"""Master pack builder: many Excel/CSV files -> ONE clean, documented workbook for Microsoft Copilot chat.

    python master_pack.py --input "D:\\Lindstrom\\exports" --out master.xlsx --customer all
    python master_pack.py --input file1.xlsx file2.xlsx --out master.xlsx

Designed for a chat model to read: few wide sheets, plain column names, pre-computed measures, a model-facing README,
values only (no formulas, no merged cells). Source files are hashed before and after and never modified.
Exit code is non-zero only on a hard failure; a build report is always written."""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, os, sys, time, traceback
import numpy as np
import pandas as pd

import data_loader as dl
import validation as vd
import metrics as mt
import measures as ms
import integrity as ig
from decisions import Decisions
from schema import TABLES

EXTS = (".xlsx", ".xlsm", ".csv")
DIM_TABLES = ("customers", "sites", "products", "laundries", "baselines", "industry_priorities", "assumptions", "reference_totals")
DROPPED_FREE_TEXT = {"laundries": ["note"], "products": ["material_note"], "baselines": ["assumption_note"], "industry_priorities": ["dashboard_emphasis"]}
MAX_ROWS = 1_000_000 - 10
MAX_EXCLUDED_LISTED = 5000
MEASURES_SITE_MONTH_MAX = 120_000     # above this many values the site-by-month level stays on Analysis only (keeps Measures small enough to ground)
SPLIT_DETAIL_ABOVE = 250_000        # total fact rows above which facts go to a separate Master_Detail file


# ------------------------------------------------------------------------------------------------ input
def discover(inputs) -> list[str]:
    """Files and/or folders (recursive). Skips Excel lock files and our own earlier outputs."""
    out = []
    for p in inputs:
        if os.path.isdir(p):
            for root, _, names in os.walk(p):
                for n in names:
                    if n.lower().endswith(EXTS) and not n.startswith("~$") and not n.startswith("Lindstrom_Master_") and not n.startswith("Master_") and not n.lower().endswith("_for_copilot.xlsx"):
                        out.append(os.path.join(root, n))
        elif os.path.isfile(p) and p.lower().endswith(EXTS):
            out.append(p)
    return sorted(dict.fromkeys(os.path.abspath(x) for x in out))


def sha256(path_or_bytes) -> str:
    h = hashlib.sha256()
    if isinstance(path_or_bytes, (bytes, bytearray)):
        h.update(path_or_bytes)
    else:
        with open(path_or_bytes, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    return h.hexdigest()


def label(path: str, root: str | None) -> str:
    """Stable, readable source name: relative to the input folder when there is one."""
    return os.path.relpath(path, root).replace("\\", "/") if root else os.path.basename(path)


# ------------------------------------------------------------------------------------------------ core pipeline
def load_tables(sources, decisions: Decisions | None = None, progress=None, skip_docs=True):
    """sources: list of (name, path|bytes). One file at a time is read into frames and its bytes released.
    -> dict(raw, mapping, T0, load_issues, presence, skipped, read_errors)"""
    decisions = decisions or Decisions()
    raw, skipped, errors = {}, [], []
    n = len(sources)
    for i, (name, src) in enumerate(sources, 1):
        blob = src
        if isinstance(src, str):
            with open(src, "rb") as f:
                blob = f.read()
        raw.update(dl.read_workbooks([(name, blob)], skip_docs=skip_docs, skipped=skipped, errors=errors))
        del blob
        if progress:
            progress(i / max(n, 1) * 0.6, f"Read {i} of {n} files")
    mapping = decisions.apply_mapping(raw, dl.auto_map(raw))
    return dict(raw=raw, mapping=mapping, skipped=skipped, read_errors=errors)


def tidy_dimensions(T):
    """Across many files the same customers/sites/products repeat; identical dimension rows are collapsed, not flagged.
    Returns (T, n_collapsed per table). Fact tables are never touched here (duplicates there are real validation errors)."""
    T2, n = dict(T), {}
    for t in DIM_TABLES:
        df = T2.get(t)
        if df is None or df.empty:
            continue
        key = [k for k in TABLES[t].key if k in df.columns] or None
        content = [c for c in df.columns if c not in vd.META]
        dup = df.duplicated(content, keep="first")
        if dup.any():
            n[t] = int(dup.sum())
            # keep one row per identical content but remember the dropped uids so lineage can count them
            T2[t] = df[~dup].reset_index(drop=True)
    return T2, n


def validate_and_clean(raw, mapping, decisions: Decisions | None = None):
    decisions = decisions or Decisions()
    T, load_issues, presence = dl.build_tables(raw, mapping)
    T, collapsed = tidy_dimensions(T)
    issues = vd.validate(T, load_issues, mapping, raw, presence)
    actions = decisions.actions_for(issues)
    T_clean, log = vd.apply_exclusions(T, issues, actions, decisions.uid_reasons())
    T_clean = mt.enrich(T_clean)
    return dict(T=T, T_clean=T_clean, issues=issues, log=log, actions=actions, presence=presence, collapsed=collapsed)


def filter_customer(T, customer):
    """customer: 'all' | customer_id | exact customer name (case-insensitive)."""
    if customer in (None, "", "all"):
        return T, None
    C = T.get("customers")
    cid = None
    if C is not None and not C.empty:
        hit = C[(C.customer_id.astype(str) == customer) | (C.customer_name.astype(str).str.lower() == str(customer).lower())]
        if len(hit):
            cid = hit.iloc[0].customer_id
    if cid is None:
        cid = customer
    T2 = {}
    S = T["sites"]
    sites = set(S[S.customer_id == cid].site_id)
    for k, df in T.items():
        if k == "customers":
            T2[k] = df[df.customer_id == cid]
        elif k == "sites":
            T2[k] = df[df.customer_id == cid]
        elif k in vd.FACT:
            T2[k] = df[df.site_id.isin(sites)] if "site_id" in df else df
        else:
            T2[k] = df
    labs = set()
    for k in ("service_activity", "repairs", "service_cycles"):
        if k in T2 and "laundry_id" in T2[k]:
            labs |= set(T2[k].laundry_id.dropna())
    for k in ("laundries", "resources", "waste"):
        if k in T2 and "laundry_id" in T2[k] and labs:
            T2[k] = T2[k][T2[k].laundry_id.isin(labs)]
    return T2, cid


# ------------------------------------------------------------------------------------------------ output sheets
def _iso(df):
    for c in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[c]):
            df[c] = df[c].dt.strftime("%Y-%m-%d %H:%M:%S").where(df[c].notna(), None)
    return df


def _ids_text(df):
    for c in df.columns:
        if c.endswith(" ID") or c in ("Month",):
            df[c] = df[c].map(lambda v: None if pd.isna(v) else str(v))
    return df


def _round(df, nd=2):
    for c in df.select_dtypes("number").columns:
        df[c] = df[c].round(nd)
    return df


# (internal column) -> (plain name, unit, definition)
FACT_COLS = {
    "service_activity": [("month", "Month", "", "Calendar month, YYYY-MM"), ("customer_id", "Customer ID", "", "Customer key"), ("customer", "Customer", "", "Customer name"),
                         ("site_id", "Site ID", "", "Site key"), ("site", "Site", "", "Site name"), ("product_id", "Product ID", "", "Product key"),
                         ("laundry_id", "Laundry ID", "", "Laundry key"), ("active_wearers", "Active wearers", "wearers", "Wearers in the month (summed over product rows; may double-count)"),
                         ("allocated_pieces", "Garments allocated", "garments", "Garments assigned"),
                         ("active_assets_scanned", "Garments with scan activity", "garments", "Garments that recorded scan activity in the month"),
                         ("washed_pieces", "Garments washed", "garments", "Pieces washed"), ("packed_pieces", "Garments packed", "garments", "Pieces packed"),
                         ("washing_pct", "Washing %", "%", "Washing percentage as reported"),
                         ("customer_washed_kg", "Washed kg", "kg", "Customer-attributed washed weight"), ("service_requests", "Service requests", "requests", "Service requests in the month"),
                         ("data_status", "Source data status", "", "Label carried in the source file (e.g. SYNTHETIC)")],
    "repairs": [("month", "Month", "", "Calendar month, YYYY-MM"), ("customer_id", "Customer ID", "", "Customer key"), ("customer", "Customer", "", "Customer name"),
                ("site_id", "Site ID", "", "Site key"), ("site", "Site", "", "Site name"), ("product_id", "Product ID", "", "Product key"), ("laundry_id", "Laundry ID", "", "Laundry key"),
                ("repair_type", "Repair type", "", "Kind of repair"), ("repair_count", "Repairs", "repairs", "Counted repair events"),
                ("repair_quotient_pct", "Repair quotient %", "%", "Repair quotient as reported"),
                ("estimated_replacements_postponed", "Replacements postponed (source estimate)", "pieces", "Estimate carried in the source file; Measures use repairs x factor instead"),
                ("data_status", "Source data status", "", "Label carried in the source file")],
    "service_cycles": [("asset_id", "Asset ID", "", "Garment RFID asset (not a person)"), ("cycle_number", "Cycle number", "", "Cycle counter for the asset"),
                       ("customer_id", "Customer ID", "", "Customer key"), ("site_id", "Site ID", "", "Site key"), ("laundry_id", "Laundry ID", "", "Laundry key"), ("product_id", "Product ID", "", "Product key"),
                       ("pickup_timestamp", "Pickup time", "", "ISO date-time"), ("in_laundry_timestamp", "In laundry time", "", "ISO date-time"),
                       ("out_laundry_timestamp", "Out of laundry time", "", "ISO date-time"), ("delivered_timestamp", "Delivered time", "", "ISO date-time"),
                       ("cycle_hours", "Cycle hours", "hours", "Pickup to delivery"), ("performance_flag", "Performance flag", "", "ON_TIME or late flag as reported"),
                       ("data_status", "Source data status", "", "Label carried in the source file")],
    "resources": [("month", "Month", "", "Calendar month, YYYY-MM"), ("laundry_id", "Laundry ID", "", "Laundry key"), ("laundry_name", "Laundry", "", "Laundry name"), ("country", "Country", "", "Laundry country"),
                  ("washed_kg", "Laundry washed kg", "kg", "Total washed weight of the laundry in the month"), ("energy_kwh_per_kg", "Energy kWh per kg", "kWh/kg", "Laundry energy intensity"),
                  ("fresh_water_l_per_kg", "Fresh water L per kg", "L/kg", "Laundry water intensity"), ("process_energy_kwh", "Process energy kWh", "kWh", "Laundry process energy"),
                  ("fresh_water_l", "Fresh water L", "L", "Laundry fresh water"), ("process_emissions_kgco2e", "Process CO2e kg", "kgCO2e", "Laundry process emissions"),
                  ("delivery_emissions_kgco2e", "Delivery CO2e kg", "kgCO2e", "Laundry delivery emissions"),
                  ("_share", "Share of laundry kg in this file %", "%", "Customer kg in this file / laundry washed kg x 100: the allocation share used"),
                  ("data_status", "Source data status", "", "Label carried in the source file")],
    "waste": [("month", "Month", "", "Calendar month, YYYY-MM"), ("laundry_id", "Laundry ID", "", "Laundry key"), ("recycling_kg", "Recycling kg", "kg", "Textile waste recycled"),
              ("reuse_kg", "Reuse kg", "kg", "Textile waste reused"), ("energy_recovery_kg", "Energy recovery kg", "kg", "Textile waste to energy recovery"),
              ("incineration_kg", "Incineration kg", "kg", "Textile waste incinerated"), ("textile_waste_total_kg", "Textile waste total kg", "kg", "Total textile waste of the laundry"),
              ("_rec", "Recycling %", "%", "(recycling + reuse) / total"), ("_div", "Diversion %", "%", "(recycling + reuse + energy recovery) / total"),
              ("data_status", "Source data status", "", "Label carried in the source file")],
}
DIM_COLS = {
    "customers": [("customer_id", "Customer ID", "", "Customer key"), ("customer_name", "Customer", "", "Customer name"), ("industry", "Industry", "", "Industry segment"),
                  ("segment", "Segment", "", "Customer segment"), ("hq_country", "HQ country", "", "Headquarters country"), ("priority_topics", "Priority topics", "", "Topics the customer cares about (from CRM)"),
                  ("_lo", "Utilisation band low %", "%", "Lower end of the utilisation band used for this customer"), ("_hi", "Utilisation band high %", "%", "Upper end of the band used"),
                  ("_src", "Utilisation band source", "", "General default, industry default or KAM override")],
    "sites": [("site_id", "Site ID", "", "Site key"), ("site_name", "Site", "", "Site name"), ("customer_id", "Customer ID", "", "Customer key"), ("customer", "Customer", "", "Customer name"),
              ("country", "Country", "", "Site country"), ("city", "City", "", "Site city"), ("site_type", "Site type", "", "Kind of site"), ("primary_laundry_id", "Primary laundry ID", "", "Laundry serving the site"),
              ("laundry", "Primary laundry", "", "Laundry name"), ("laundry_country", "Laundry country", "", "Laundry country")],
    "products": [("product_id", "Product ID", "", "Product key"), ("product_name", "Product", "", "Product name"), ("product_group", "Product group", "", "Product category"),
                 ("avg_weight_kg", "Average weight kg", "kg", "Average garment weight"), ("product_footprint_kgco2e", "Footprint kgCO2e", "kgCO2e", "Product footprint (as supplied)"),
                 ("purchase_cost_eur", "Replacement cost EUR", "EUR", "Purchase cost used for purchases avoided")],
    "laundries": [("laundry_id", "Laundry ID", "", "Laundry key"), ("laundry_name", "Laundry", "", "Laundry name"), ("country", "Country", "", "Laundry country"), ("country_code", "Country code", "", "ISO country code")],
}


def _pick(df, spec):
    out = pd.DataFrame(index=df.index)
    for src, name, _, _ in spec:
        out[name] = df[src] if src in df.columns else np.nan
    return out.dropna(axis=1, how="all") if False else out


def build_sheets(T, T0_issues, log, decisions, report, baseline_id=None, bands=None):
    """-> (ordered dict sheet -> DataFrame, data dictionary rows)"""
    bands = bands or decisions.bands_obj()
    sheets, doc = {}, []
    S = T["sites"].drop_duplicates("site_id")
    C = T["customers"].drop_duplicates("customer_id") if T.get("customers") is not None and not T["customers"].empty else pd.DataFrame(columns=["customer_id", "customer_name", "industry"])
    cname = C.set_index("customer_id").customer_name.to_dict() if "customer_name" in C else {}
    cind = C.set_index("customer_id").industry.to_dict() if "industry" in C else {}
    L = T.get("laundries")
    lname = L.drop_duplicates("laundry_id").set_index("laundry_id").laundry_name.to_dict() if L is not None and not L.empty else {}
    lcty = L.drop_duplicates("laundry_id").set_index("laundry_id").country.to_dict() if L is not None and not L.empty else {}
    sname = S.set_index("site_id").site_name.to_dict()
    scty = S.set_index("site_id").country.to_dict()
    stype = S.set_index("site_id").site_type.to_dict()

    # ---------- measures
    F = ms.build_frames(T, baseline_id)
    baseline_name = F["baseline"]
    if F["A"] is None:
        raise ValueError("No usable service-activity data (month, site, washed kg): nothing to analyse.")
    M_sm = ms.aggregate(F, ["customer_id", "site_id", "month"])
    M_cm = ms.aggregate(F, ["customer_id", "month"])
    M_s = ms.aggregate(F, ["customer_id", "site_id"])
    M_c = ms.aggregate(F, ["customer_id"])
    months = sorted(M_sm.month.dropna().unique())
    latest, first = months[-1], months[0]
    period = f"{first} to {latest}" if first != latest else first

    def band_for(cid):
        return bands.for_customer(cid, cind.get(cid))

    # ---------- Analysis (wide, chat-ready)
    A = M_sm.copy()
    A.insert(1, "Customer", A.customer_id.map(cname))
    A.insert(2, "Industry", A.customer_id.map(cind))
    A["Site"] = A.site_id.map(sname)
    A["Country"] = A.site_id.map(scty)
    A["Site type"] = A.site_id.map(stype)
    bl = A.customer_id.map(lambda c: band_for(c)[:2])
    A["Utilisation band low %"] = [b[0] for b in bl]
    A["Utilisation band high %"] = [b[1] for b in bl]
    A["Utilisation vs band"] = np.where(A["Utilisation %"].isna(), "n/a", np.where(A["Utilisation %"] < A["Utilisation band low %"], "below band",
                                         np.where(A["Utilisation %"] > A["Utilisation band high %"], "above band", "within band")))
    A["Baseline"] = baseline_name
    A["Status note"] = ms.STATUS_NOTE
    A = A.rename(columns={"customer_id": "Customer ID", "site_id": "Site ID", "month": "Month"})
    lead = ["Month", "Customer ID", "Customer", "Industry", "Site ID", "Site", "Country", "Site type"]
    A = A[lead + ms.MEASURE_ORDER + ["Utilisation band low %", "Utilisation band high %", "Utilisation vs band", "Baseline", "Status note"]]
    A = A.sort_values(["Customer ID", "Site ID", "Month"], kind="stable").reset_index(drop=True)

    # ---------- Measures (long, with status per number)
    def long(M, level, keycols):
        m = M.copy()
        m["Level"] = level
        if "month" not in m.columns:
            m["month"] = period
        m["Customer"] = m.customer_id.map(cname)
        m["Site ID"] = m["site_id"] if "site_id" in m else ""
        m["Site"] = m["Site ID"].map(sname) if "site_id" in m else ""
        idv = ["Level", "customer_id", "Customer", "Site ID", "Site", "month"]
        t = m.melt(id_vars=idv, value_vars=ms.MEASURE_ORDER, var_name="Measure", value_name="Value").dropna(subset=["Value"])
        return t
    parts = [long(M_cm, "Customer, month", None), long(M_s, "Site, whole period", None), long(M_c, "Customer, whole period", None)]
    site_month_in_measures = int(M_sm[ms.MEASURE_ORDER].notna().sum().sum()) <= MEASURES_SITE_MONTH_MAX
    if site_month_in_measures:
        parts.insert(0, long(M_sm, "Site, month", None))
    Me = pd.concat(parts, ignore_index=True)
    Me["Unit"] = Me.Measure.map(lambda k: ms.MEASURES[k][0])
    Me["Status"] = Me.Measure.map(lambda k: ms.MEASURES[k][1])
    Me["Basis"] = Me.Measure.map(lambda k: f"Baseline: {baseline_name}" if "baseline" in k else ("Repair factor 1.0 (Base case)" if "estimate" in k else ""))
    Me = Me.rename(columns={"customer_id": "Customer ID", "month": "Period"})
    Me["Site ID"] = Me["Site ID"].fillna("")
    Me["Site"] = Me["Site"].fillna("")
    Me["_o"] = Me.Level.map({"Customer, whole period": 0, "Customer, month": 1, "Site, whole period": 2, "Site, month": 3})
    Me["_m"] = Me.Measure.map({k: i for i, k in enumerate(ms.MEASURE_ORDER)})
    Me = Me.sort_values(["_o", "Customer ID", "Site ID", "Period", "_m"], kind="stable").drop(columns=["_o", "_m"])
    Me = Me[["Level", "Customer ID", "Customer", "Site ID", "Site", "Period", "Measure", "Value", "Unit", "Status", "Basis"]].reset_index(drop=True)

    # ---------- Site_Summary / Customer_Summary
    latest_site = M_sm[M_sm.month == latest].set_index(["customer_id", "site_id"])
    SS = M_s.copy()
    SS = SS.join(latest_site[["Garments allocated", "Utilisation %", "Allocated garments with no scan activity"]].add_suffix(" (latest month)"), on=["customer_id", "site_id"])
    yo = {}
    for (cid, sid), g in M_sm.groupby(["customer_id", "site_id"]):
        yo[(cid, sid)] = ms.yoy_pct(g, "Washed kg")
    reasons, nrs, lvl, lo_l, hi_l, vs = [], [], [], [], [], []
    SS = SS.reset_index(drop=True)
    SS["_k"] = list(zip(SS.customer_id, SS.site_id))
    for i, r in SS.iterrows():
        lo, hi, _, _ = band_for(r.customer_id)
        cust = SS[SS.customer_id == r.customer_id]
        txt, n, lv = ms.notable_text(r, cust, SS, (lo, hi), prior=yo.get(r._k))
        reasons.append(txt); nrs.append(n); lvl.append(lv); lo_l.append(lo); hi_l.append(hi)
        u = r["Utilisation % (latest month)"]
        vs.append("n/a" if pd.isna(u) else "below band" if u < lo else "above band" if u > hi else "within band")
    SS["Utilisation band low %"], SS["Utilisation band high %"], SS["Utilisation vs band"] = lo_l, hi_l, vs
    SS["Washed kg vs last year %"] = [yo.get(k) for k in SS._k]
    SS["Why notable"], SS["Notable level"] = reasons, lvl
    SS["Customer"] = SS.customer_id.map(cname)
    SS["Site"] = SS.site_id.map(sname)
    SS["Country"] = SS.site_id.map(scty)
    SS["Site type"] = SS.site_id.map(stype)
    SS["Period"] = period
    SS = SS.rename(columns={"customer_id": "Customer ID", "site_id": "Site ID"})
    keep = ["Customer ID", "Customer", "Site ID", "Site", "Country", "Site type", "Period", "Washed kg", "Garments allocated (latest month)", "Utilisation % (latest month)",
            "Allocated garments with no scan activity (latest month)", "Utilisation band low %", "Utilisation band high %", "Utilisation vs band", "Service requests",
            "Service requests per 1000 garments", "On-time %", "Repairs", "Repairs per 1000 garments", "Repairs per 1000 kg", "Water saved vs baseline L", "Energy saved vs baseline kWh",
            "CO2e saved vs baseline kg", "Total CO2e kg", "Textile waste kg", "Recycling %", "Diversion %", "Washed kg vs last year %", "Why notable", "Notable level"]
    SS = SS[keep].sort_values(["Customer ID", "Notable level", "Site ID"], key=lambda s: s.map({"notable": 0, "minor": 1, "none": 2}) if s.name == "Notable level" else s, kind="stable").reset_index(drop=True)

    CS = M_c.copy()
    CS["Customer"] = CS.customer_id.map(cname); CS["Industry"] = CS.customer_id.map(cind); CS["Period"] = period
    nsites = M_s.groupby("customer_id").site_id.nunique()
    CS["Sites"] = CS.customer_id.map(nsites)
    latest_c = M_cm[M_cm.month == latest].set_index("customer_id")
    CS["Garments allocated (latest month)"] = CS.customer_id.map(latest_c["Garments allocated"])
    CS["Utilisation % (latest month)"] = CS.customer_id.map(latest_c["Utilisation %"])
    CS["Utilisation band low %"] = CS.customer_id.map(lambda c: band_for(c)[0])
    CS["Utilisation band high %"] = CS.customer_id.map(lambda c: band_for(c)[1])
    CS["Utilisation band source"] = CS.customer_id.map(lambda c: band_for(c)[2])
    CS["Sites outside the band"] = CS.customer_id.map(SS[SS["Utilisation vs band"].isin(["below band", "above band"])].groupby("Customer ID").size()).fillna(0).astype(int)
    CS["Notable sites"] = CS.customer_id.map(SS[SS["Notable level"] == "notable"].groupby("Customer ID").size()).fillna(0).astype(int)
    ycol = {}
    for cid, g in M_cm.groupby("customer_id"):
        ycol[cid] = ms.yoy_pct(g, "Washed kg")
    CS["Washed kg vs last year %"] = CS.customer_id.map(ycol)
    CS = CS.rename(columns={"customer_id": "Customer ID"})
    CS = CS[["Customer ID", "Customer", "Industry", "Period", "Sites", "Washed kg", "Garments allocated (latest month)", "Utilisation % (latest month)", "Utilisation band low %",
             "Utilisation band high %", "Utilisation band source", "Sites outside the band", "Notable sites", "Service requests", "On-time %", "Repairs", "Purchases avoided EUR (estimate)",
             "Replacements postponed (estimate)", "Water saved vs baseline L", "Energy saved vs baseline kWh", "CO2e saved vs baseline kg", "Total CO2e kg", "Textile waste kg",
             "Recycling %", "Diversion %", "Washed kg vs last year %"]]

    # ---------- dimensions
    cust = C.copy()
    cust["_lo"] = cust.customer_id.map(lambda c: band_for(c)[0]); cust["_hi"] = cust.customer_id.map(lambda c: band_for(c)[1]); cust["_src"] = cust.customer_id.map(lambda c: band_for(c)[2])
    sites = S.copy(); sites["customer"] = sites.customer_id.map(cname); sites["laundry"] = sites.primary_laundry_id.map(lname); sites["laundry_country"] = sites.primary_laundry_id.map(lcty)
    dims = {"Customers": _pick(cust, DIM_COLS["customers"]), "Sites": _pick(sites, DIM_COLS["sites"]),
            "Products": _pick(T["products"], DIM_COLS["products"]) if T.get("products") is not None else pd.DataFrame(),
            "Laundries": _pick(T["laundries"], DIM_COLS["laundries"]) if T.get("laundries") is not None else pd.DataFrame()}

    # ---------- facts
    facts = {}
    a = T["service_activity"].copy(); a["customer"] = a.customer_id.map(cname); a["site"] = a.site_id.map(sname)
    facts["Fact_Service_Activity"] = _pick(a.sort_values(["month", "site_id", "product_id", "laundry_id"], kind="stable"), FACT_COLS["service_activity"])
    if T.get("repairs") is not None and not T["repairs"].empty:
        r = T["repairs"].copy(); r["customer"] = r.customer_id.map(cname); r["site"] = r.site_id.map(sname)
        facts["Fact_Repairs"] = _pick(r.sort_values(["month", "site_id", "product_id", "repair_type"], kind="stable"), FACT_COLS["repairs"])
    if T.get("service_cycles") is not None and not T["service_cycles"].empty:
        facts["Fact_Cycles"] = _pick(T["service_cycles"].sort_values(["asset_id", "cycle_number"], kind="stable"), FACT_COLS["service_cycles"])
    if T.get("resources") is not None and not T["resources"].empty:
        rs = T["resources"].copy()
        lm = a.groupby(["month", "laundry_id"]).customer_washed_kg.sum()
        rs["_share"] = [100 * lm.get((m, l), np.nan) / k if k else np.nan for m, l, k in zip(rs.month, rs.laundry_id, rs.washed_kg)]
        facts["Fact_Resources"] = _pick(rs.sort_values(["month", "laundry_id"], kind="stable"), FACT_COLS["resources"])
    if T.get("waste") is not None and not T["waste"].empty:
        w = T["waste"].copy()
        routes = w[["recycling_kg", "reuse_kg", "energy_recovery_kg", "incineration_kg"]].sum(axis=1, min_count=1)
        tot = w.textile_waste_total_kg.where(w.textile_waste_total_kg.notna(), routes)
        w["_rec"] = 100 * (w.recycling_kg.fillna(0) + w.reuse_kg.fillna(0)) / tot.replace(0, np.nan)
        w["_div"] = 100 * (w.recycling_kg.fillna(0) + w.reuse_kg.fillna(0) + w.energy_recovery_kg.fillna(0)) / tot.replace(0, np.nan)
        facts["Fact_Waste"] = _pick(w.sort_values(["month", "laundry_id"], kind="stable"), FACT_COLS["waste"])
    for k, df in facts.items():                            # drop columns that are entirely empty (the source never had them)
        facts[k] = df.dropna(axis=1, how="all")

    out = dict(Analysis=A, Measures=Me, Customer_Summary=CS, Site_Summary=SS)
    out.update(dims)
    out.update(facts)
    meta = dict(site_month_in_measures=site_month_in_measures, latest=latest, first=first, period=period, baseline=baseline_name, months=len(months), bands={c: band_for(c) for c in C.customer_id},
                customers=cname, n_customers=len(cname), n_sites=len(sname))
    # dictionary rows for output columns that come from specs
    for sheet, spec in (("Fact_Service_Activity", FACT_COLS["service_activity"]), ("Fact_Repairs", FACT_COLS["repairs"]), ("Fact_Cycles", FACT_COLS["service_cycles"]),
                        ("Fact_Resources", FACT_COLS["resources"]), ("Fact_Waste", FACT_COLS["waste"]), ("Customers", DIM_COLS["customers"]), ("Sites", DIM_COLS["sites"]),
                        ("Products", DIM_COLS["products"]), ("Laundries", DIM_COLS["laundries"])):
        if sheet in out:
            for src, name, unit, d in spec:
                if name in out[sheet].columns:
                    doc.append((sheet, name, d, unit, "SOURCE" if not src.startswith("_") else "CALCULATED", src))
    return out, doc, meta


def finalise_formats(sheets):
    for k, df in sheets.items():
        _iso(df); _ids_text(df)
        for c in df.select_dtypes("number").columns:
            df[c] = df[c].round(3)
        sheets[k] = df
    return sheets


# ------------------------------------------------------------------------------------------------ documentation sheets
PROMPT = """You are analysing the attached Lindström workbook. Use only the sheets in this file.
Do not invent numbers, customers, sites or time periods.

Where to look
- Start with sheet Analysis (one row per customer / site / month, every KPI in a column) and Site_Summary / Customer_Summary (whole period, with "Why notable").
- Measures lists every pre-computed number with its Status. Validation_Exceptions and Open_Questions say what is doubtful or missing.

Definitions
- Month is YYYY-MM. Washed kg is customer-attributed washed weight.
- Utilisation = garments with scan activity / garments allocated. It is a signal, not proof of idleness.
  "Allocated garments with no scan activity" = allocated minus with-scan-activity.
- Repairs are counted events; a repair is not proof that a replacement was avoided.
- CO2e, water and energy are calculated or allocated; see the Status of every measure row.
- Status values: CALCULATED, MEASURED, ALLOCATED, ESTIMATED, TEAM_ASSUMPTION, KAM_REPORTED, EXTERNAL_CLAIM, CONTRACTUAL, SYNTHETIC.

How to answer
1. Say what you looked at (sheet + columns) and the period.
2. Give the number, its unit and its status.
3. Compare in plain language: vs last year, vs the portfolio average, vs the customer's own sites.
4. If the data cannot answer, say what is missing (see Open_Questions). Do not estimate silently.
5. Keep it short: a read, the key numbers, one chart if useful, and what to do next.

Never
- Never add, average or extrapolate raw Fact_ rows yourself if a Measures or Analysis value exists.
- Never call garments "idle".
- Never present an estimate as measured.
- Never combine customers unless asked.
- If you cannot read a sheet, say so instead of guessing.

Try these first
- Which sites have the most service requests per 1000 garments this year?
- How has washed kg changed versus last year?
- Where is utilisation outside the healthy band, and why?
- What are the three biggest water or CO2 savings versus baseline?
- Which sites should we discuss in the next QBR, and what should we say?"""

HOW_TO = """HOW TO USE THIS WITH MICROSOFT COPILOT  (for you, not for Copilot)
1. Open Copilot chat and attach the workbook {xlsx}.
2. Send this as your FIRST message: Follow the instructions in the START_HERE sheet of the attached workbook.
3. If Copilot does not follow it, paste everything below the line instead.
4. At the end, ask Copilot for the DECK ADDITIONS block and paste it back into the app.
------------------------------------------------------------ paste from here ------------------------------------------------------------
"""


SLIM_SHEETS = ["START_HERE", "Customer_Summary", "Site_Summary", "Analysis", "Open_Questions", "Validation_Exceptions", "Assumptions"]   # what a chat model needs; the rest stays in the full pack


def start_here_rows(T, decisions):
    """First sheet: the script for the chat model, the anomalies already found, and the format for the DECK ADDITIONS block."""
    import portfolio as pf, anomalies as an, deck_draft as dd
    from assumptions import Uncertainty
    CU = pf.customers(T).set_index("customer_id")
    bsel = mt.default_baseline(T)
    _, SA = pf.portfolio(T, bsel, "Base", Uncertainty())
    RI = pf.repair_intensity(T)
    bands = decisions.bands_obj()
    names = ", ".join(CU.customer)
    r = [("What this is", f"Customer data for: {names}. You are helping a key account manager (KAM) prepare for a customer steering committee meeting. Follow this sheet."),
         ("Your job", "Reply first with at most three short lines: the top three findings below in plain words, then ask which to start with. Then talk it through using only the sheets in this file. When the KAM says they are done, write the DECK ADDITIONS block (format below)."),
         ("Where to look", "Site_Summary and Customer_Summary: whole period, with 'Why notable'. Analysis: one row per site per month, every KPI in a column. Open_Questions, Validation_Exceptions and Assumptions say what is doubtful or missing."),
         ("Rules", "Use only this file. Do not invent numbers, customers, sites or periods. Give each number with its unit and status (CALCULATED, ALLOCATED, ESTIMATED). Utilisation is a signal, not proof of idleness: never call garments idle. Never present an estimate as measured. Never put calculated figures inside the DECK ADDITIONS block: it carries topics, questions and requests only.")]
    for cid in CU.index:
        lo, hi, _, _ = bands.for_customer(cid, CU.industry[cid])
        A = an.find(SA[SA.customer_id == cid], RI, cid, lo, hi)
        lines = an.to_lines(A, 3) or ["Nothing stands out against the references."]
        for i, l in enumerate(lines):
            r.append((f"Top findings: {CU.customer[cid]}" if i == 0 else "", l))
    for i, l in enumerate(dd.ADD_FORMAT.split("\n")):
        r.append(("DECK ADDITIONS format" if i == 0 else "", l))
    return pd.DataFrame(r, columns=["Section", "Text"])


def readme_rows(report, meta, files_n, split):
    r = [
        ("What this file is", f"Lindström customer value master pack, built {report['built_on']} from {files_n} source file(s). Period {meta['period']}. {meta['n_customers']} customer(s), {meta['n_sites']} site(s). Made to be read by a chat model (Microsoft Copilot): values only, one header row per sheet, no formulas, no merged cells, no blank rows."),
        ("How to use it", "Attach this workbook in Copilot chat and send: Follow the instructions in the START_HERE sheet. (Fallback: paste the text on sheet Prompt_Card as the first message.) Then talk it through; at the end ask for the DECK ADDITIONS block and paste it back into the app. Every number was calculated by code, never by an AI model."),
        ("Read these first", "Analysis: one row per customer / site / month with every KPI in a column. Site_Summary and Customer_Summary: whole-period figures with a plain-language 'Why notable'. Measures: the same numbers in long form with Unit and Status."),
        ("Sheet: Analysis", "Grain: customer x site x month. Plain column names (e.g. 'Utilisation %'). IDs kept alongside. Includes the utilisation band used and whether the site is below / within / above it."),
        ("Sheet: Measures", "Grain: one row per customer or site, per month or whole period, per measure. Columns Unit, Status, Basis. Levels: 'Site, month', 'Customer, month', 'Site, whole period', 'Customer, whole period'. Rows with no value are not listed." + ("" if meta.get("site_month_in_measures", True) else " NOTE: this file is large, so the 'Site, month' level is NOT in Measures; read site-by-month numbers on sheet Analysis.")),
        ("Sheet: Customer_Summary / Site_Summary", "Grain: customer, or customer x site, over the whole period. Utilisation is for the latest month; other figures cover the whole period. 'Why notable' compares with the band, the customer's other sites and last year (only when 24 months exist)."),
        ("Sheets: Customers, Sites, Products, Laundries", "Clean dimension tables. Keys: Customer ID, Site ID, Product ID, Laundry ID, Month (YYYY-MM)."),
        ("Sheets: Fact_*", "Cleaned source rows: Fact_Service_Activity (customer x site x product x laundry x month), Fact_Repairs (... x repair type), Fact_Cycles (one row per asset cycle), Fact_Resources and Fact_Waste (laundry x month, laundry level)." + (" Fact sheets are in the separate Detail file." if split else "")),
        ("Sheet: Data_Dictionary", "Every column: definition, unit, status, example, where it comes from."),
        ("Sheet: Lineage", "Every source file and sheet: header row, rows read, rows kept, rows excluded, how it was used and which columns were not carried."),
        ("Sheet: Validation_Exceptions / Excluded_Rows", "What looked wrong, with the exact source file, sheet and Excel row, and what was done. Source files are never changed; excluded rows are only left out of this workbook."),
        ("Sheet: Integrity_Check", "An automatic verifier re-checked the numbers: source files unchanged, every source column total replicated, exclusions accounted for, the pack consistent with itself and with an independent calculation engine. Any FAIL row means do not quote that number."),
        ("Sheet: Assumptions", "Every threshold and assumption used, its value, rationale and status."),
        ("Sheet: Open_Questions", "Questions this file cannot answer. If asked, say 'not in this file'."),
        ("What this file cannot answer", "Prices, revenue, contracts and contractual KPIs, garment lifespan effects of repairs, wearer-level data (data is aggregated; no named people), anything outside the period and customers listed here."),
        ("Status words", "CALCULATED (arithmetic on source data), ALLOCATED (laundry figure shared by washed-kg share), ESTIMATED (uses an assumption), MEASURED, TEAM_ASSUMPTION, KAM_REPORTED, EXTERNAL_CLAIM, CONTRACTUAL, SYNTHETIC."),
        ("Cautions", f"{report['n_errors']} validation error(s), {report['n_warnings']} warning(s) were found; {report['rows_excluded']} row(s) were excluded. Read Validation_Exceptions before quoting a number."),
    ]
    if report.get("synthetic"):
        r.append(("Data origin", "The source data carries the label SYNTHETIC: it is test data, not real customer data."))
    return pd.DataFrame(r, columns=["Topic", "What the model should know"])


def assumptions_rows(T, meta, decisions, report):
    from assumptions import APP_ASSUMPTIONS, Uncertainty, THRESH
    u = Uncertainty()
    rows = []
    for aid, name, rule, why, conf, treat in APP_ASSUMPTIONS:
        rows.append((aid, name, rule.format(baseline_pct=u.baseline_pct, allocation_pct=u.allocation_pct, repair_low=u.repair_low, repair_high=u.repair_high,
                                           rel_tol=THRESH["rel_tol"], ref_rel_tol=THRESH["ref_rel_tol"]), why, "TEAM_ASSUMPTION", f"Confidence {conf}. {treat}"))
    rows.append(("X11", "Baseline used", meta["baseline"], "Default baseline of the source pack, unless chosen otherwise", "SOURCE", "All savings in this file are against this baseline."))
    rows.append(("X12", "Scenario", "Base case (repair factor 1.0, baseline and allocation factors 1.0)", "Pack values as supplied; no Low/High range in this file", "TEAM_ASSUMPTION", "Ranges are available in the app."))
    rows.append(("X13", "Year-on-year", "Latest 12 months vs the 12 before; only when 24 months exist", "Avoids comparing partial years", "TEAM_ASSUMPTION", "Otherwise the file says it cannot answer."))
    for cid, (lo, hi, src, why) in meta["bands"].items():
        rows.append((f"BAND-{cid}", f"Utilisation band for {meta['customers'].get(cid, cid)}", f"{lo:.0f}-{hi:.0f} %", why, "TEAM_ASSUMPTION" if "override" not in src.lower() else "KAM_REPORTED", f"Source: {src}. Below = possible excess allocated garments; above = more garments may be needed."))
    rows.append(("X14", "Textile diversion", "(recycling + reuse + energy recovery) / total waste", "Energy recovery is diversion from incineration but not recycling", "TEAM_ASSUMPTION", "Recycling % excludes energy recovery."))
    A = T.get("assumptions")
    if A is not None and not A.empty:
        for r in A.itertuples():
            rows.append((f"SRC-{r.assumption_id}", r.assumption, r.value_or_rule, r.rationale if isinstance(r.rationale, str) else "", "SOURCE", "Assumption registry supplied in the source file."))
    return pd.DataFrame(rows, columns=["ID", "Assumption", "Value used", "Rationale", "Status", "Note"])


def exception_rows(issues, log, decisions, actions):
    rows = []
    for r in issues.itertuples():
        act = actions.get(r.id, r.default_action)
        by = {}
        for u in r.uids:
            src, row = u.rsplit("#", 1)
            by.setdefault(src, []).append(int(row))
        decision = "Rows excluded from this workbook" if act == "exclude" and r.uids else "Kept and flagged"
        if not by:
            rows.append((r.severity, r.check, r.table, "", "", "", 0, r.explanation, r.fix, decision, r.scope))
        for src, rs in by.items():
            f, sh = (src.split("::", 1) + [""])[:2]
            rs = sorted(rs)
            shown = ", ".join(map(str, rs[:50])) + (f" (+{len(rs) - 50} more)" if len(rs) > 50 else "")
            rows.append((r.severity, r.check, r.table, f, sh, shown, len(rs), r.explanation, r.fix, decision, r.scope))
    cols = ["Severity", "Check", "Table", "Source file", "Sheet", "Excel rows", "Rows affected", "Explanation", "Suggested fix", "Decision", "Scope"]
    ev = pd.DataFrame(rows, columns=cols)
    sev = {"ERROR": 0, "WARNING": 1, "INFO": 2}
    ev = ev.sort_values(["Severity", "Check", "Source file", "Sheet"], key=lambda s: s.map(sev) if s.name == "Severity" else s, kind="stable").reset_index(drop=True)
    ex = pd.DataFrame([(l.source.split("::")[0], l.sheet, int(l.row), l.table, l.reason) for l in log.itertuples()],
                      columns=["Source file", "Sheet", "Excel row", "Table", "Reason"])
    if len(ex):
        ex = ex.sort_values(["Source file", "Sheet", "Excel row"], kind="stable").reset_index(drop=True)
        if len(ex) > MAX_EXCLUDED_LISTED:
            more = len(ex) - MAX_EXCLUDED_LISTED
            ex = pd.concat([ex.head(MAX_EXCLUDED_LISTED), pd.DataFrame([("(more)", "", None, "", f"{more} further excluded rows are not listed; counts per source sheet are in Validation_Exceptions and Lineage.")], columns=ex.columns)], ignore_index=True)
    return ev, ex


def lineage_rows(raw, mapping, log, skipped, read_errors, hashes, collapsed):
    ex = log.groupby("source").size().to_dict() if len(log) else {}
    rows = []
    for key, rs in raw.items():
        sm = mapping.get(key)
        used = bool(sm and sm.include and sm.table)
        carried = {c for c in (sm.cols.values() if sm else []) if c}
        notc = [c for c in rs.df.columns if c not in carried]
        kept_est = None
        rows.append((rs.file, rs.sheet, rs.header_row, len(rs.df), None, ex.get(key, 0), sm.table if used else "(not used)", round(sm.score, 2) if sm else None,
                     ", ".join(notc[:12]) + (f" (+{len(notc) - 12} more)" if len(notc) > 12 else ""), (sm.note if sm else ""), hashes.get(rs.file, "")[:12]))
    df = pd.DataFrame(rows, columns=["Source file", "Sheet", "Header row (Excel)", "Rows read", "Rows kept", "Rows excluded", "Used as", "Mapping confidence",
                                     "Columns not carried (incl. free text)", "Note", "Source SHA-256 (first 12)"])
    df["Rows kept"] = np.where(df["Used as"] == "(not used)", 0, df["Rows read"] - df["Rows excluded"])
    extra = [(f, s, None, None, 0, 0, "(documentation sheet skipped)", None, "", "README / dictionary-type sheet not read", hashes.get(f, "")[:12]) for f, s in skipped]
    extra += [(f, "", None, None, 0, 0, "(file could not be read)", None, "", m, hashes.get(f, "")[:12]) for f, m in read_errors]
    if collapsed:
        extra.append(("(all files)", "", None, None, None, 0, "(identical dimension rows collapsed)", None, "", "; ".join(f"{k}: {v}" for k, v in collapsed.items()), ""))
    extra.append(("(all files)", "", None, None, None, 0, "(free text)", None, "", "Free-text columns (laundry note, material note, assumption note, dashboard emphasis) and any unmapped source column are not carried; no named people.", ""))
    df = pd.concat([df, pd.DataFrame(extra, columns=df.columns)], ignore_index=True)
    return df


def open_questions(T, meta, report):
    q = [("What is the revenue, price per garment or contract value?", "No commercial data in the source files.", "Price / contract data (CRM or contract export)."),
         ("Which contractual KPIs apply (e.g. on-time >= 95 %)?", "Contract KPIs are not in the files; they vary by customer.", "Contract KPI list per customer (KAM can add)."),
         ("Do repairs extend garment lifespan?", "Not analysed by Lindström; repairs are shown as a cost and circularity signal only.", "Garment-level life data."),
         ("Which individual wearers or people are involved?", "Data is aggregated at site level on purpose (no named people).", "Not provided by design."),
         ("What do customers say in meetings?", "Meeting notes are not part of this file.", "KAM-reported notes (app).")]
    if meta["months"] < 24:
        q.append(("How does this compare with last year?", f"The file covers {meta['months']} month(s) ({meta['period']}); year-on-year needs 24 months.", "A further 12 months earlier than the first month."))
    if "service_cycles" not in T or T["service_cycles"].empty:
        q.append(("What is the on-time %, turnaround or cycle time?", "No service-cycle (RFID) data was provided.", "End-to-end delivery / RFID cycle sheet."))
    if "waste" not in T or T["waste"].empty:
        q.append(("How much textile is recycled?", "No textile-waste data was provided.", "Textile waste kg report."))
    if "resources" not in T or T["resources"].empty:
        q.append(("What are the water, energy and CO2e figures?", "No laundry resource data was provided.", "Laundry resource report."))
    if "baselines" not in T or T["baselines"].empty:
        q.append(("What are the savings versus a local laundry?", "No comparison baseline was provided.", "Comparison baseline table."))
    if T.get("repairs") is None or T["repairs"].empty:
        q.append(("How many repairs and what purchases were avoided?", "No repair data was provided.", "Repairs table."))
    return pd.DataFrame(q, columns=["Question the data cannot answer", "Why not", "What is missing"])


def dictionary(sheets, spec_doc):
    rows = list(spec_doc)
    have = {(s, n) for s, n, *_ in rows}
    ex = lambda sh, c: next((str(v) for v in sheets[sh][c].dropna().head(1)), "") if sh in sheets and c in sheets[sh].columns else ""
    for name in ms.MEASURE_ORDER:
        unit, status, d = ms.MEASURES[name]
        for sh in ("Analysis", "Site_Summary", "Customer_Summary"):
            if sh in sheets and name in sheets[sh].columns and (sh, name) not in have:
                rows.append((sh, name, d, unit, status, "measure"))
    extra = {
        "Analysis": {"Month": ("Calendar month, YYYY-MM", "", "SOURCE"), "Customer ID": ("Customer key", "", "SOURCE"), "Customer": ("Customer name", "", "SOURCE"), "Industry": ("Industry segment", "", "SOURCE"),
                     "Site ID": ("Site key", "", "SOURCE"), "Site": ("Site name", "", "SOURCE"), "Country": ("Site country", "", "SOURCE"), "Site type": ("Kind of site", "", "SOURCE"),
                     "Utilisation band low %": ("Lower end of the utilisation band for this customer", "%", "TEAM_ASSUMPTION"), "Utilisation band high %": ("Upper end of the band", "%", "TEAM_ASSUMPTION"),
                     "Utilisation vs band": ("below band / within band / above band", "", "CALCULATED"), "Baseline": ("Comparison baseline named for all savings", "", "SOURCE"),
                     "Status note": ("Which numbers are calculated, allocated or estimated", "", "")},
        "Measures": {"Level": ("Grain of the row", "", ""), "Customer ID": ("Customer key", "", ""), "Customer": ("Customer name", "", ""), "Site ID": ("Site key (blank for customer rows)", "", ""),
                     "Site": ("Site name", "", ""), "Period": ("Month YYYY-MM, or the whole period", "", ""), "Measure": ("Measure name (see Analysis dictionary entries)", "", ""),
                     "Value": ("The number", "see Unit", ""), "Unit": ("Unit of Value", "", ""), "Status": ("How the number was produced", "", ""), "Basis": ("Baseline or factor used, where relevant", "", "")},
        "Customer_Summary": {"Customer ID": ("Customer key", "", ""), "Customer": ("Customer name", "", ""), "Industry": ("Industry", "", ""), "Period": ("First to last month in the file", "", ""),
                             "Sites": ("Number of sites with activity", "sites", "CALCULATED"), "Garments allocated (latest month)": ("Garments allocated in the latest month", "garments", "CALCULATED"),
                             "Utilisation % (latest month)": ("Utilisation in the latest month", "%", "CALCULATED"),
                             "Utilisation band low %": ("Lower end of the band for this customer", "%", "TEAM_ASSUMPTION"), "Utilisation band high %": ("Upper end of the band", "%", "TEAM_ASSUMPTION"),
                             "Utilisation band source": ("General default, industry default or KAM override", "", "TEAM_ASSUMPTION"),
                             "Sites outside the band": ("Sites whose latest utilisation is below or above the band", "sites", "CALCULATED"), "Notable sites": ("Sites with a notable 'Why notable'", "sites", "CALCULATED"),
                             "Washed kg vs last year %": ("Latest 12 months vs the 12 before; blank when 24 months do not exist", "%", "CALCULATED")},
        "Site_Summary": {"Customer ID": ("Customer key", "", ""), "Customer": ("Customer name", "", ""), "Site ID": ("Site key", "", ""), "Site": ("Site name", "", ""), "Country": ("Site country", "", ""),
                         "Site type": ("Kind of site", "", ""), "Period": ("First to last month in the file", "", ""), "Garments allocated (latest month)": ("Allocated in the latest month", "garments", "CALCULATED"),
                         "Utilisation % (latest month)": ("Utilisation in the latest month", "%", "CALCULATED"),
                         "Allocated garments with no scan activity (latest month)": ("Allocated minus with scan activity, latest month; an investigation signal", "garments", "CALCULATED"),
                         "Utilisation band low %": ("Lower end of the band", "%", "TEAM_ASSUMPTION"), "Utilisation band high %": ("Upper end of the band", "%", "TEAM_ASSUMPTION"),
                         "Utilisation vs band": ("below band / within band / above band", "", "CALCULATED"),
                         "Washed kg vs last year %": ("Latest 12 months vs the 12 before; blank when 24 months do not exist", "%", "CALCULATED"),
                         "Why notable": ("Plain-language reasons the site stands out, most informative first", "", "CALCULATED"),
                         "Notable level": ("notable / minor / none", "", "CALCULATED")},
        "Integrity_Check": {c: (d, "", "") for c, d in {"Check": "What was verified", "Scope": "Sheet, column or customer verified", "Expected": "Value from the independent path", "Found": "Value in the pack", "Difference": "Found minus expected", "Result": "PASS, FAIL or WARNING", "Note": "Context"}.items()},
        "Validation_Exceptions": {c: (c, "", "") for c in ["Severity", "Check", "Table", "Source file", "Sheet", "Excel rows", "Rows affected", "Explanation", "Suggested fix", "Decision", "Scope"]},
        "Excluded_Rows": {c: (c, "", "") for c in ["Source file", "Sheet", "Excel row", "Table", "Reason"]},
    }
    for sh, d in extra.items():
        if sh not in sheets:
            continue
        for c, (de, un, stt) in d.items():
            if c in sheets[sh].columns and (sh, c) not in {(r[0], r[1]) for r in rows}:
                rows.append((sh, c, de, un, stt, "derived"))
    rows = [(s, n, d, u, st, src, ex(s, n)) for s, n, d, u, st, src in rows]
    df = pd.DataFrame(rows, columns=["Sheet", "Column", "Definition", "Unit", "Status", "Source", "Example"])
    order = {k: i for i, k in enumerate(sheets)}
    df["_o"] = df.Sheet.map(order)
    return df.sort_values(["_o"], kind="stable").drop(columns="_o").reset_index(drop=True)


# ------------------------------------------------------------------------------------------------ writing
def _write_xlsx(path, sheets: dict[str, pd.DataFrame]):
    """Values only, one header row. openpyxl write-only mode: fast and memory-light for big fact sheets."""
    from openpyxl import Workbook
    from openpyxl.cell import WriteOnlyCell
    from openpyxl.styles import Font, Alignment
    wb = Workbook(write_only=True)
    bold = Font(bold=True)
    for name, df in sheets.items():
        ws = wb.create_sheet(name[:31])
        ws.freeze_panes = "A2"
        wrap = name in ("README", "START_HERE", "Prompt_Card", "Assumptions", "Open_Questions", "Validation_Exceptions", "Data_Dictionary")
        for i, col in enumerate(df.columns, 1):
            width = min(max(len(str(col)) + 2, 10), 60)
            if wrap or df[col].dtype == object:
                try:
                    width = min(max(width, int(df[col].astype(str).str.len().head(2000).quantile(0.9)) + 2 if len(df) else width), 70)
                except Exception:
                    pass
            ws.column_dimensions[ws.cell(row=1, column=i).column_letter if False else __import__("openpyxl").utils.get_column_letter(i)].width = width
        hdr = []
        for c in df.columns:
            cell = WriteOnlyCell(ws, value=str(c)); cell.font = bold; hdr.append(cell)
        ws.append(hdr)
        al = Alignment(wrap_text=True, vertical="top") if wrap else None
        for row in df.itertuples(index=False, name=None):
            vals = []
            for v in row:
                if v is None or (isinstance(v, float) and v != v) or v is pd.NA or v is pd.NaT:
                    v = None
                elif isinstance(v, (np.integer,)):
                    v = int(v)
                elif isinstance(v, (np.floating,)):
                    v = float(v)
                elif isinstance(v, (np.bool_,)):
                    v = bool(v)
                if al is not None and v is not None:
                    c = WriteOnlyCell(ws, value=v); c.alignment = al; v = c
                vals.append(v)
            ws.append(vals)
    wb.save(path)


def split_if_big(name, df):
    """Excel holds ~1,048,576 rows. Split a fact sheet by year (Month column) when it would not fit."""
    if len(df) <= MAX_ROWS:
        return {name: df}
    col = "Month" if "Month" in df.columns else ("Pickup time" if "Pickup time" in df.columns else None)
    if col is None:
        raise ValueError(f"{name} has {len(df)} rows and cannot be split")
    out = {}
    for y, g in df.groupby(df[col].astype(str).str[:4]):
        out[f"{name}_{y}"[:31]] = g
    return out


def build(inputs, out_path, customer="all", decisions_path=None, decisions: Decisions | None = None, progress=None, csv=False,
          input_root=None, sources=None, split_above=SPLIT_DETAIL_ABOVE, cache_ok=True, sqlite=False, keep_working=False):
    """Build the master pack. -> report dict (always; check report['ok']). Never raises for data problems."""
    t0 = time.time()
    decisions = decisions or Decisions.load(decisions_path)
    report = dict(ok=False, built_on=dt.date.today().isoformat(), inputs=[], errors=[], warnings=[], outputs=[], source_unchanged=None)
    if sources is None:
        paths = discover(inputs)
        if not paths:
            report["errors"].append("No .xlsx, .xlsm or .csv files were found in the input.")
            return report
        root = input_root or (inputs[0] if len(inputs) == 1 and os.path.isdir(inputs[0]) else None)
        sources = [(label(p, root), p) for p in paths]
    hashes_before = {n: sha256(s) for n, s in sources}
    report["inputs"] = [dict(file=n, sha256=h) for n, h in hashes_before.items()]
    try:
        L = load_tables(sources, decisions, progress)
        raw, mapping = L["raw"], L["mapping"]
        if not raw:
            report["errors"].append("None of the files could be read as a workbook with data."); report["read_errors"] = L["read_errors"]
            return report
        V = validate_and_clean(raw, mapping, decisions)
        issues, log, T = V["issues"], V["log"], V["T_clean"]
        if progress:
            progress(0.7, "Checked the data")
        if T.get("sites") is None or T["sites"].empty or T.get("service_activity") is None or T["service_activity"].empty:
            report["errors"].append("Could not find usable Sites and Service activity data. Open Advanced mode to check how the sheets were understood.")
            report["unmapped"] = {k: (sm.table, round(sm.score, 2)) for k, sm in mapping.items()}
            return report
        if keep_working:
            report["_working"] = dict(T=T, issues=issues, log=log)
        T, cid = filter_customer(T, customer)
        sheets, spec_doc, meta = build_sheets(T, issues, log, decisions, report)
        if progress:
            progress(0.85, "Calculated the measures")
        ev, ex = exception_rows(issues, log, decisions, V["actions"])
        n_err = int((issues.severity == "ERROR").sum()); n_warn = int((issues.severity == "WARNING").sum())
        synth = any("SYNTHETIC" in str(v).upper() for k in ("service_activity",) for v in T[k].get("data_status", pd.Series(dtype=object)).dropna().unique()[:5])
        report.update(n_errors=n_err, n_warnings=n_warn, n_info=int((issues.severity == "INFO").sum()), rows_excluded=len(log), synthetic=synth,
                      files=len({r.file for r in raw.values()}), sheets_used=sum(1 for sm in mapping.values() if sm.include and sm.table),
                      sheets_ignored=[(raw[k].file, raw[k].sheet) for k, sm in mapping.items() if not (sm.include and sm.table)],
                      customers=list(meta["customers"].values()), period=meta["period"], n_sites=meta["n_sites"],
                      read_errors=L["read_errors"], skipped_docs=L["skipped"], rows_service_activity=len(T["service_activity"]))
        facts = {k: sheets.pop(k) for k in list(sheets) if k.startswith("Fact_")}
        total_fact_rows = sum(len(v) for v in facts.values())
        split = total_fact_rows > split_above
        core = {}
        core["README"] = readme_rows(report, meta, report["files"], split)
        core["START_HERE"] = start_here_rows(T, decisions)
        core["Prompt_Card"] = pd.DataFrame({"Paste this as the first message in Copilot chat": [l for l in PROMPT.split("\n") if l.strip()]})
        core.update({k: sheets[k] for k in ("Analysis", "Measures", "Customer_Summary", "Site_Summary") if k in sheets})
        for k in ("Customers", "Sites", "Products", "Laundries"):
            if k in sheets and len(sheets[k]):
                core[k] = sheets[k]
        core["Assumptions"] = assumptions_rows(T, meta, decisions, report)
        core["Validation_Exceptions"] = ev
        core["Excluded_Rows"] = ex
        core["Open_Questions"] = open_questions(T, meta, report)
        all_for_doc = dict(core); all_for_doc.update(facts)
        core["Lineage"] = lineage_rows(raw, mapping, log, L["skipped"], L["read_errors"], {n: h for n, h in hashes_before.items()}, V["collapsed"])
        allsheets = finalise_formats({**core, **facts})
        sqlite_path = None
        if sqlite:
            sqlite_path = os.path.splitext(out_path)[0] + "_working.sqlite"
            os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
            ig.write_sqlite(sqlite_path, allsheets)
            report["outputs"].append(sqlite_path)
        hashes_mid = {n: sha256(s) for n, s in sources}
        integ = ig.check_pack(raw, mapping, V, T, log, allsheets, hashes_before, hashes_mid, sqlite_path, customer_filtered=cid is not None)
        report["integrity"] = ig.summary(integ)
        if report["integrity"]["failed"]:
            report["warnings"].append(f"Integrity agent: {report['integrity']['failed']} check(s) FAILED. See sheet Integrity_Check before quoting numbers.")
        core["Integrity_Check"] = integ
        allsheets["Integrity_Check"] = integ
        all_for_doc = {k: allsheets[k] for k in list(core) + list(facts) if k in allsheets}
        core_final = {k: allsheets[k] for k in core}
        core_final["Data_Dictionary"] = dictionary(all_for_doc, spec_doc)
        order = ["START_HERE", "README", "Prompt_Card", "Data_Dictionary", "Lineage", "Validation_Exceptions", "Excluded_Rows", "Integrity_Check", "Assumptions", "Customers", "Sites", "Products", "Laundries",
                 "Analysis", "Measures", "Customer_Summary", "Site_Summary", "Open_Questions"]
        core_final = {k: core_final[k] for k in order if k in core_final}
        facts_final = {}
        for k, df in facts.items():
            facts_final.update(split_if_big(k, allsheets[k]))
        os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
        base = os.path.splitext(out_path)[0]
        if split:
            core_path, detail_path = out_path, f"{base}_Detail.xlsx"
            _write_xlsx(core_path, core_final)
            _write_xlsx(detail_path, facts_final)
            report["outputs"] += [core_path, detail_path]
            report["warnings"].append(f"{total_fact_rows:,} fact rows: written as a Core file and a separate Detail file. Attach the Core file to Copilot first.")
        else:
            _write_xlsx(out_path, {**core_final, **facts_final})
            report["outputs"].append(out_path)
        slim_path = f"{base}_for_Copilot.xlsx"
        slim = {k: core_final[k] for k in SLIM_SHEETS if k in core_final}
        _write_xlsx(slim_path, slim)
        report["outputs"].append(slim_path); report["slim"] = slim_path
        prompt_path = os.path.join(os.path.dirname(os.path.abspath(out_path)), "Copilot_Prompt.md")
        with open(prompt_path, "w", encoding="utf-8") as f:
            f.write(HOW_TO.format(xlsx=os.path.basename(slim_path)) + PROMPT + "\n")
        report["outputs"].append(prompt_path)
        if csv:
            cdir = base + "_csv"
            os.makedirs(cdir, exist_ok=True)
            for k, df in {**core_final, **facts_final}.items():
                df.to_csv(os.path.join(cdir, f"{k}.csv"), index=False, encoding="utf-8")
            report["outputs"].append(cdir)
        report["sheets"] = {k: [len(v), len(v.columns)] for k, v in {**core_final, **facts_final}.items()}
        report["ok"] = True
        if n_err:
            report["warnings"].append(f"{n_err} data error(s) found; the pack was still built. See Validation_Exceptions.")
        if L["read_errors"]:
            report["warnings"].append(f"{len(L['read_errors'])} file(s) could not be read and were skipped.")
        report["meta"] = dict(latest_month=meta["latest"], period=meta["period"], baseline=meta["baseline"])
    except Exception as e:                                     # never a traceback to the user; the report keeps it
        report["errors"].append(f"{type(e).__name__}: {e}")
        report["traceback"] = traceback.format_exc()
    # source immutability: hash again
    after = {n: sha256(s) for n, s in sources}
    report["source_unchanged"] = after == hashes_before
    if not report["source_unchanged"]:
        report["errors"].append("A source file changed while the pack was built. This should never happen.")
        report["ok"] = False
    report["seconds"] = round(time.time() - t0, 1)
    try:
        with open(os.path.splitext(out_path)[0] + "_build_report.json", "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str, ensure_ascii=False)
    except Exception:
        pass
    if progress:
        progress(1.0, "Done")
    return report


def default_name(customer, folder=".") :
    return os.path.join(folder, f"Lindstrom_Master_{str(customer).replace(' ', '_') if customer else 'all'}_{dt.date.today():%Y%m%d}.xlsx")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build one Copilot-ready master workbook from many Excel/CSV files.")
    ap.add_argument("--input", nargs="+", required=True, help="files and/or folders (recursive)")
    ap.add_argument("--out", help="output .xlsx (default Lindstrom_Master_<customer>_<date>.xlsx)")
    ap.add_argument("--customer", default="all", help="all | customer id | customer name")
    ap.add_argument("--decisions", help="sidecar JSON with mapping fixes, row exclusions and utilisation bands")
    ap.add_argument("--csv", action="store_true", help="also write every sheet as CSV")
    ap.add_argument("--sqlite", action="store_true", help="also write a read-only-by-convention SQLite working container derived from the pack")
    a = ap.parse_args(argv)
    out = a.out or default_name(a.customer)
    last = [0]

    def prog(p, msg):
        if int(p * 10) != last[0]:
            last[0] = int(p * 10)
            print(f"[{int(p * 100):3d}%] {msg}", flush=True)
    rep = build(a.input, out, a.customer, a.decisions, progress=prog, csv=a.csv, sqlite=a.sqlite)
    if rep["ok"]:
        print(f"\nBuilt {next(o for o in rep['outputs'] if o.endswith('.xlsx'))}\n  files {rep['files']}, sheets used {rep['sheets_used']}, customers {len(rep['customers'])}, period {rep['period']}, "
              f"exceptions: {rep['n_errors']} error(s), {rep['n_warnings']} warning(s), {rep['rows_excluded']} row(s) excluded; integrity {rep['integrity']['passed']}/{rep['integrity']['checks']} checks pass; {rep['seconds']} s")
        for w in rep["warnings"]:
            print("  note:", w)
        print("  Next: attach the workbook in Copilot chat and paste Copilot_Prompt.md (below the line) as your first message.")
        return 0
    print("Could not build a pack:", *rep["errors"], sep="\n  ", file=sys.stderr)
    print("  Build report:", os.path.splitext(out)[0] + "_build_report.json", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
