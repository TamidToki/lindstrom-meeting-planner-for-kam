"""The Analyst: a conversational analyst for the KAM that never invents a number.

How it stays honest
-------------------
* Every figure comes from a deterministic tool in this file (exact pandas arithmetic on the validated tables,
  re-using metrics.py / portfolio.py). The language model only chooses tools, reads their results and words the answer.
* The model answers through a structured `respond` tool: a short read, key numbers, charts, hypotheses, follow-ups.
  - key numbers must be found in a tool result; their status badge (Calculated / Estimate / What-if) is looked up
    in that result by code, never taken from the model;
  - charts are drawn by code from a tool result's rows, so a chart cannot contain an invented value;
  - hypotheses are labelled as such and may only cite numbers that a tool returned;
  - any number in the text that no tool returned (and that is not in the question) makes the answer fail the
    check: the model gets one chance to fix it, then the deterministic rule-based answer is shown instead.
* Arithmetic the model wants (a difference, a share) goes through the `calc` tool, which only accepts operands
  that already appear in a tool result, so derived numbers are exact and auditable too.
* Without an API key the same tools are driven by a rule-based router with conversation memory.
"""
from __future__ import annotations
import ast
import json
import operator
import os
import re
import unicodedata
import numpy as np
import pandas as pd
import metrics as mt
import portfolio as pf
from assumptions import Uncertainty

import providers
MODEL = os.getenv("ANALYST_MODEL", providers.DEFAULT_ANTHROPIC_MODEL)      # kept for compatibility; the model in force is providers.model_name()

STATUS_LABEL = {"CALCULATED": "Calculated", "ALLOCATED": "Estimate · allocated", "ESTIMATED": "Estimate · assumption",
                "SCENARIO": "What-if", "HYPOTHESIS": "Hypothesis"}


# ============================================================================================ helpers
def _plain(s) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", s).strip()


def _r(v, d=1):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return v
    if np.isnan(f) or np.isinf(f):
        return None
    return round(f, d) if d else int(round(f))


def nf(v, d=0) -> str:
    """Display number with space thousands separator (parsable by the verifier)."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "n/a"
    return f"{v:,.{d}f}".replace(",", " ")


def big(v, unit="") -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "n/a"
    a = abs(v)
    s = f"{v/1e6:.2f} M" if a >= 1e6 else f"{v/1e3:.1f} k" if a >= 1e4 else nf(v, 0) if a >= 100 else f"{v:.1f}"
    return f"{s} {unit}".strip()


# ============================================================================================ catalogue
DIMS = {"customer": "customer", "country": "country", "city": "city", "site": "site", "site_type": "site_type",
        "product": "product", "product_group": "product_group", "month": "month", "quarter": "quarter",
        "laundry": "laundry", "repair_type": "repair_type"}

# name: (family, kind, unit, status, definition)
MEASURES = {
    "washed_kg": ("A", "sum", "kg", "CALCULATED", "sum of customer_washed_kg"),
    "service_requests": ("A", "sum", "requests", "CALCULATED", "sum of service_requests"),
    "garments_allocated": ("A", "stock", "garments", "CALCULATED", "allocated_pieces in the last month of the period (or per month when grouped by month)"),
    "garments_scanned": ("A", "stock", "garments", "CALCULATED", "active_assets_scanned in the last month of the period (or per month)"),
    "garments_not_scanned": ("A", "stock", "garments", "CALCULATED", "allocated − scanned in the last month of the period (or per month)"),
    "active_wearers": ("A", "stock", "wearers", "CALCULATED", "active_wearers summed over product rows, last month (a person with two products counts twice)"),
    "utilisation_pct": ("A", "ratio", "%", "CALCULATED", "scanned ÷ allocated garments, last month of the period (or per month)"),
    "requests_per_1000_garments": ("A", "ratio", "per 1000", "CALCULATED", "1000 × service requests in the period ÷ garments allocated (last month, or per month)"),
    "water_saving_l": ("A", "sum", "L", "ALLOCATED", "Σ matched kg × baseline L/kg − Σ kg × laundry L/kg (laundry water allocated by washed kg)"),
    "energy_saving_kwh": ("A", "sum", "kWh", "ALLOCATED", "Σ matched kg × baseline kWh/kg − Σ kg × laundry kWh/kg"),
    "co2_saving_kg": ("A", "sum", "kgCO2e", "ALLOCATED", "Σ matched kg × baseline (process+delivery) kgCO2e/kg − allocated laundry emissions"),
    "water_l_per_kg": ("A", "ratio", "L/kg", "ALLOCATED", "allocated laundry water ÷ matched washed kg"),
    "energy_kwh_per_kg": ("A", "ratio", "kWh/kg", "ALLOCATED", "allocated laundry energy ÷ matched washed kg"),
    "repairs": ("R", "sum", "repairs", "CALCULATED", "sum of repair_count"),
    "repairs_per_100_garments": ("R", "ratio", "per 100", "CALCULATED", "100 × repairs in the period ÷ garments allocated (last month, or per month)"),
    "replacements_postponed": ("R", "sum", "garments", "ESTIMATED", "repairs × repair factor (Base 1.0 = pack assumption A002, an upper bound)"),
    "purchases_avoided_eur": ("R", "sum", "EUR", "ESTIMATED", "Σ repairs × product purchase cost × repair factor (upper bound, direct purchase only)"),
    "service_cycles": ("C", "sum", "cycles", "CALCULATED", "count of RFID service cycles (by pickup month)"),
    "late_cycles": ("C", "sum", "cycles", "CALCULATED", "cycles with performance_flag ≠ ON_TIME"),
    "ontime_pct": ("C", "ratio", "%", "CALCULATED", "share of service cycles flagged ON_TIME"),
    "avg_cycle_hours": ("C", "ratio", "h", "CALCULATED", "mean pickup→delivery hours"),
}
ALIASES = {"utilisation": "utilisation_pct", "utilization": "utilisation_pct", "on-time": "ontime_pct", "ontime": "ontime_pct",
           "on_time": "ontime_pct", "requests": "service_requests", "request_rate": "requests_per_1000_garments", "kg": "washed_kg",
           "water": "water_saving_l", "energy": "energy_saving_kwh", "co2": "co2_saving_kg", "emissions": "co2_saving_kg",
           "repair_rate": "repairs_per_100_garments", "garments": "garments_allocated", "idle": "garments_not_scanned",
           "wearers": "active_wearers", "cycle_hours": "avg_cycle_hours", "late": "late_cycles", "cost": "purchases_avoided_eur"}
DEC = {"%": 1, "per 1000": 1, "per 100": 1, "L/kg": 2, "kWh/kg": 3, "h": 1}


def _measure(name):
    n = str(name).strip().lower().replace(" ", "_").replace("-", "_")
    if n in MEASURES:
        return n
    return ALIASES.get(n) or ALIASES.get(n.replace("_", "-")) or next((m for m in MEASURES if n in m), None)


# ============================================================================================ context
class Ctx:
    """Everything the tools need, built once per (data version, baseline, assumptions). Holds the result store."""

    def __init__(self, T, issues, baseline=None, unc=None, P=None, S=None):
        self.T, self.issues = T, issues
        self.unc = unc or Uncertainty()
        self.baseline = baseline or mt.default_baseline(T)
        if P is None or S is None:
            P, S = pf.portfolio(T, self.baseline, "Base", self.unc)
        self.P, self.S = P, S
        self.RI = pf.repair_intensity(T)
        self.CU = pf.customers(T)
        self.names = self.CU.set_index("customer_id").customer.to_dict()
        self._M = {}
        self.store, self.n = {}, 0
        self.state = {}          # rule-based conversation memory: customer, site, measure, group_by
        self._facts()

    # ---------------------------------------------------------------- facts (long tables with dimension labels)
    def _facts(self):
        T, u = self.T, self.unc
        S = T["sites"].drop_duplicates("site_id").set_index("site_id")
        P = T.get("products")
        L = T.get("laundries")
        pn = P.set_index("product_id").product_name if P is not None and not P.empty else pd.Series(dtype=str)
        pg = P.set_index("product_id").product_group if P is not None and not P.empty else pd.Series(dtype=str)
        ln = L.set_index("laundry_id").laundry_name if L is not None and not L.empty and "laundry_name" in L else pd.Series(dtype=str)

        def dims(d):
            d = d.copy()
            d["customer"] = d.customer_id.map(self.names).fillna(d.customer_id)
            d["site"] = d.site_id.map(S.site_name).fillna(d.site_id)
            d["country"] = d.site_id.map(S.country).fillna("n/a")
            d["city"] = d.site_id.map(S.city).fillna("n/a") if "city" in S else "n/a"
            d["site_type"] = d.site_id.map(S.site_type).fillna("n/a") if "site_type" in S else "n/a"
            if "product_id" in d:
                d["product"] = d.product_id.map(pn).fillna(d.product_id)
                d["product_group"] = d.product_id.map(pg).fillna("n/a")
            if "laundry_id" in d:
                d["laundry"] = d.laundry_id.map(ln).fillna(d.laundry_id)
            if "month" in d:
                mo = pd.to_datetime(d.month, errors="coerce")
                d["quarter"] = mo.dt.year.astype("Int64").astype(str) + "-Q" + mo.dt.quarter.astype("Int64").astype(str)
            return d

        A = dims(T["service_activity"])
        RI = mt._intensities(T)
        B = T.get("baselines")
        bl = None
        if B is not None and not B.empty:
            b = B[B.baseline_id == self.baseline]
            bl = b.iloc[0] if len(b) else None
        self.bl = bl
        kg = A.customer_washed_kg
        bp, ap = u.baseline_pct, u.allocation_pct
        if RI is not None:
            A = A.merge(RI[["month", "laundry_id", "water", "energy", "co2"]], on=["month", "laundry_id"], how="left")
            kg = A.customer_washed_kg
            for k, bcol, out in (("water", "water_l_per_kg", "water_saving_l"), ("energy", "energy_kwh_per_kg", "energy_saving_kwh"), ("co2", None, "co2_saving_kg")):
                used = kg * A[k]
                A[f"{k}_used"] = used
                A[f"{k}_kg"] = kg.where(A[k].notna())
                if bl is None:
                    continue
                if k == "co2":
                    bi = float(bl.process_kgco2e_per_kg) + (0 if pd.isna(bl.delivery_kgco2e_per_kg) else float(bl.delivery_kgco2e_per_kg))
                else:
                    if pd.isna(bl.get(bcol)):
                        continue
                    bi = float(bl[bcol])
                base = A[f"{k}_kg"] * bi
                A[out] = base - used
                A[out + "__low"] = base * (1 - bp) - used * (1 + ap)
                A[out + "__high"] = base * (1 + bp) - used * (1 - ap)
        self.A = A
        R = T.get("repairs")
        if R is not None and not R.empty:
            R = dims(R)
            cost = R.product_id.map(P.set_index("product_id").purchase_cost_eur) if P is not None and "purchase_cost_eur" in P else np.nan
            R["eur_gross"] = R.repair_count * cost
        self.R = R
        C = T.get("service_cycles")
        if C is not None and not C.empty:
            C = C.copy()
            C["month"] = C.pickup_timestamp.dt.strftime("%Y-%m")
            C = dims(C)
            C["late"] = (C.performance_flag.astype(str).str.upper().str.replace(" ", "_") != "ON_TIME") & C.performance_flag.notna()
            C["hours"] = C.cycle_hours.where(C.cycle_hours.notna(), (C.delivered_timestamp - C.pickup_timestamp).dt.total_seconds() / 3600)
        self.C = C
        self.months = sorted(A.month.dropna().unique())

    # ---------------------------------------------------------------- resolution
    def resolve(self, text):
        """Customer id named in free text (name word, id) or None."""
        t = _plain(text)
        for r in self.CU.itertuples():
            toks = [_plain(r.customer_id), _plain(r.customer)] + [w for w in _plain(r.customer).split() if len(w) > 3 and w not in ("group", "network", "systems", "industrial", "foods", "health")]
            if any(re.search(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])", t) for k in toks):
                return r.customer_id
        return None

    def name(self, cid):
        return self.names.get(cid, cid)

    def sites_in(self, text, cid=None):
        """Site rows (from the site table) whose name/city/id is named in the text."""
        t = _plain(text)
        S = self.S if cid is None else self.S[self.S.customer_id == cid]
        hits = []
        for r in S.itertuples():
            nm = _plain(r.site)
            words = [w for w in nm.split() if len(w) > 3 and _plain(self.name(r.customer_id)).find(w) < 0]
            if _plain(r.site_id) in t.split() or nm in t or any(re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", t) for w in words):
                hits.append(r.site_id)
        return hits

    def metrics(self, cid, baseline=None, sites=None, unc=None, T=None):
        key = (cid, baseline or self.baseline, tuple(sites) if sites else None, unc or self.unc, id(T) if T is not None else None)
        if key not in self._M:
            self._M[key] = mt.metrics(T if T is not None else self.T, cid, baseline or self.baseline, "Base", unc or self.unc, sites=sites)
        return self._M[key]

    def put(self, tool, args, res):
        self.n += 1
        rid = f"R{self.n}"
        res = dict(res)
        res["result_id"] = rid
        self.store[rid] = dict(tool=tool, args=args, result=res)
        return rid, res


# ============================================================================================ query engine
def _match(series: pd.Series, wanted) -> pd.Series:
    vals = wanted if isinstance(wanted, (list, tuple)) else [wanted]
    vals = [_plain(v) for v in vals if str(v).strip()]
    s = series.astype(str).map(_plain)
    m = pd.Series(False, index=series.index)
    for v in vals:
        m |= (s == v) | s.str.contains(re.escape(v), regex=True)
    return m


def _apply_filters(ctx, d, filters, errors):
    if d is None:
        return None
    for k, v in (filters or {}).items():
        if v in (None, "", []):
            continue
        k = str(k).lower()
        if k in ("month_from", "from"):
            d = d[d.month >= str(v)[:7]]
            continue
        if k in ("month_to", "to"):
            d = d[d.month <= str(v)[:7]]
            continue
        if k == "customer":
            ids = [ctx.resolve(x) or x for x in (v if isinstance(v, list) else [v])]
            d = d[d.customer_id.isin(ids) | _match(d.customer, v)]
            continue
        col = DIMS.get(k)
        if col is None:
            errors.append(f"unknown filter '{k}'")
            continue
        if col not in d:
            continue
        m = _match(d[col], v)
        if col == "site" and "site_id" in d:
            m |= _match(d.site_id, v)
        if not m.any():
            errors.append(f"no {k} matches {v!r}; known: {', '.join(map(str, sorted(d[col].dropna().unique())[:30]))}")
        d = d[m]
    return d


def query(ctx, measures, group_by=None, filters=None, sort_by=None, ascending=False, top_n=25):
    """Exact aggregation of any catalogue measure by any dimensions, with filters. Returns rows + per-measure status."""
    ms, unknown = [], []
    for m in (measures if isinstance(measures, list) else [measures]):
        k = _measure(m)
        (ms if k else unknown).append(k or m)
    ms = list(dict.fromkeys(ms))
    gb = [g for g in (group_by if isinstance(group_by, list) else ([group_by] if group_by else [])) if g]
    bad_g = [g for g in gb if g not in DIMS]
    gb = [g for g in gb if g in DIMS]
    errors = [f"unknown measure '{u}'" for u in unknown] + [f"unknown dimension '{g}'" for g in bad_g]
    if not ms:
        return {"error": "no valid measure", "errors": errors, "measures": list(MEASURES), "dimensions": list(DIMS)}
    if "repair_type" in gb and any(MEASURES[m][0] != "R" for m in ms):
        errors.append("repair_type applies to repair measures only; other measures dropped")
        ms = [m for m in ms if MEASURES[m][0] == "R"] or ["repairs"]
    keys = [DIMS[g] for g in gb] or ["_all"]
    fA = _apply_filters(ctx, ctx.A, filters, errors)
    fR = _apply_filters(ctx, ctx.R, filters, []) if ctx.R is not None else None
    fC = _apply_filters(ctx, ctx.C, filters, []) if ctx.C is not None else None
    fams = {MEASURES[m][0] for m in ms}
    if fA is None or fA.empty:
        return {"error": "no rows match the filters", "errors": errors}
    last = fA.month.max()
    by_month = "month" in gb or "quarter" in gb

    def g(d):
        d = d.assign(_all="all")
        return d

    parts = []
    # ---- activity (needed for activity measures and for per-garment repair rates)
    need_A = ("A" in fams or "repairs_per_100_garments" in ms) and "repair_type" not in gb
    need_stock = need_A and (any(MEASURES[m][1] in ("stock", "ratio") for m in ms if MEASURES[m][0] == "A") or "repairs_per_100_garments" in ms)
    a = g(fA)
    sums = {c: "sum" for c in ("customer_washed_kg", "service_requests", "water_saving_l", "water_saving_l__low", "water_saving_l__high",
                               "energy_saving_kwh", "energy_saving_kwh__low", "energy_saving_kwh__high", "co2_saving_kg", "co2_saving_kg__low",
                               "co2_saving_kg__high", "water_used", "water_kg", "energy_used", "energy_kg") if c in a}
    if need_A:
        parts.append(a.groupby(keys, dropna=False).agg(sums))
    if need_stock:
        if "month" in gb:
            st = a
        elif "quarter" in gb:      # stock = last month of each quarter
            lm = a.groupby("quarter").month.transform("max")
            st = a[a.month == lm]
        else:
            st = a[a.month == last]
        parts.append(st.groupby(keys, dropna=False)[["allocated_pieces", "active_assets_scanned", "active_wearers"]].sum(min_count=1))
    if "R" in fams and fR is not None and len(fR):
        parts.append(g(fR).groupby(keys, dropna=False).agg(repair_count=("repair_count", "sum"), eur_gross=("eur_gross", "sum")))
    if "C" in fams and fC is not None and len(fC):
        parts.append(g(fC).groupby(keys, dropna=False).agg(cycles=("late", "size"), late=("late", "sum"), hours=("hours", "mean")))
    D = pd.concat(parts, axis=1) if parts else pd.DataFrame()
    out = pd.DataFrame(index=D.index)
    low_high = {}
    for m in ms:
        fam, kind, unit, status, _ = MEASURES[m]
        col = None
        if m == "washed_kg": col = D.get("customer_washed_kg")
        elif m == "service_requests": col = D.get("service_requests")
        elif m == "garments_allocated": col = D.get("allocated_pieces")
        elif m == "garments_scanned": col = D.get("active_assets_scanned")
        elif m == "garments_not_scanned": col = D.get("allocated_pieces") - D.get("active_assets_scanned") if "allocated_pieces" in D else None
        elif m == "active_wearers": col = D.get("active_wearers")
        elif m == "utilisation_pct": col = 100 * D.active_assets_scanned / D.allocated_pieces.replace(0, np.nan) if "allocated_pieces" in D else None
        elif m == "requests_per_1000_garments": col = 1000 * D.service_requests / D.allocated_pieces.replace(0, np.nan) if "allocated_pieces" in D else None
        elif m in ("water_saving_l", "energy_saving_kwh", "co2_saving_kg"):
            col = D.get(m)
            if col is not None:
                low_high[m] = (D[m + "__low"], D[m + "__high"])
        elif m == "water_l_per_kg": col = D.water_used / D.water_kg.replace(0, np.nan) if "water_used" in D else None
        elif m == "energy_kwh_per_kg": col = D.energy_used / D.energy_kg.replace(0, np.nan) if "energy_used" in D else None
        elif m == "repairs": col = D.get("repair_count")
        elif m == "repairs_per_100_garments": col = 100 * D.repair_count / D.allocated_pieces.replace(0, np.nan) if "repair_count" in D and "allocated_pieces" in D else None
        elif m == "replacements_postponed":
            col = D.get("repair_count")
            if col is not None:
                low_high[m] = (col * ctx.unc.repair_low, col * ctx.unc.repair_high)
        elif m == "purchases_avoided_eur":
            col = D.get("eur_gross")
            if col is not None:
                low_high[m] = (col * ctx.unc.repair_low, col * ctx.unc.repair_high)
        elif m == "service_cycles": col = D.get("cycles")
        elif m == "late_cycles": col = D.get("late")
        elif m == "ontime_pct": col = 100 * (1 - D.late / D.cycles.replace(0, np.nan)) if "cycles" in D else None
        elif m == "avg_cycle_hours": col = D.get("hours")
        if col is None:
            errors.append(f"{m}: no valid data for this selection")
            continue
        out[m] = col
        if m in low_high:
            out[m + "_low"], out[m + "_high"] = low_high[m]
    ms = [m for m in ms if m in out]
    if not ms:
        return {"error": "nothing calculable", "errors": errors}
    out = out.reset_index()
    if "_all" in out:
        out = out.drop(columns="_all")
    out = out.rename(columns={v: k for k, v in DIMS.items() if v in out and k != v})
    sb = _measure(sort_by) if sort_by else None
    if by_month:
        out = out.sort_values([c for c in ("month", "quarter") if c in out])
    elif sb in out:
        out = out.sort_values(sb, ascending=bool(ascending))
    elif gb:
        out = out.sort_values(ms[0], ascending=bool(ascending))
    total_groups = len(out)
    top_n = max(1, min(int(top_n or 25), 60))
    shown = out.head(top_n) if not by_month else out.tail(max(top_n, 24))
    rnd = {}
    for c in shown.columns:
        base = c.replace("_low", "").replace("_high", "")
        if base in MEASURES:
            rnd[c] = DEC.get(MEASURES[base][2], 0)
    rows = [{c: (_r(v, rnd[c]) if c in rnd else (str(v) if not isinstance(v, (int, float)) else v)) for c, v in r.items()} for r in shown.to_dict("records")]
    summary = {}
    if gb and total_groups > 1:
        label = gb[0]
        for m in ms:
            s = out.set_index(label)[m].dropna() if label in out else pd.Series(dtype=float)
            if len(s):
                d = rnd.get(m, 0)
                e = dict(median=_r(s.median(), d), min=_r(s.min(), d), min_at=str(s.idxmin()), max=_r(s.max(), d), max_at=str(s.idxmax()))
                if MEASURES[m][1] == "sum":
                    e["total"] = _r(s.sum(), d)
                if by_month and len(s) >= 2:
                    e.update(first=_r(s.iloc[0], d), last=_r(s.iloc[-1], d), change_first_to_last=_r(s.iloc[-1] - s.iloc[0], d))
                    h = len(s) // 2
                    e.update(first_half_avg=_r(s.iloc[:h].mean(), d), second_half_avg=_r(s.iloc[h:].mean(), d),
                             change_half_to_half=_r(s.iloc[h:].mean() - s.iloc[:h].mean(), d))
                summary[m] = e
    period = f"{fA.month.min()} to {fA.month.max()}"
    res = dict(measures=ms, group_by=gb, filters=filters or {}, period=period, rows=rows, total_groups=total_groups,
               shown=len(rows), summary=summary,
               status={m: MEASURES[m][3] for m in ms} | {f"{m}_{x}": MEASURES[m][3] for m in ms for x in ("low", "high")},
               units={m: MEASURES[m][2] for m in ms},
               definitions={m: MEASURES[m][4] for m in ms})
    if any(m in low_high for m in ms):
        res["range_note"] = (f"_low/_high = Low/High case: baseline ±{ctx.unc.baseline_pct:.0%}, allocation ±{ctx.unc.allocation_pct:.0%}; "
                             f"repair factor {ctx.unc.repair_low}–{ctx.unc.repair_high}.")
    if any(MEASURES[m][0] == "A" and MEASURES[m][3] == "ALLOCATED" for m in ms):
        res["baseline"] = mt.baseline_name(ctx.T, ctx.baseline)
    if errors:
        res["notes"] = errors
    if total_groups > len(rows):
        res["notes"] = res.get("notes", []) + [f"showing {len(rows)} of {total_groups} groups"]
    return res


# ============================================================================================ other tools
def _cid(ctx, customer, required=True):
    cid = ctx.resolve(customer) if customer else None
    return cid


def t_portfolio(ctx, **_):
    P = ctx.P
    return dict(customers=[dict(customer=r.customer, id=r.customer_id, industry=r.industry, segment=r.segment, sites=int(r.sites),
                                countries=r.countries, washed_kg=_r(r.kg, 0), share_of_portfolio_kg_pct=_r(r.share_of_portfolio_kg, 1),
                                utilisation_pct=_r(r.utilisation), ontime_pct=_r(r.ontime), requests_per_1000_garments=_r(r.requests_per_1000),
                                repairs_per_100_garments=_r(r.repairs_per_100), sites_needing_attention=int(r.sites_attention),
                                water_saving_l=_r(r.water_saving, 0), water_saving_l_low=_r(r.water_low, 0), water_saving_l_high=_r(r.water_high, 0))
                           for r in P.itertuples()],
                status={"water_saving_l": "ALLOCATED", "water_saving_l_low": "ALLOCATED", "water_saving_l_high": "ALLOCATED"},
                default_status="CALCULATED", baseline=mt.baseline_name(ctx.T, ctx.baseline),
                note="Internal view. Few accounts: a side-by-side comparison, not a statistical benchmark.")


def t_metric_detail(ctx, customer=None, metric=None, site=None, **_):
    cid = _cid(ctx, customer)
    if not cid:
        return {"error": "name a customer", "known": list(ctx.names.values())}
    sites = ctx.sites_in(site, cid) if site else None
    M = ctx.metrics(cid, sites=sites or None)
    t = _plain(metric or "")
    key = t.replace(" ", "_") if t.replace(" ", "_") in M else None
    if key is None and any(w in t for w in ("saving", "saved")):
        key = next((k for k in M if k.endswith("saving") and k.split("_")[0] in t), None)
    for k, m in ([] if key else M.items()):
        if t and (t in _plain(k) or t in _plain(m.label) or _plain(k) in t):
            key = k
            break
    if key is None:
        return {"error": f"metric not found: {metric}", "available": {k: m.label for k, m in M.items()}, "not_calculated": M.missing}
    m = M[key]
    inputs = {k: (_r(v, 3) if isinstance(v, (int, float, np.floating, np.integer)) else str(v)) for k, v in m.inputs.items()}
    return dict(customer=ctx.name(cid), site=site if sites else None, metric=m.label, value=m.fmt(), low=m._f(m.low, m.unit), high=m._f(m.high, m.unit),
                exact=m.exact, status=m.status, formula=m.formula, inputs=inputs, input_data_status=m.input_status, range_varies=m.range_basis or "nothing (exact)",
                sources=list(m.sources), note=m.note, caveat=m.caveat, baseline=M.baseline_name)


def _flag_reasons(r, med):
    out = []
    if r.flag_utilisation: out.append(f"utilisation {r.utilisation:.1f} % vs site median {med['utilisation']:.1f} %")
    if r.flag_ontime: out.append(f"on-time {r.ontime:.1f} % vs site median {med['ontime']:.1f} %")
    if r.flag_requests: out.append(f"{r.requests_per_1000:.1f} requests per 1000 garments vs site median {med['requests_per_1000']:.1f}")
    return out


def t_flagged_sites(ctx, customer=None, **_):
    cid = _cid(ctx, customer)
    S = ctx.S if not cid else ctx.S[ctx.S.customer_id == cid]
    rows = []
    for c, St in S.groupby("customer_id"):
        med = St[["utilisation", "ontime", "requests_per_1000"]].median()
        for r in St[St.attention].itertuples():
            rows.append(dict(site=r.site, customer=r.customer, country=r.country, utilisation_pct=_r(r.utilisation), ontime_pct=_r(r.ontime),
                             requests_per_1000_garments=_r(r.requests_per_1000), garments=_r(r.pieces, 0), extreme=bool(r.extreme),
                             why=_flag_reasons(r, med)))
    return dict(customer=ctx.name(cid) if cid else "all customers", sites=rows, sites_checked=int(len(S)), default_status="CALCULATED",
                rule="robust outlier vs the customer's own sites (median/MAD z≥1.5 on ≥2 indicators with a minimum effect size, or z≥3 on one). A signal to ask about, not a diagnosis.")


def t_site_profile(ctx, site=None, customer=None, **_):
    cid = _cid(ctx, customer)
    ids = ctx.sites_in(site or "", cid)
    if not ids:
        S = ctx.S if not cid else ctx.S[ctx.S.customer_id == cid]
        return {"error": f"site not found: {site}", "known_sites": list(S.site)[:40]}
    r = ctx.S[ctx.S.site_id == ids[0]].iloc[0]
    St = ctx.S[ctx.S.customer_id == r.customer_id]
    med = St[["utilisation", "ontime", "requests_per_1000", "pieces"]].median()
    rk = lambda col, asc: int(St[col].rank(ascending=asc, method="min")[St.site_id == r.site_id].iloc[0])
    prod = query(ctx, ["garments_allocated", "utilisation_pct", "repairs"], ["product"], {"site": r.site_id, "customer": r.customer_id})
    mo = query(ctx, ["utilisation_pct", "service_requests"], ["month"], {"site": r.site_id, "customer": r.customer_id})
    sa = pf.stale_assets(ctx.T, r.customer_id, 90)
    stale_here = next((n for s, n in sa.get("top_sites", []) if s == r.site), None) if sa else None
    return dict(site=r.site, site_id=r.site_id, customer=r.customer, country=r.country, type=r.type,
                garments=_r(r.pieces, 0), washed_kg=_r(r.kg, 0), utilisation_pct=_r(r.utilisation), ontime_pct=_r(r.ontime),
                requests_per_1000_garments=_r(r.requests_per_1000), repairs=_r(r.repairs, 0),
                water_saving_l=_r(r.water_saving, 0), needs_attention=bool(r.attention), why=_flag_reasons(r, med) if r.attention else [],
                customer_site_median=dict(utilisation_pct=_r(med.utilisation), ontime_pct=_r(med.ontime), requests_per_1000_garments=_r(med.requests_per_1000)),
                difference_vs_median=dict(utilisation_pp=_r(r.utilisation - med.utilisation), ontime_pp=_r(r.ontime - med.ontime),
                                          requests_per_1000=_r(r.requests_per_1000 - med.requests_per_1000)),
                rank_of_sites=dict(n_sites=len(St), utilisation_rank_lowest_first=rk("utilisation", True),
                                   requests_rank_highest_first=rk("requests_per_1000", False)),
                by_product=prod.get("rows", []), by_month=mo.get("rows", []), month_trend=mo.get("summary", {}),
                status={"water_saving_l": "ALLOCATED"}, default_status="CALCULATED")


def t_compare_baselines(ctx, customer=None, **_):
    cid = _cid(ctx, customer)
    if not cid:
        return {"error": "name a customer"}
    B = ctx.T.get("baselines")
    rows = []
    for b in B.itertuples():
        M = ctx.metrics(cid, baseline=b.baseline_id)
        g = lambda k, a: _r(getattr(M[k], a), 0) if k in M else None
        rows.append(dict(baseline=mt.baseline_name(ctx.T, b.baseline_id), baseline_water_l_per_kg=_r(b.water_l_per_kg, 2),
                         baseline_energy_kwh_per_kg=_r(b.energy_kwh_per_kg, 3), water_saving_l=g("water_saving", "value"),
                         water_saving_l_low=g("water_saving", "low"), water_saving_l_high=g("water_saving", "high"),
                         energy_saving_kwh=g("energy_saving", "value"), co2_saving_kg=g("co2_service", "value"),
                         selected=b.baseline_id == ctx.baseline))
    M = ctx.metrics(cid)
    return dict(customer=ctx.name(cid), rows=rows, lindstrom_water_l_per_kg=_r(M["water_per_kg"].value, 2) if "water_per_kg" in M else None,
                default_status="ALLOCATED", status={"baseline_water_l_per_kg": "ESTIMATED", "baseline_energy_kwh_per_kg": "ESTIMATED", "lindstrom_water_l_per_kg": "ALLOCATED"},
                note="Baselines are illustrative pack values. The saving stays positive for any alternative above Lindström's allocated L/kg.")


def _stale_by_site(ctx, cid, days):
    C = ctx.C
    if C is None:
        return None
    c = C[C.customer_id == cid]
    end = C.delivered_timestamp.max()
    last = c.groupby(["asset_id", "site"]).delivered_timestamp.max().reset_index()
    last["age"] = (end - last.delivered_timestamp).dt.days
    g = last.groupby("site").agg(garments=("asset_id", "size"), stale=("age", lambda a: int((a > days).sum())))
    g["stale_pct"] = 100 * g.stale / g.garments
    return g.sort_values("stale", ascending=False).reset_index()


def t_stale_garments(ctx, customer=None, days=90, **_):
    cid = _cid(ctx, customer)
    if not cid:
        return {"error": "name a customer"}
    days = int(days or 90)
    sa = pf.stale_assets(ctx.T, cid, days)
    if not sa:
        return {"error": "no RFID delivery timestamps"}
    g = _stale_by_site(ctx, cid, days)
    return dict(customer=ctx.name(cid), threshold_days=days, garments_with_scans=sa["assets"], over_threshold=sa["stale"],
                over_threshold_pct=_r(sa["share"]), median_days_since_delivery=_r(sa["median_age"], 0), p90_days=_r(sa["p90_age"], 0),
                as_of=sa["end"], rows=[dict(site=r.site, garments=int(r.garments), over_threshold=int(r.stale), over_threshold_pct=_r(r.stale_pct)) for r in g.head(25).itertuples()],
                default_status="CALCULATED",
                caveats=["Threshold is illustrative; the customer defines what is acceptable.", "Sample cycles are sparse (3–8 per garment per year): indicative only.",
                         "Garment level only, never named wearers (GDPR)."])


def t_opportunities(ctx, customer=None, stale_days=90, **_):
    cid = _cid(ctx, customer)
    if not cid:
        return {"error": "name a customer"}
    M = ctx.metrics(cid)
    St = ctx.S[ctx.S.customer_id == cid]
    cards = pf.opportunities(ctx.T, cid, M, St, ctx.RI, ctx.unc, int(stale_days or 90))
    return dict(customer=ctx.name(cid), default_status="HYPOTHESIS",
                opportunities=[dict(title=c["title"], hypothesis=c["hypothesis"], evidence=c["evidence_internal"], sizing=c["sizing"],
                                    data_status=c["status"], assumptions=c["assumptions"], matches_customer_priority=bool(c["fit"]),
                                    confirm_with_customer=c["confirm"], caveat=c["caveat"]) for c in cards],
                note="Evidence-backed hypotheses for a conversation, sized in units, never revenue claims.")


def t_challenges(ctx, customer=None, **_):
    cid = _cid(ctx, customer)
    if not cid:
        return {"error": "name a customer"}
    M = ctx.metrics(cid)
    out = []
    for c in pf.challenges(ctx.T, M, cid, ctx.baseline, ctx.unc, pf.issues_for_customer(ctx.issues, ctx.T, cid) if ctx.issues is not None else None):
        d = dict(question=c["q"], number=c["number"], answer=c["answer"], what_would_change_it=c["changes"])
        if c.get("table") is not None:
            d["table"] = c["table"].to_dict("records")
        out.append(d)
    return dict(customer=ctx.name(cid), challenges=out, default_status="ESTIMATED")


def t_data_issues(ctx, customer=None, **_):
    I = ctx.issues
    if I is None or I.empty:
        return {"issues": [], "default_status": "CALCULATED"}
    cid = _cid(ctx, customer)
    if cid:
        I = pf.issues_for_customer(I, ctx.T, cid)
    return dict(scope=ctx.name(cid) if cid else "all loaded data", default_status="CALCULATED",
                counts=I.severity.value_counts().to_dict(),
                issues=[dict(severity=r.severity, check=r.check, table=r.table, where=r.location, rows=int(r.n_rows), explanation=r.explanation,
                             suggested_fix=r.fix, default=r.default_action) for r in I.itertuples()])


def t_industry_context(ctx, customer=None, **_):
    cid = _cid(ctx, customer)
    if not cid:
        return {"error": "name a customer"}
    cu = ctx.CU.set_index("customer_id").loc[cid]
    P = ctx.T.get("industry_priorities")
    rows = []
    if P is not None and not P.empty:
        p = P[P.industry.astype(str).str.lower() == str(cu.industry).lower()].sort_values("priority_rank")
        rows = [dict(rank=int(r.priority_rank), theme=r.priority_theme, emphasis=r.dashboard_emphasis) for r in p.itertuples()]
    return dict(customer=ctx.name(cid), industry=cu.industry, segment=cu.segment,
                customer_priority_topics=[t.strip() for t in str(cu.topics).split("|") if t.strip()],
                industry_priorities=rows, default_status="CALCULATED",
                note="Industry priorities come from the data pack's Industry_Priorities sheet (illustrative). Use them to choose emphasis, not as compliance advice.")


def t_what_if(ctx, customer=None, baseline=None, own_water_l_per_kg=None, own_energy_kwh_per_kg=None, repair_share_pct=None,
              utilisation_target_pct=None, ontime_target_pct=None, stale_days=None, exclude_sites=None, exclude_laundries=None,
              baseline_pct=None, allocation_pct=None, **_):
    """Deterministic scenarios. Before/after/change computed in code; everything returned is a what-if."""
    cid = _cid(ctx, customer)
    if not cid:
        return {"error": "name a customer"}
    M0 = ctx.metrics(cid)
    St = ctx.S[ctx.S.customer_id == cid]
    changes, assumptions, extra = [], [], {}

    def ch(label, k, M1, unit_key=None):
        if k in M0 and k in M1:
            a, b = M0[k], M1[k]
            changes.append(dict(measure=label, before=_r(a.value, 1), after=_r(b.value, 1), change=_r(b.value - a.value, 1), unit=a.unit,
                                after_low=_r(b.low, 1), after_high=_r(b.high, 1)))

    T1 = None
    bid = None
    if baseline:
        t = _plain(baseline)
        B = ctx.T["baselines"]
        for b in B.itertuples():
            if t in _plain(b.baseline_name) or t in _plain(b.baseline_id) or any(w in _plain(b.baseline_name) for w in t.split() if len(w) > 3):
                bid = b.baseline_id
                break
        if bid is None:
            return {"error": f"unknown baseline {baseline}", "known": list(B.baseline_name)}
        assumptions.append(f"Comparison baseline switched from {mt.baseline_name(ctx.T, ctx.baseline)} to {mt.baseline_name(ctx.T, bid)}.")
    if own_water_l_per_kg is not None or own_energy_kwh_per_kg is not None:
        T1 = dict(ctx.T)
        B = ctx.T["baselines"].copy()
        src = B[B.baseline_id == (bid or ctx.baseline)].iloc[0].copy()
        src["baseline_id"], src["baseline_name"] = "B_CUSTOMER", "Customer's own figures (what-if)"
        if own_water_l_per_kg is not None:
            src["water_l_per_kg"] = float(own_water_l_per_kg)
            assumptions.append(f"Customer's own water use {float(own_water_l_per_kg):g} L/kg replaces the baseline value.")
        if own_energy_kwh_per_kg is not None:
            src["energy_kwh_per_kg"] = float(own_energy_kwh_per_kg)
            assumptions.append(f"Customer's own energy use {float(own_energy_kwh_per_kg):g} kWh/kg replaces the baseline value.")
        T1["baselines"] = pd.concat([B, src.to_frame().T], ignore_index=True)
        bid = "B_CUSTOMER"
    unc1 = ctx.unc
    if baseline_pct is not None or allocation_pct is not None:
        unc1 = Uncertainty(baseline_pct=float(baseline_pct) / 100 if baseline_pct is not None else ctx.unc.baseline_pct,
                           allocation_pct=float(allocation_pct) / 100 if allocation_pct is not None else ctx.unc.allocation_pct,
                           repair_low=ctx.unc.repair_low, repair_high=ctx.unc.repair_high)
        assumptions.append(f"Sensitivity: baseline ±{unc1.baseline_pct:.0%}, allocation ±{unc1.allocation_pct:.0%}.")
    sites = None
    if exclude_sites or exclude_laundries:
        ex = set()
        for s in (exclude_sites if isinstance(exclude_sites, list) else [exclude_sites] if exclude_sites else []):
            ex |= set(ctx.sites_in(s, cid))
        T1 = dict(T1 or ctx.T)
        for lname in (exclude_laundries if isinstance(exclude_laundries, list) else [exclude_laundries] if exclude_laundries else []):
            L = ctx.T.get("laundries")
            lid = [r.laundry_id for r in L.itertuples() if _plain(lname) in (_plain(r.laundry_id), _plain(r.laundry_name)) or _plain(lname) in _plain(r.laundry_name)] if L is not None else []
            lid = lid or [lname]
            for tn in ("service_activity", "repairs", "service_cycles"):
                d = T1.get(tn)
                if d is not None and "laundry_id" in d:
                    T1[tn] = d[~d.laundry_id.isin(lid)]
            assumptions.append(f"Rows served by laundry {', '.join(map(str, lid))} excluded.")
        if ex:
            sites = [s for s in St.site_id if s not in ex]
            assumptions.append(f"Excluded sites: {', '.join(St[St.site_id.isin(ex)].site)}.")
    if bid or T1 is not None or unc1 is not ctx.unc or sites:
        M1 = mt.metrics(T1 or ctx.T, cid, bid or ctx.baseline, "Base", unc1, sites=sites)
        for k, lab in (("water_saving", "Water saved"), ("energy_saving", "Energy saved"), ("co2_service", "Service emissions saved"),
                       ("kg", "Washed kg"), ("utilisation", "Garment utilisation"), ("ontime", "On-time cycles"), ("repairs", "Repairs")):
            ch(lab, k, M1)
        changes = [c for c in changes if abs(c["change"] or 0) > 1e-9] or changes
    if repair_share_pct is not None and "repairs" in M0:
        sh = float(repair_share_pct) / 100
        g_eur = M0["avoided_cost"].inputs.get("gross_EUR") if "avoided_cost" in M0 else None
        g_co2 = M0["avoided_co2"].inputs.get("gross_kgCO2e") if "avoided_co2" in M0 else None
        reps = M0["repairs"].value
        changes.append(dict(measure="Replacements postponed", before=_r(reps * 1.0, 0), after=_r(reps * sh, 0), change=_r(reps * sh - reps, 0), unit="garments"))
        if g_eur is not None:
            changes.append(dict(measure="Purchases avoided", before=_r(g_eur, 0), after=_r(g_eur * sh, 0), change=_r(g_eur * sh - g_eur, 0), unit="EUR"))
        if g_co2 is not None:
            changes.append(dict(measure="Avoided product emissions", before=_r(g_co2, 0), after=_r(g_co2 * sh, 0), change=_r(g_co2 * sh - g_co2, 0), unit="kgCO2e"))
        assumptions.append(f"{float(repair_share_pct):g} % of repairs really prevent a purchase (Base case assumes 100 %, an upper bound).")
    if utilisation_target_pct is not None:
        t = float(utilisation_target_pct)
        A = ctx.A[(ctx.A.customer_id == cid)]
        last = A.month.max()
        d = A[A.month == last].groupby("site").agg(alloc=("allocated_pieces", "sum"), scanned=("active_assets_scanned", "sum"))
        d["util"] = 100 * d.scanned / d.alloc
        below = d[d.util < t].copy()
        below["releasable"] = below.alloc - below.scanned / (t / 100)
        rel = below.releasable.sum()
        tot_alloc, tot_scan = d.alloc.sum(), d.scanned.sum()
        changes.append(dict(measure="Garments allocated", before=_r(tot_alloc, 0), after=_r(tot_alloc - rel, 0), change=_r(-rel, 0), unit="garments"))
        changes.append(dict(measure="Garment utilisation", before=_r(100 * tot_scan / tot_alloc), after=_r(100 * tot_scan / (tot_alloc - rel)),
                            change=_r(100 * tot_scan / (tot_alloc - rel) - 100 * tot_scan / tot_alloc), unit="%"))
        extra["sites_below_target"] = [dict(site=s, utilisation_pct=_r(r.util), garments_allocated=_r(r.alloc, 0), garments_that_could_be_released=_r(r.releasable, 0))
                                       for s, r in below.sort_values("releasable", ascending=False).iterrows()][:15]
        assumptions.append(f"Every site below {t:g} % utilisation is right-sized to exactly {t:g} % in month {last}; sites above are unchanged. Scanned garments stay as they are.")
    if ontime_target_pct is not None:
        t = float(ontime_target_pct)
        C = ctx.C[ctx.C.customer_id == cid]
        d = C.groupby("site").agg(cycles=("late", "size"), late=("late", "sum"))
        d["ontime"] = 100 * (1 - d.late / d.cycles)
        below = d[d.ontime < t].copy()
        below["late_after"] = below.cycles * (1 - t / 100)
        fewer = (below.late - below.late_after).sum()
        changes.append(dict(measure="Late service cycles", before=_r(d.late.sum(), 0), after=_r(d.late.sum() - fewer, 0), change=_r(-fewer, 0), unit="cycles"))
        changes.append(dict(measure="On-time cycles", before=_r(100 * (1 - d.late.sum() / d.cycles.sum())), after=_r(100 * (1 - (d.late.sum() - fewer) / d.cycles.sum())),
                            change=_r(100 * fewer / d.cycles.sum()), unit="%"))
        extra["sites_below_target"] = [dict(site=s, ontime_pct=_r(r.ontime), cycles=int(r.cycles), late=int(r.late)) for s, r in below.sort_values("ontime").iterrows()][:15]
        assumptions.append(f"Every site below {t:g} % on-time is lifted to exactly {t:g} %.")
    if stale_days is not None:
        for dd in sorted({90, int(stale_days)}):
            sa = pf.stale_assets(ctx.T, cid, dd)
            if sa:
                extra.setdefault("garment_control", []).append(dict(threshold_days=dd, garments_over_threshold=sa["stale"], share_pct=_r(sa["share"])))
        assumptions.append("Garments whose last RFID delivery is older than the threshold, as of the end of the data.")
    if not changes and not extra:
        return {"error": "no scenario given", "levers": ["baseline", "own_water_l_per_kg", "own_energy_kwh_per_kg", "repair_share_pct", "utilisation_target_pct",
                                                        "ontime_target_pct", "stale_days", "exclude_sites", "exclude_laundries", "baseline_pct", "allocation_pct"]}
    return dict(customer=ctx.name(cid), changes=changes, **extra, assumptions=assumptions, default_status="SCENARIO",
                note="What-if: recomputed in code with the changed input; not a forecast or a commitment.")


# ---------------------------------------------------------------- calc
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.USub: operator.neg, ast.UAdd: operator.pos}


def _eval(node, used):
    if isinstance(node, ast.Expression):
        return _eval(node.body, used)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        used.append(float(node.value))
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.left, used), _eval(node.right, used))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand, used))
    raise ValueError("only + − × ÷ and parentheses on numbers are allowed")


def t_calc(ctx, expression="", label="", **_):
    expr = str(expression).replace("×", "*").replace("÷", "/").replace("−", "-").replace(",", "")
    used = []
    try:
        v = _eval(ast.parse(expr, mode="eval"), used)
    except Exception as e:
        return {"error": f"cannot evaluate: {e}"}
    allowed = _allowed_numbers(ctx)
    bad = [u for u in used if not (u in (100, 1000, 1, 2, 12) or _supported(u, 0, allowed))]
    if bad:
        return {"error": f"operands not found in any tool result: {bad}. Fetch them with a tool first."}
    return dict(label=label or expr, expression=expression, value=_r(v, 3), default_status="CALCULATED",
                note="Derived exactly from numbers returned by earlier tool results.")


# ============================================================================================ standing snapshot
def snapshot(ctx, customer=None, **_):
    """The standing account summary. Built by code only; also a tool so the model can quote it."""
    cid = _cid(ctx, customer) if customer else None
    if not cid:
        return _portfolio_snapshot(ctx)
    M = ctx.metrics(cid)
    St = ctx.S[ctx.S.customer_id == cid]
    cu = ctx.CU.set_index("customer_id").loc[cid]
    kp = []

    def k(key, label=None, note=""):
        if key in M:
            m = M[key]
            kp.append(dict(key=key, label=label or m.label, value=m.fmt(), low=None if m.exact else m._f(m.low, m.unit),
                           high=None if m.exact else m._f(m.high, m.unit), status=m.status, note=note))
    k("kg", "Textiles washed")
    k("pieces", "Garments in circulation")
    k("utilisation", "Garment utilisation (last month)")
    k("ontime", "On-time service cycles")
    rq = 1000 * M["requests"].value / M["pieces"].value if "requests" in M and "pieces" in M else None
    if rq is not None:
        kp.append(dict(key="requests_per_1000", label="Service requests per 1000 garments", value=f"{rq:.1f}", status="CALCULATED", note=f"{nf(M['requests'].value)} requests in the period"))
    k("repairs", "Repairs completed")
    k("water_saving", f"Water saved vs {M.baseline_name}")
    k("co2_service", f"Service CO2e saved vs {M.baseline_name}")
    # ---- what is moving (second half vs first half of the period)
    q = query(ctx, ["utilisation_pct", "service_requests", "repairs", "ontime_pct"], ["month"], {"customer": cid})
    moving = []
    labels = {"utilisation_pct": ("Garment utilisation", "%", 1, True), "service_requests": ("Service requests per month", "", 0, False),
              "repairs": ("Repairs per month", "", 0, None), "ontime_pct": ("On-time cycles", "%", 1, True)}
    for m, (lab, unit, d, good_up) in labels.items():
        s = q.get("summary", {}).get(m)
        if not s or s.get("first_half_avg") is None:
            continue
        a, b = s["first_half_avg"], s["second_half_avg"]
        rel = (b - a) / a if a else 0
        thr = 0.005 if unit == "%" else 0.05
        direction = "flat" if abs(rel) < thr else ("up" if b > a else "down")
        tone = "neutral" if direction == "flat" or good_up is None else ("good" if (direction == "up") == good_up else "watch")
        u = f" {unit}" if unit else ""
        moving.append(dict(label=lab, direction=direction, tone=tone, text=f"{lab}: {nf(a, d)}{u} → {nf(b, d)}{u} (first vs second half-year average)",
                           first_half=a, second_half=b, status="CALCULATED"))
    # ---- watch list
    watch = []
    att = St[St.attention]
    if len(att):
        med = St[["utilisation", "ontime", "requests_per_1000"]].median()
        for r in att.sort_values(["extreme", "n_flags"], ascending=False).head(4).itertuples():
            watch.append(dict(text=f"{r.site} ({r.country}): " + "; ".join(_flag_reasons(r, med)), status="CALCULATED", kind="site", site=r.site))
    sa = pf.stale_assets(ctx.T, cid, 90)
    if sa and sa["stale"]:
        watch.append(dict(text=f"{nf(sa['stale'])} of {nf(sa['assets'])} scanned garments ({sa['share']:.0f} %) have had no delivery for more than 90 days (as of {sa['end']}; illustrative threshold)",
                          status="CALCULATED", kind="garment control"))
    if ctx.issues is not None and len(ctx.issues):
        Ib = pf.issues_for_customer(ctx.issues, ctx.T, cid)
        e, w = int((Ib.severity == "ERROR").sum()), int((Ib.severity == "WARNING").sum())
        if e or w:
            watch.append(dict(text=f"Data: {e} error(s) and {w} warning(s) touch this customer's figures, e.g. {Ib[Ib.severity.isin(['ERROR', 'WARNING'])].check.iloc[0]}",
                              status="CALCULATED", kind="data"))
    for key in ("water_saving", "co2_service"):
        if key in M and M[key].caveat:
            watch.append(dict(text=M[key].caveat, status="ALLOCATED", kind="coverage"))
            break
    # ---- open threads (hypotheses)
    opps = pf.opportunities(ctx.T, cid, M, St, ctx.RI, ctx.unc, 90)
    threads = [dict(title=c["title"], sizing=c["sizing"], data_status=c["status"], fits_priority=bool(c["fit"]), status="HYPOTHESIS") for c in opps[:3]]
    ic = t_industry_context(ctx, cid)
    head = (f"{ctx.name(cid)} · {cu.industry} · {len(St)} sites in {St.country.nunique()} countries · "
            f"{int(att.shape[0])} site(s) stand out · baseline {M.baseline_name} · period {ctx.months[0]} to {ctx.months[-1]}")
    trend = q.get("rows", [])
    return dict(customer=ctx.name(cid), customer_id=cid, headline=head, kpis=kp, moving=moving, watch=watch, open_threads=threads,
                industry_lens=[r["theme"] for r in ic.get("industry_priorities", [])], priority_topics=ic.get("customer_priority_topics", []),
                trend=trend, default_status="CALCULATED", status={"water_saving": "ALLOCATED", "co2_service": "ALLOCATED"},
                note="Synthetic demo data. Calculated = exact from the data; Estimate = allocation or assumption, range shown; Hypothesis = to confirm with the customer.")


def _portfolio_snapshot(ctx):
    P = ctx.P
    kp = [dict(label="Customers", value=str(len(P)), status="CALCULATED"), dict(label="Sites", value=str(int(P.sites.sum())), status="CALCULATED"),
          dict(label="Textiles washed", value=big(P.kg.sum(), "kg"), status="CALCULATED"),
          dict(label="Sites needing attention", value=str(int(P.sites_attention.sum())), status="CALCULATED")]
    lines = [dict(text=f"{r.customer}: {r.sites} sites, {r.share_of_portfolio_kg:.0f} % of washed kg, utilisation {r.utilisation:.1f} %, on-time {r.ontime:.1f} %, "
                       f"{int(r.sites_attention)} site(s) stand out", status="CALCULATED") for r in P.itertuples()]
    lo = P.sort_values("utilisation").iloc[0]
    hi = P.sort_values("requests_per_1000", ascending=False).iloc[0]
    watch = [dict(text=f"Lowest garment utilisation: {lo.customer} ({lo.utilisation:.1f} %)", status="CALCULATED"),
             dict(text=f"Highest service-request rate: {hi.customer} ({hi.requests_per_1000:.1f} per 1000 garments)", status="CALCULATED")]
    return dict(customer="Whole portfolio", headline=f"{len(P)} customers · {int(P.sites.sum())} sites · period {ctx.months[0]} to {ctx.months[-1]}",
                kpis=kp, moving=lines, watch=watch, open_threads=[], default_status="CALCULATED", trend=[])


# ============================================================================================ tool registry
TOOLS = {"query": query, "account_snapshot": snapshot, "portfolio_overview": t_portfolio, "metric_detail": t_metric_detail,
         "flagged_sites": t_flagged_sites, "site_profile": t_site_profile, "compare_baselines": t_compare_baselines,
         "stale_garments": t_stale_garments, "opportunities": t_opportunities, "challenges": t_challenges, "data_issues": t_data_issues,
         "industry_context": t_industry_context, "what_if": t_what_if, "calc": t_calc}

_C = {"type": "string", "description": "customer name or id"}
_S = {"type": "string"}
SCHEMAS = [
    {"name": "query", "description": "Exact aggregation of the validated data. Use for any number, ranking, drill-down, comparison or trend. "
                                     "measures: " + ", ".join(MEASURES) + ". group_by: " + ", ".join(DIMS) + ". Stock measures (garments, utilisation) use the last month "
                                     "of the period unless grouped by month. Results include per-group rows, a summary (median/min/max, and first/last/half-year change when grouped by month), status per measure.",
     "input_schema": {"type": "object", "properties": {
         "measures": {"type": "array", "items": {"type": "string", "enum": list(MEASURES)}},
         "group_by": {"type": "array", "items": {"type": "string", "enum": list(DIMS)}},
         "filters": {"type": "object", "description": "dimension -> value or list, e.g. {\"customer\": \"NorthStar\", \"country\": \"Sweden\", \"month_from\": \"2025-07\", \"month_to\": \"2025-12\"}"},
         "sort_by": {"type": "string"}, "ascending": {"type": "boolean"}, "top_n": {"type": "integer"}}, "required": ["measures"]}},
    {"name": "account_snapshot", "description": "Standing summary of one customer (KPIs with status and ranges, what is moving, watch list, open threads). Omit customer for the portfolio.",
     "input_schema": {"type": "object", "properties": {"customer": _C}}},
    {"name": "portfolio_overview", "description": "All customers side by side (internal view).", "input_schema": {"type": "object", "properties": {}}},
    {"name": "metric_detail", "description": "How one headline metric is calculated: formula, inputs, Low/Base/High, status, caveats. Optional site.",
     "input_schema": {"type": "object", "properties": {"customer": _C, "metric": _S, "site": _S}, "required": ["customer", "metric"]}},
    {"name": "flagged_sites", "description": "Sites that stand out against the customer's own sites, with the reasons.", "input_schema": {"type": "object", "properties": {"customer": _C}}},
    {"name": "site_profile", "description": "Deep dive on one site: metrics vs the customer's site median, rank, product mix, monthly trend.",
     "input_schema": {"type": "object", "properties": {"site": _S, "customer": _C}, "required": ["site"]}},
    {"name": "compare_baselines", "description": "Water/energy/CO2e savings for one customer against every comparison baseline (local laundry, home, in-house).",
     "input_schema": {"type": "object", "properties": {"customer": _C}, "required": ["customer"]}},
    {"name": "stale_garments", "description": "RFID garment control: garments with no delivery for more than `days` (hygiene risk), by site.",
     "input_schema": {"type": "object", "properties": {"customer": _C, "days": {"type": "integer"}}, "required": ["customer"]}},
    {"name": "opportunities", "description": "Evidence-backed discussion hypotheses for the account (sized in units, never revenue).",
     "input_schema": {"type": "object", "properties": {"customer": _C, "stale_days": {"type": "integer"}}, "required": ["customer"]}},
    {"name": "challenges", "description": "Questions the customer is likely to challenge, with break-even and sensitivity numbers.",
     "input_schema": {"type": "object", "properties": {"customer": _C}, "required": ["customer"]}},
    {"name": "data_issues", "description": "Validation findings (optionally only those touching one customer).", "input_schema": {"type": "object", "properties": {"customer": _C}}},
    {"name": "industry_context", "description": "Industry priorities from the data and the customer's own stated priority topics. Use for emphasis and brainstorming.",
     "input_schema": {"type": "object", "properties": {"customer": _C}, "required": ["customer"]}},
    {"name": "what_if", "description": "Recompute with a changed input and return before/after/change: baseline (name), own_water_l_per_kg, own_energy_kwh_per_kg, "
                                       "repair_share_pct (share of repairs that prevent a purchase), utilisation_target_pct (right-size sites below it), ontime_target_pct, "
                                       "stale_days, exclude_sites, exclude_laundries, baseline_pct / allocation_pct (sensitivity ±%).",
     "input_schema": {"type": "object", "properties": {"customer": _C, "baseline": _S, "own_water_l_per_kg": {"type": "number"}, "own_energy_kwh_per_kg": {"type": "number"},
                                                        "repair_share_pct": {"type": "number"}, "utilisation_target_pct": {"type": "number"}, "ontime_target_pct": {"type": "number"},
                                                        "stale_days": {"type": "integer"}, "exclude_sites": {"type": "array", "items": _S}, "exclude_laundries": {"type": "array", "items": _S},
                                                        "baseline_pct": {"type": "number"}, "allocation_pct": {"type": "number"}}, "required": ["customer"]}},
    {"name": "calc", "description": "Exact arithmetic (+ − × ÷) on numbers that already appear in tool results, e.g. a difference or a share. Use instead of mental maths.",
     "input_schema": {"type": "object", "properties": {"expression": _S, "label": _S}, "required": ["expression", "label"]}},
    {"name": "respond", "description": "Give the final answer. Call exactly once, after the data tools.",
     "input_schema": {"type": "object", "properties": {
         "read": {"type": "string", "description": "2–4 sentences, plain business English: the answer and what it means for the account. Numbers only as returned by tools."},
         "key_numbers": {"type": "array", "description": "2–5 numbers that matter, each copied from a tool result.", "items": {"type": "object", "properties": {
             "label": _S, "value": {"type": "string", "description": "the number with unit, as in the tool result"}, "result_id": _S}, "required": ["label", "value", "result_id"]}},
         "charts": {"type": "array", "description": "0–2 charts drawn from a tool result's rows. Use when a comparison of >3 items or a trend is clearer as a picture.",
                    "items": {"type": "object", "properties": {"result_id": _S, "kind": {"type": "string", "enum": ["bar", "barh", "line", "scatter"]},
                                                               "x": _S, "y": {"type": "array", "items": _S}, "color": _S, "title": _S}, "required": ["result_id", "kind", "x", "y", "title"]}},
         "hypotheses": {"type": "array", "items": _S, "description": "Ideas or explanations the data does not prove (to test with the customer). No new numbers."},
         "follow_ups": {"type": "array", "items": _S, "description": "2–3 sharp next questions the KAM could ask you."},
         "caveat": {"type": "string", "description": "One line on what limits this answer (data status, assumption, coverage), if relevant."}},
         "required": ["read", "key_numbers", "follow_ups"]}},
]

SYSTEM = """You are the account analyst for a Lindström key account manager (KAM). Lindström rents and launders workwear for multi-site B2B customers. The KAM uses you to prepare and think through the yearly steering-committee meeting with one customer: what value was delivered, what is moving, which sites need attention, what to propose next, and how the customer might challenge the numbers.

Behave like a sharp analyst who knows the numbers: answer the actual question first, drill down when something stands out, compare against the customer's own median or other accounts, test what-ifs, and offer angles the KAM may not have considered. Be concise and concrete. No filler.

Hard rules (they are enforced by code; an answer that breaks them is rejected):
1. Never compute, estimate, recall or round-trip a number yourself. Every number you state must appear in a tool result in this conversation (or in the KAM's question). For a difference, share or ratio, call `calc` with numbers from tool results. You may round to fewer decimals or write k / M.
2. Keep the status of each number clear: CALCULATED = exact from the data; ALLOCATED or ESTIMATED = estimate, mention the range or assumption when it matters; SCENARIO = what-if. Badges on key numbers are added by code from the tool result, so pick key numbers from the right result_id.
3. Ideas, explanations and brainstormed angles that the data does not prove go in `hypotheses`, phrased as something to test with the customer. They may not contain numbers that no tool returned.
4. Data is synthetic and illustrative. Never present a figure as audited, verified, or as a revenue or sales claim. Peer comparisons between customers are for the KAM only; say so if the KAM seems to want customer-facing wording.
5. If the data cannot answer, say what is missing and which data would answer it.

Method: call the tools you need (several in one turn is fine), then call `respond` exactly once. Prefer `query` for any slicing (by site, country, product, product_group, month, quarter, laundry, repair_type) and filters. Use charts when they beat a sentence: a ranking of more than 3 items (bar/barh), a monthly trend (line), two measures against each other (scatter). Chart x and y must be column names in that result's rows. The `read` is 2–4 sentences. Follow-ups should push the thinking forward (drill-down, what-if, an angle for the meeting).

Units: utilisation and on-time are %, requests are per 1000 garments, repairs per 100 garments, water in L, energy in kWh, CO2e in kg."""


# ============================================================================================ verification
_SCALE = {"m": 1e6, "million": 1e6, "k": 1e3, "thousand": 1e3, "bn": 1e9, "billion": 1e9}
_NUM = re.compile(r"(?<![A-Za-z0-9_.])(\d+(?:\.\d+)?)(?:\s?(M|million|k|thousand|bn|billion)\b)?", re.I)


def _norm(text: str) -> str:
    s = str(text)
    for ch in (" ", " ", " ", " "):
        s = s.replace(ch, " ")
    s = re.sub(r"(?<=\d)[ ,](?=\d{3}(?!\d))", "", s)
    s = re.sub(r"(?<=\d)[ ,](?=\d{3}(?!\d))", "", s)
    s = re.sub(r"\b(20[2-3]\d)-(0[1-9]|1[0-2])\b", "", s)            # months like 2025-03
    s = re.sub(r"\b(20[2-3]\d)-Q[1-4]\b", "", s)
    s = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", "", s)                         # dates
    return s


def numbers(text: str) -> list[tuple[float, float]]:
    """(value, display tolerance) for every number in the text, with k/M scaling."""
    out = []
    for m in _NUM.finditer(_norm(text)):
        raw = m.group(1)
        sc = _SCALE.get((m.group(2) or "").lower(), 1.0)
        d = len(raw.split(".")[1]) if "." in raw else 0
        out.append((float(raw) * sc, 0.5 * (10 ** -d) * sc))
    return out


def _allowed_numbers(ctx, extra=()):
    vals = []
    for e in ctx.store.values():
        vals += [v for v, _ in numbers(json.dumps(e["result"], ensure_ascii=False, default=str))]
    for o in extra:
        vals += [v for v, _ in numbers(json.dumps(o, ensure_ascii=False, default=str))]
    return np.array(sorted(set(vals))) if vals else np.array([])


def _supported(n, tol, allowed):
    if not len(allowed):
        return False
    t = max(tol, 0.006 * abs(n), 1e-9)
    return bool(np.any(np.abs(allowed - n) <= t + 0.006 * np.abs(allowed)))


def unsupported(text: str, allowed: np.ndarray, question: str = "") -> list[float]:
    qn = [v for v, _ in numbers(question)]
    bad = []
    low = text.lower()
    for n, tol in numbers(text):
        if 2020 <= n <= 2030 or any(abs(n - q) < 1e-9 for q in qn):
            continue
        if n in (100.0, 1000.0) and f"per {int(n)}" in low:          # unit wording ("per 1000 garments"), not a claim
            continue
        if not _supported(n, tol, allowed):
            bad.append(n)
    return bad


def _status_for(ctx, value: str, rid: str | None):
    """Find the number in the referenced result (or any result) and return (status, result_id). Status comes from the data, not the model."""
    nums = numbers(value)
    if not nums:
        return None, rid
    n, tol = nums[0]
    order = ([rid] if rid in ctx.store else []) + [k for k in reversed(list(ctx.store)) if k != rid]
    for k in order:
        res = ctx.store[k]["result"]
        st = _walk(res, n, tol, res.get("status", {}) or {}, res.get("default_status", "CALCULATED"), None)
        if st:
            return st, k
    return None, rid


def _walk(o, n, tol, smap, default, inherited):
    if isinstance(o, dict):
        local = o.get("status") if isinstance(o.get("status"), str) else None
        for key, v in o.items():
            if key in ("status", "result_id"):
                continue
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                if _supported(float(v), tol, np.array([float(n)])) or abs(float(v) - n) <= max(tol, 0.006 * abs(v)):
                    return local or smap.get(key) or inherited or default
            elif isinstance(v, str):
                if any(abs(x - n) <= max(tol, t, 0.006 * abs(x)) for x, t in numbers(v)):
                    return local or smap.get(key) or inherited or default
            else:
                r = _walk(v, n, tol, smap, default, local or inherited)
                if r:
                    return r
    elif isinstance(o, list):
        for v in o:
            r = _walk(v, n, tol, smap, default, inherited)
            if r:
                return r
    return None


def finalize(ctx, spec: dict, question: str, tools_used: list, source: str) -> tuple[dict, list]:
    """Turn a respond-spec into an answer; return (answer, unsupported numbers)."""
    allowed = _allowed_numbers(ctx)
    texts = [spec.get("read", ""), spec.get("caveat", "") or ""] + list(spec.get("hypotheses") or []) + [c.get("title", "") for c in spec.get("charts") or []]
    bad = []
    for t in texts:
        bad += unsupported(t, allowed, question)
    kn = []
    for k in spec.get("key_numbers") or []:
        b = unsupported(k.get("value", ""), allowed, question)
        if b:
            bad += b
            continue
        st, rid = _status_for(ctx, k.get("value", ""), k.get("result_id"))
        if st is None and numbers(k.get("value", "")):
            bad += [v for v, _ in numbers(k["value"])][:1]
            continue
        kn.append(dict(label=k.get("label", ""), value=k.get("value", ""), status=st or "CALCULATED", result_id=rid))
    charts = []
    for c in spec.get("charts") or []:
        e = ctx.store.get(c.get("result_id"))
        rows = (e or {}).get("result", {}).get("rows") or (e or {}).get("result", {}).get("changes") or (e or {}).get("result", {}).get("customers")
        if not rows:
            continue
        ys = c.get("y") if isinstance(c.get("y"), list) else [c.get("y")]
        cols = set().union(*[r.keys() for r in rows])
        if c.get("x") in cols and all(y in cols for y in ys):
            res = e["result"]
            charts.append(dict(c, y=ys, status=(res.get("status") or {}).get(ys[0]) or res.get("default_status", "CALCULATED")))
    ans = dict(read=spec.get("read", "").strip(), key_numbers=kn, charts=charts, hypotheses=list(spec.get("hypotheses") or []),
               follow_ups=list(spec.get("follow_ups") or [])[:3], caveat=spec.get("caveat") or "", source=source, tools=tools_used,
               result_ids=[t["result_id"] for t in tools_used if t.get("result_id")])
    return ans, sorted(set(bad))


# ============================================================================================ LLM path
def _client():
    """Any configured provider (Anthropic, Gemini, Groq, Ollama, Azure OpenAI) behind one Anthropic-shaped interface; None = rules mode."""
    return providers.get_client()


def _run_tool(ctx, name, args):
    fn = TOOLS.get(name)
    if fn is None:
        return None, {"error": f"unknown tool {name}"}
    try:
        res = fn(ctx, **(args or {}))
    except Exception as e:  # a tool bug must not break the conversation
        res = {"error": f"{type(e).__name__}: {e}"}
    rid, res = ctx.put(name, args, res)
    return rid, res


def history_messages(history):
    """Previous turns as plain text so the model can follow a thread (results stay addressable by id)."""
    msgs = []
    for h in (history or [])[-6:]:
        a = h["answer"]
        kn = "; ".join(f"{k['label']}: {k['value']} [{k['result_id']}]" for k in a.get("key_numbers", []))
        res = ", ".join(f"{t['result_id']}={t['tool']}({json.dumps(t.get('args', {}), ensure_ascii=False)[:120]})" for t in a.get("tools", []) if t.get("result_id"))
        msgs.append({"role": "user", "content": h["q"]})
        msgs.append({"role": "assistant", "content": f"{a.get('read','')}\nKey numbers: {kn or '-'}\nResults available: {res or '-'}"})
    return msgs


def answer(question: str, ctx: Ctx, history=None, focus=None, client=None, max_steps=8) -> dict:
    """Grounded conversational answer. Falls back to rules when there is no client, a call fails,
    or the model keeps stating numbers no tool returned."""
    client = client if client is not None else _client()
    if client is None:
        a = rules_answer(question, ctx, focus)
        a["banner"] = providers.status_line()          # honest: this answer came from rules, not a model
        return a
    snap_rid = None
    if focus:
        snap_rid, snap = ctx.put("account_snapshot", {"customer": focus}, snapshot(ctx, focus))
    sys_txt = SYSTEM + "\n\nCustomers: " + "; ".join(f"{r.customer} ({r.customer_id}, {r.industry}, {r.sites} sites in {r.countries})" for r in ctx.P.itertuples())
    sys_txt += f"\nComparison baseline selected: {mt.baseline_name(ctx.T, ctx.baseline)}. Period: {ctx.months[0]} to {ctx.months[-1]}."
    if focus:
        sys_txt += f"\nThe KAM is currently looking at {ctx.name(ctx.resolve(focus))}. Assume questions are about this customer unless another is named. " \
                   f"Its standing snapshot is result {snap_rid}:\n" + json.dumps(snap, ensure_ascii=False, default=str)[:6000]
    msgs = history_messages(history) + [{"role": "user", "content": question}]
    used, retries = [], 0
    if snap_rid:
        used.append(dict(tool="account_snapshot", args={"customer": focus}, result_id=snap_rid))
    try:
        for _ in range(max_steps):
            r = client.messages.create(model=providers.model_name(), max_tokens=2000, system=sys_txt, tools=SCHEMAS, messages=msgs)
            blocks = list(r.content)
            calls = [b for b in blocks if getattr(b, "type", "") == "tool_use"]
            if not calls:
                text = "".join(getattr(b, "text", "") for b in blocks).strip()
                if len(used) <= (1 if snap_rid else 0):
                    return dict(rules_answer(question, ctx, focus), note="The model answered without looking at the data, so the rule-based answer is shown.")
                ans, bad = finalize(ctx, {"read": text, "key_numbers": [], "follow_ups": []}, question, used, "llm")
                if bad:
                    return dict(rules_answer(question, ctx, focus), note=f"The model's wording contained numbers no calculation produced ({', '.join(nf(b, 2) for b in bad[:3])}), so the rule-based answer is shown.")
                return ans
            msgs.append({"role": "assistant", "content": [_block_dict(b) for b in blocks]})
            results, final = [], None
            for b in calls:
                if b.name == "respond":
                    final = b
                    continue
                rid, res = _run_tool(ctx, b.name, b.input)
                used.append(dict(tool=b.name, args=b.input, result_id=rid))
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": json.dumps(res, ensure_ascii=False, default=str)[:12000]})
            if final is not None:
                data_calls = [u for u in used if u["tool"] != "account_snapshot" or u["result_id"] != snap_rid]
                ans, bad = finalize(ctx, final.input or {}, question, used, "llm")
                if not bad and (data_calls or snap_rid):
                    return ans
                if retries >= 1:
                    return dict(rules_answer(question, ctx, focus), note=f"The model's answer contained numbers no calculation produced ({', '.join(nf(b, 2) for b in bad[:3])}), so the rule-based answer is shown.")
                retries += 1
                results.append({"type": "tool_result", "tool_use_id": final.id, "is_error": True,
                                "content": f"Rejected: these numbers appear in no tool result: {', '.join(nf(b, 3) for b in bad[:6])}. "
                                           "Fetch them with a tool (or use calc on returned numbers), or remove them, then call respond again."})
            msgs.append({"role": "user", "content": results})
    except Exception as e:  # network, auth, schema: never block the KAM
        return dict(rules_answer(question, ctx, focus), note=f"AI unavailable ({type(e).__name__}); rule-based answer shown.")
    return dict(rules_answer(question, ctx, focus), note="No final answer from the model; rule-based answer shown.")


def _block_dict(b):
    if getattr(b, "type", "") == "tool_use":
        return {"type": "tool_use", "id": b.id, "name": b.name, "input": b.input or {}}
    return {"type": "text", "text": getattr(b, "text", "")}


# ============================================================================================ rule-based analyst (no API key)
def _months_in(q):
    m = re.findall(r"\b(20[2-3]\d-(?:0[1-9]|1[0-2]))\b", q)
    if len(m) >= 2:
        return {"month_from": min(m), "month_to": max(m)}
    if re.search(r"\b(h2|second half)\b", q):
        return {"month_from": "2025-07", "month_to": "2025-12"}
    if re.search(r"\b(h1|first half)\b", q):
        return {"month_from": "2025-01", "month_to": "2025-06"}
    qm = re.search(r"\bq([1-4])\b", q)
    if qm:
        s = 3 * int(qm.group(1)) - 2
        return {"month_from": f"2025-{s:02d}", "month_to": f"2025-{s + 2:02d}"}
    return {}


_MEAS_WORDS = [("water", "water_saving_l"), ("energy", "energy_saving_kwh"), ("co2", "co2_saving_kg"), ("emission", "co2_saving_kg"), ("carbon", "co2_saving_kg"),
               ("on-time", "ontime_pct"), ("on time", "ontime_pct"), ("ontime", "ontime_pct"), ("late", "late_cycles"), ("delivery", "ontime_pct"),
               ("turnaround", "avg_cycle_hours"), ("cycle time", "avg_cycle_hours"), ("request", "requests_per_1000_garments"),
               ("repair", "repairs_per_100_garments"), ("utilis", "utilisation_pct"), ("utiliz", "utilisation_pct"), ("idle", "garments_not_scanned"),
               ("not scanned", "garments_not_scanned"), ("unused", "garments_not_scanned"), ("wearer", "active_wearers"), ("kg", "washed_kg"), ("volume", "washed_kg"),
               ("garment", "garments_allocated"), ("cost", "purchases_avoided_eur"), ("purchase", "purchases_avoided_eur")]


def _measures_in(q):
    out = []
    for w, m in _MEAS_WORDS:
        if w in q and m not in out:
            out.append(m)
    return out


def _num_after(q, words):
    for w in words:
        m = re.search(w + r"[^0-9]{0,25}(\d+(?:\.\d+)?)", q)
        if m:
            return float(m.group(1))
    return None


UNSUPPORTED_RE = (r"\b(revenue|turnover|profit|profitab\w*|margin|invoice\w*|contract value|churn|nps|satisfaction score|pricing|price per garment|"
                  r"sales figure\w*|ebitda|cash ?flow)\b")


def rules_answer(question: str, ctx: Ctx, focus=None) -> dict:
    """Deterministic analyst: intent + entities + memory -> tools -> structured answer with charts."""
    q = _plain(question)
    st = ctx.state
    cid = ctx.resolve(question)
    if cid and cid != st.get("customer"):
        st.pop("site", None)
    cid = cid or st.get("customer") or (ctx.resolve(focus) if focus else None)
    if cid:
        st["customer"] = cid
    sites = ctx.sites_in(question, cid) if cid else ctx.sites_in(question)
    if sites:
        st["site"] = sites[0]
    elif re.search(r"\b(that|this|the) site\b|\bthere\b|\bit\b", q) and st.get("site"):
        sites = [st["site"]]
    meas = _measures_in(q)
    if meas:
        st["measure"] = meas[0]
    filt = {"customer": cid} if cid else {}
    filt.update(_months_in(q))
    countries = [c for c in ctx.A.country.dropna().unique() if _plain(c) in q]
    if countries:
        filt["country"] = countries
    used = []

    def run(name, **a):
        rid, res = _run_tool(ctx, name, a)
        used.append(dict(tool=name, args=a, result_id=rid))
        return rid, res

    nm = ctx.name(cid) if cid else "the portfolio"
    spec = dict(read="", key_numbers=[], charts=[], hypotheses=[], follow_ups=[])
    is_whatif = bool(re.search(r"\bwhat if\b|\bif (we|they|the|utilis|on-time|only)\b|\bsuppose\b|\bscenario\b|\bwould\b", q))
    group = next((g for g, ws in (("site", ("by site", "per site", "which site", "each site", "sites")), ("country", ("by country", "per country", "countr")),
                                  ("product", ("by product", "per product", "product")), ("month", ("trend", "by month", "monthly", "over time", "month", "season")),
                                  ("quarter", ("quarter",)), ("repair_type", ("repair type", "kind of repair", "damage")), ("laundry", ("laundr",)),
                                  ("customer", ("customers", "accounts", "portfolio", "compare customer", "across customer")))
                  if any(w in q for w in ws)), None)

    # ---------------------------------------------------------------- out of scope: say so, never answer from an unrelated default
    if re.search(UNSUPPORTED_RE, q):
        spec["read"] = ("That is not in this data. The files hold garments, washing, repairs, deliveries, resources and waste, but no revenue, turnover, price, margin, "
                        "contract-value or customer-satisfaction figures. I will not guess one.")
        spec["follow_ups"] = [f"How are we doing with {nm}?", f"Which sites stand out at {nm}?" if cid else "Which sites stand out?", "What can this data not answer?"]
        return _rules_final(ctx, spec, question, used, note="Declined: outside the data.")

    # ---------------------------------------------------------------- two or more named sites: compare exactly those
    if len(sites) >= 2 and re.search(r"compar|versus|\bvs\b|\bagainst\b|difference between|\bor\b|\band\b", q) and not is_whatif:
        rows = []
        for sid in sites[:3]:
            nme = ctx.S[ctx.S.site_id == sid].site.iloc[0]
            rid, r = run("site_profile", site=nme, customer=cid)
            if "error" not in r:
                rows.append((rid, r))
        if len(rows) >= 2:
            spec["read"] = "Side by side (last month for utilisation; whole period for the rest): " + " | ".join(
                f"{r['site']} ({r['country']}): utilisation {r['utilisation_pct']} %, on-time {r['ontime_pct']} %, {r['requests_per_1000_garments']} requests per 1000 garments" for _, r in rows) + "."
            spec["key_numbers"] = [dict(label=f"{r['site']}: utilisation", value=f"{r['utilisation_pct']} %", result_id=rid) for rid, r in rows] + \
                                  [dict(label=f"{r['site']}: requests per 1000", value=str(r["requests_per_1000_garments"]), result_id=rid) for rid, r in rows]
            spec["follow_ups"] = [f"Drill into {rows[0][1]['site']}", f"Which sites stand out at {nm}?", f"What should I propose to {nm}?"]
            return _rules_final(ctx, spec, question, used)

    # ---------------------------------------------------------------- what-if
    if is_whatif and cid:
        args = {"customer": cid}
        if "home" in q: args["baseline"] = "home"
        elif "in-house" in q or "inhouse" in q or "in house" in q: args["baseline"] = "in-house"
        elif "local" in q and "baseline" in q: args["baseline"] = "local"
        v = _num_after(q, [r"l ?/ ?kg", r"litres? per kg", r"own water"]) if ("l/kg" in q or "per kg" in q or "own water" in q) else None
        mw = re.search(r"(\d+(?:\.\d+)?)\s*(?:l|litres?|liters?)\s*(?:/|per)\s*kg", q)
        if mw: args["own_water_l_per_kg"] = float(mw.group(1))
        me = re.search(r"(\d+(?:\.\d+)?)\s*kwh\s*(?:/|per)\s*kg", q)
        if me: args["own_energy_kwh_per_kg"] = float(me.group(1))
        pct = re.search(r"(\d+(?:\.\d+)?)\s*%", q)
        if "repair" in q and pct: args["repair_share_pct"] = float(pct.group(1))
        elif ("utilis" in q or "utiliz" in q or "right-siz" in q or "allocation" in q) and pct: args["utilisation_target_pct"] = float(pct.group(1))
        elif ("on-time" in q or "on time" in q or "ontime" in q) and pct: args["ontime_target_pct"] = float(pct.group(1))
        elif "utilis" in q or "utiliz" in q or "right-siz" in q:
            med = ctx.S[ctx.S.customer_id == cid].utilisation.median()
            args["utilisation_target_pct"] = round(float(med), 1)
        dm = re.search(r"(\d+)\s*days?", q)
        if dm: args["stale_days"] = int(dm.group(1))
        if sites and any(w in q for w in ("exclude", "without", "drop", "remove")): args["exclude_sites"] = [ctx.S[ctx.S.site_id == s].site.iloc[0] for s in sites]
        lm = re.search(r"\b(l00\d)\b", q)
        if lm: args["exclude_laundries"] = [lm.group(1).upper()]
        if len(args) == 1:       # no lever recognised: never fall back to a default scenario that answers a different question
            spec["read"] = ("I could not tell which input you want to change, so I will not run a scenario. Without a language model I can test: the comparison baseline (home / in-house / local), "
                            "the customer's own litres or kWh per kg (for example 'what if their own water use is fourteen litres per kg'), the share of repairs that prevent a purchase, a utilisation or on-time target, "
                            "the hygiene threshold in days, or excluding a site or laundry. A relative change such as 'water intensity dropped by a tenth' needs an exact value or a configured model.")
            spec["follow_ups"] = [f"What if {nm}'s own water use is 14 L/kg?", f"What if only 50 % of repairs prevent a purchase at {nm}?", f"What if on-time reached 99 % at {nm}?"]
            return _rules_final(ctx, spec, question, used, note="Declined: no recognised lever in the question.")
        rid, r = run("what_if", **args)
        if "error" in r:
            spec["read"] = r["error"] + ". Levers I can test: baseline (home / in-house / local), own L/kg, share of repairs that prevent a purchase, utilisation target, on-time target, hygiene threshold in days, excluding a site or laundry."
        else:
            parts = [f"{c['measure']} {_fmtv(c['before'], c['unit'])} → {_fmtv(c['after'], c['unit'])} ({_chg(c['change'], c['unit'])})" for c in r["changes"][:4]]
            spec["read"] = f"What-if for {nm}: " + "; ".join(parts) + ". " + " ".join(r["assumptions"])
            for gc in r.get("garment_control", []):
                spec["read"] += f" At {gc['threshold_days']} days: {nf(gc['garments_over_threshold'])} garments ({gc['share_pct']} %) over the threshold."
            spec["key_numbers"] = [dict(label=f"{c['measure']} (after)", value=_fmtv(c["after"], c["unit"]), result_id=rid) for c in r["changes"][:4]]
            if r.get("sites_below_target"):
                rid2, r2 = run("query", measures=["utilisation_pct", "garments_not_scanned"], group_by=["site"], filters={"customer": cid}, sort_by="utilisation_pct", ascending=True, top_n=12)
                if "utilisation_target_pct" in args:
                    spec["charts"].append(dict(result_id=rid2, kind="barh", x="site", y=["utilisation_pct"], title="Utilisation by site, last month"))
            spec["hypotheses"] = ["A what-if is a recalculation with one input changed, not a forecast. Confirm the input with the customer before using it."]
        spec["follow_ups"] = [f"Which sites would change most at {nm}?", f"How fair is the baseline for {nm}?", f"What if only 50 % of repairs prevent a purchase at {nm}?"]
        return _rules_final(ctx, spec, question, used)

    # ---------------------------------------------------------------- how is X calculated
    if re.search(r"how (is|are|was|do you) .*(calculat|comput|derived|work out)|formula|where does .* come from|explain the", q) and cid:
        mkey = {"water_saving_l": "water_saving", "energy_saving_kwh": "energy_saving", "co2_saving_kg": "co2_service", "ontime_pct": "ontime", "utilisation_pct": "utilisation",
                "requests_per_1000_garments": "requests", "repairs_per_100_garments": "repairs", "purchases_avoided_eur": "avoided_cost", "garments_not_scanned": "utilisation",
                "avg_cycle_hours": "cycle_hours", "washed_kg": "kg"}.get(meas[0] if meas else "", "water_saving")
        rid, r = run("metric_detail", customer=cid, metric=mkey)
        if "error" in r:
            spec["read"] = r["error"]
        else:
            rng = "exact, no assumption" if r["exact"] else f"Low–High {r['low']} to {r['high']} (varies: {r['range_varies']})"
            spec["read"] = f"{r['metric']} for {r['customer']} is {r['value']} ({STATUS_LABEL.get(r['status'], r['status'])}). Formula: {r['formula']}. Range: {rng}. Source tables: {', '.join(r['sources'])}."
            if r.get("caveat"): spec["caveat"] = r["caveat"]
            spec["key_numbers"] = [dict(label=r["metric"], value=r["value"], result_id=rid)] + ([dict(label="Low case", value=r["low"], result_id=rid), dict(label="High case", value=r["high"], result_id=rid)] if not r["exact"] else [])
        spec["follow_ups"] = [f"How fair is the baseline for {nm}?", f"What if {nm}'s own water use is 14 L/kg?", f"Show {nm} water saving by country"]
        return _rules_final(ctx, spec, question, used)

    # ---------------------------------------------------------------- baseline fairness / challenge
    if cid and re.search(r"baseline|fair|challenge|push back|defend|sceptic|skeptic|finance", q):
        rid, r = run("compare_baselines", customer=cid)
        rid2, r2 = run("challenges", customer=cid)
        rows = r["rows"]
        sel = next(x for x in rows if x["selected"])
        spec["read"] = (f"Against the selected baseline ({sel['baseline']}) {nm} saved {big(sel['water_saving_l'], 'L')} of water. Across the three baselines in the data the saving runs from "
                        f"{big(min(x['water_saving_l'] for x in rows), 'L')} to {big(max(x['water_saving_l'] for x in rows), 'L')}; it stays positive for any alternative above "
                        f"{r['lindstrom_water_l_per_kg']} L/kg (Lindström's allocated intensity). Expect questions on: " + "; ".join(c["question"] for c in r2["challenges"][:4]) + ".")
        spec["key_numbers"] = [dict(label=f"Water saved vs {x['baseline']}", value=big(x["water_saving_l"], "L"), result_id=rid) for x in rows] + [dict(label="Lindström allocated water", value=f"{r['lindstrom_water_l_per_kg']} L/kg", result_id=rid)]
        spec["charts"] = [dict(result_id=rid, kind="bar", x="baseline", y=["water_saving_l"], title="Water saved by comparison baseline")]
        spec["hypotheses"] = ["Ask which alternative the customer would really use; their own L/kg turns the estimate into evidence."]
        spec["caveat"] = "Baselines are illustrative pack values; laundry water is allocated by washed kg."
        spec["follow_ups"] = [f"What if {nm}'s own water use is 12 L/kg?", f"How is the water saving calculated for {nm}?", f"What if only 50 % of repairs prevent a purchase at {nm}?"]
        return _rules_final(ctx, spec, question, used)

    # ---------------------------------------------------------------- data quality
    if re.search(r"data quality|how good is the data|trust|valid|issue|error|warning|gap", q):
        rid, r = run("data_issues", customer=cid)
        top = [i for i in r["issues"] if i["severity"] in ("ERROR", "WARNING")]
        spec["read"] = (f"{r['scope']}: {r['counts'].get('ERROR', 0)} error(s), {r['counts'].get('WARNING', 0)} warning(s), {r['counts'].get('INFO', 0)} note(s). "
                        + " ".join(f"{i['severity'].title()}: {i['check']} ({i['where']}). {i['suggested_fix']}" for i in top[:3]))
        spec["key_numbers"] = [dict(label=s.title() + "s", value=str(r["counts"].get(s, 0)), result_id=rid) for s in ("ERROR", "WARNING")]
        spec["follow_ups"] = ["What would firm up next year's review?", f"How is the water saving calculated for {nm}?", "Open the Data tab to change a decision"]
        return _rules_final(ctx, spec, question, used)

    # ---------------------------------------------------------------- hygiene / garment control
    if cid and re.search(r"hygien|stale|not washed|not been washed|garment control|rfid|traceab|missing garment|not returned", q):
        days = int(_num_after(q, [r"(?:threshold|over|more than|than)"]) or 90)
        rid, r = run("stale_garments", customer=cid, days=days)
        if "error" in r:
            spec["read"] = r["error"]
        else:
            spec["read"] = (f"At a {days}-day threshold, {nf(r['over_threshold'])} of {nf(r['garments_with_scans'])} scanned garments at {nm} ({r['over_threshold_pct']} %) had no delivery since then (as of {r['as_of']}). "
                            f"Median time since last delivery is {r['median_days_since_delivery']} days. Most at: " + ", ".join(f"{x['site']} ({x['over_threshold']})" for x in r["rows"][:3]) + ".")
            spec["key_numbers"] = [dict(label=f"Garments over {days} days", value=nf(r["over_threshold"]), result_id=rid), dict(label="Share of scanned garments", value=f"{r['over_threshold_pct']} %", result_id=rid),
                                   dict(label="Median days since delivery", value=str(r["median_days_since_delivery"]), result_id=rid)]
            spec["charts"] = [dict(result_id=rid, kind="barh", x="site", y=["over_threshold"], title=f"Garments with no delivery for > {days} days, by site")]
            spec["hypotheses"] = ["Sparse sample scans overstate stale garments; with real RFID data the count is likely lower. Agree the threshold with the customer's hygiene plan first."]
        spec["follow_ups"] = [f"What if the threshold is 120 days at {nm}?", f"Which sites stand out at {nm}?", f"What should I propose to {nm}?"]
        return _rules_final(ctx, spec, question, used)

    # ---------------------------------------------------------------- opportunities / brainstorm
    if cid and re.search(r"propos|opportun|idea|brainstorm|angle|venture|offer|next year|upsell|grow|meeting|what should i", q):
        rid, r = run("opportunities", customer=cid)
        rid2, r2 = run("industry_context", customer=cid)
        ops = r["opportunities"]
        star = [o for o in ops if o["matches_customer_priority"]]
        spec["read"] = (f"For {nm} ({r2['industry']}; stated priorities: {', '.join(r2['customer_priority_topics'])}) the strongest openings are: "
                        + "; ".join(f"{o['title']} ({o['sizing']})" for o in (star or ops)[:3]) + ".")
        spec["hypotheses"] = [f"{o['title']}: {o['hypothesis']} Ask: {o['confirm_with_customer'][0]}" for o in ops[:4]]
        spec["hypotheses"].append("Industry lens (" + r2["industry"] + "): " + "; ".join(f"{x['theme']}" for x in r2["industry_priorities"]) + ".")
        spec["caveat"] = "Hypotheses for a conversation, sized in units; not revenue claims. Synthetic data."
        spec["follow_ups"] = [f"What if utilisation at {nm} reached the site median?", f"Which sites stand out at {nm}?", f"How fair is the baseline for {nm}?"]
        return _rules_final(ctx, spec, question, used)

    # ---------------------------------------------------------------- flagged sites
    if re.search(r"stand out|flag|attention|outlier|problem|worst|struggl|weak", q) and not group in ("month", "product", "country"):
        rid, r = run("flagged_sites", customer=cid)
        if cid:
            rid2, r2 = run("query", measures=["requests_per_1000_garments", "utilisation_pct", "ontime_pct"], group_by=["site"], filters={"customer": cid}, sort_by="requests_per_1000_garments", top_n=30)
        if not r["sites"]:
            spec["read"] = f"No site stands out at {nm} under the attention rule."
        else:
            spec["read"] = (f"{len(r['sites'])} of {r['sites_checked']} sites stand out at {nm}: " + "; ".join(f"{s['site']} ({s['country']}): {', '.join(s['why'])}" for s in r["sites"][:4])
                            + ". The rule compares each site with the customer's own other sites, so this is a signal to ask about, not a verdict.")
            st["site"] = ctx.sites_in(r["sites"][0]["site"], cid)[0] if cid and ctx.sites_in(r["sites"][0]["site"], cid) else st.get("site")
            spec["key_numbers"] = [dict(label=f"{s['site']}: requests per 1000", value=str(s["requests_per_1000_garments"]), result_id=rid) for s in r["sites"][:3]]
            if cid:
                spec["charts"] = [dict(result_id=rid2, kind="barh", x="site", y=["requests_per_1000_garments"], title=f"Service requests per 1000 garments by site, {nm}")]
            spec["hypotheses"] = ["Typical causes to ask about: a changed contact person, delivery windows that clash with shifts, layout of the garment room, or a new product."]
        first = r["sites"][0]["site"] if r["sites"] else "the first site"
        spec["follow_ups"] = [f"Drill into {first}", f"What if on-time reached 99 % at {nm}?", f"Show the monthly trend of requests at {nm}"]
        return _rules_final(ctx, spec, question, used)

    # ---------------------------------------------------------------- site drill-down
    if sites and (re.search(r"drill|deep dive|tell me about|what about|look at|profile|zoom|why", q) or not group):
        rid, r = run("site_profile", site=ctx.S[ctx.S.site_id == sites[0]].site.iloc[0], customer=cid)
        if "error" in r:
            spec["read"] = r["error"]
        else:
            dv = r["difference_vs_median"]
            spec["read"] = (f"{r['site']} ({r['country']}, {r['customer']}): utilisation {r['utilisation_pct']} % ({_sgn(dv['utilisation_pp'])} pp vs site median), on-time {r['ontime_pct']} % "
                            f"({_sgn(dv['ontime_pp'])} pp), {r['requests_per_1000_garments']} requests per 1000 garments ({_sgn(dv['requests_per_1000'])} vs median). "
                            f"It ranks {r['rank_of_sites']['requests_rank_highest_first']} of {r['rank_of_sites']['n_sites']} sites on request rate. "
                            + (("Flagged because: " + "; ".join(r["why"]) + ".") if r["why"] else "Not flagged."))
            spec["key_numbers"] = [dict(label="Utilisation", value=f"{r['utilisation_pct']} %", result_id=rid), dict(label="On-time", value=f"{r['ontime_pct']} %", result_id=rid),
                                   dict(label="Requests per 1000 garments", value=str(r["requests_per_1000_garments"]), result_id=rid), dict(label="Garments", value=nf(r["garments"]), result_id=rid)]
            rid2, r2 = run("query", measures=["utilisation_pct", "service_requests"], group_by=["month"], filters={"customer": r["customer"], "site": r["site_id"]})
            spec["charts"] = [dict(result_id=rid2, kind="line", x="month", y=["service_requests"], title=f"Service requests per month, {r['site']}")]
            rid3, r3 = run("query", measures=["garments_allocated", "utilisation_pct"], group_by=["product"], filters={"customer": r["customer"], "site": r["site_id"]})
            spec["charts"].append(dict(result_id=rid3, kind="bar", x="product", y=["utilisation_pct"], title=f"Utilisation by product, {r['site']}"))
            spec["hypotheses"] = ["Check whether one product drives the pattern, and whether the timing matches an event at the site (new contract, staff change, layout)."]
        spec["follow_ups"] = [f"What if we exclude this site at {nm}?", f"Compare utilisation by site at {nm}", f"What should I propose to {nm}?"]
        return _rules_final(ctx, spec, question, used)

    # ---------------------------------------------------------------- query (compare / slice / trend)
    if group or meas:
        m = meas or [st.get("measure", "utilisation_pct")]
        g = group or ("site" if cid else "customer")
        if g == "customer":
            filt.pop("customer", None)
        if g == "repair_type":
            m = ["repairs"]
        if g == "month":
            m = [{"requests_per_1000_garments": "service_requests", "repairs_per_100_garments": "repairs"}.get(x, x) for x in m]
        extra = {"utilisation_pct": ["garments_not_scanned"], "requests_per_1000_garments": ["service_requests"], "ontime_pct": ["late_cycles"],
                 "water_saving_l": ["washed_kg"], "repairs_per_100_garments": ["repairs"]}.get(m[0], [])
        ms = list(dict.fromkeys(m + extra))
        asc = m[0] in ("utilisation_pct", "ontime_pct") and g != "month"
        rid, r = run("query", measures=ms, group_by=[g], filters=filt, sort_by=m[0], ascending=asc, top_n=30)
        if "error" in r:
            spec["read"] = r["error"] + (". " + "; ".join(r.get("errors", [])) if r.get("errors") else "")
            return _rules_final(ctx, spec, question, used)
        m0 = r["measures"][0]
        unit = r["units"][m0]
        s = r["summary"].get(m0, {})
        scope = nm if "customer" in filt else "all customers"
        scope_at = f"at {scope}" if "customer" in filt else "across all customers"
        lab = LABEL.get(m0, m0.replace("_", " "))
        if g == "month" and s:
            spec["read"] = (f"{lab.capitalize()} {scope_at}, {r['period']}: {_fmtv(s['first'], unit)} in the first month and {_fmtv(s['last'], unit)} in the last; half-year average "
                            f"{_fmtv(s['first_half_avg'], unit)} → {_fmtv(s['second_half_avg'], unit)}. Lowest {s['min_at']} ({_fmtv(s['min'], unit)}), highest {s['max_at']} ({_fmtv(s['max'], unit)}).")
            spec["charts"] = [dict(result_id=rid, kind="line", x="month", y=[m0], title=f"{lab.capitalize()} by month, {scope}")]
            spec["key_numbers"] = [dict(label="First half average", value=_fmtv(s["first_half_avg"], unit), result_id=rid), dict(label="Second half average", value=_fmtv(s["second_half_avg"], unit), result_id=rid),
                                   dict(label=f"Peak ({s['max_at']})", value=_fmtv(s["max"], unit), result_id=rid)]
            spec["hypotheses"] = ["The pack covers one year, so this shows seasonality and sudden changes, not year-on-year growth."]
        elif s:
            spec["read"] = (f"{lab.capitalize()} by {g.replace('_', ' ')} {scope_at} ({r['period']}): highest {s['max_at']} ({_fmtv(s['max'], unit)}), lowest {s['min_at']} ({_fmtv(s['min'], unit)}), "
                            f"median {_fmtv(s['median'], unit)}" + (f", total {_fmtv(s['total'], unit)}" if "total" in s else "") + f" across {r['total_groups']} {_pl(g)}.")
            spec["charts"] = [dict(result_id=rid, kind="barh" if r["total_groups"] > 6 else "bar", x=g, y=[m0], title=f"{lab.capitalize()} by {g.replace('_', ' ')}, {scope}")]
            spec["key_numbers"] = [dict(label=f"Highest: {s['max_at']}", value=_fmtv(s["max"], unit), result_id=rid), dict(label=f"Lowest: {s['min_at']}", value=_fmtv(s["min"], unit), result_id=rid),
                                   dict(label="Median", value=_fmtv(s["median"], unit), result_id=rid)]
            if g == "customer":
                spec["caveat"] = "Internal view: comparing accounts is for the KAM only. With few accounts this is a side-by-side, not a benchmark."
        else:
            row = r["rows"][0]
            spec["read"] = f"{lab.capitalize()} {scope_at} ({r['period']}): {_fmtv(row[m0], unit)}" + (f" (Low–High {_fmtv(row[m0 + '_low'], unit)} to {_fmtv(row[m0 + '_high'], unit)})" if m0 + "_low" in row else "") + "."
            spec["key_numbers"] = [dict(label=lab, value=_fmtv(row[m0], unit), result_id=rid)]
        if r["status"][m0] != "CALCULATED":
            spec["caveat"] = (spec.get("caveat", "") + f" {STATUS_LABEL[r['status'][m0]]}: {r['definitions'][m0]}." + (f" {r['range_note']}" if r.get("range_note") else "")).strip()
        st["group"] = g
        nxt = {"site": "country", "country": "site", "month": "site", "product": "site", "customer": "site", "quarter": "site", "laundry": "site", "repair_type": "product"}[g]
        spec["follow_ups"] = [f"Same by {nxt}" + (f" at {nm}" if cid else ""), f"Show the monthly trend of {lab}" + (f" at {nm}" if cid else ""), f"Which sites stand out at {nm}?" if cid else "Which sites stand out?"]
        return _rules_final(ctx, spec, question, used)

    # ---------------------------------------------------------------- default: standing snapshot
    rid, r = run("account_snapshot", customer=cid)
    k = {x["key"]: x for x in r["kpis"] if "key" in x}
    if cid:
        spec["read"] = (r["headline"] + ". " + " ".join(x["text"] + "." for x in r["moving"][:2]) + " " + (r["watch"][0]["text"] + "." if r["watch"] else ""))
        spec["key_numbers"] = [dict(label=x["label"], value=x["value"], result_id=rid) for x in r["kpis"][:5]]
        spec["charts"] = [dict(result_id=rid, kind="line", x="month", y=["utilisation_pct"], title="Garment utilisation by month")] if r.get("trend") else []
        spec["hypotheses"] = [f"{t['title']}: {t['sizing']}" for t in r["open_threads"]]
    else:
        spec["read"] = r["headline"] + ". " + " ".join(x["text"] + "." for x in r["moving"])
        spec["key_numbers"] = [dict(label=x["label"], value=x["value"], result_id=rid) for x in r["kpis"]]
    spec["follow_ups"] = [f"Which sites stand out at {nm}?", f"What should I propose to {nm}?", f"How fair is the baseline for {nm}?"] if cid else ["Compare customers on on-time delivery", "Which sites stand out?", "How good is the data?"]
    return _rules_final(ctx, spec, question, used, note=None if (meas or group) else "I read this as a request for the account overview. Ask about a measure, a site, a what-if or opportunities to go deeper.")


def _rules_final(ctx, spec, question, used, note=None):
    ans, bad = finalize(ctx, spec, question, used, "rules")
    if bad:  # should not happen: rules text is built from tool outputs. Keep it visible if it does.
        ans["note"] = f"Check: numbers not traced to a result: {bad[:3]}"
    elif note:
        ans["note"] = note
    return ans


def _fmtv(v, unit):
    if v is None:
        return "n/a"
    if unit == "%":
        return f"{v:.1f} %"
    if unit in ("L", "kWh", "kgCO2e", "kg", "EUR") and abs(v) >= 1e4:
        return big(v, unit)
    if unit in ("per 1000", "per 100", "h", "L/kg", "kWh/kg"):
        return f"{v:g}" + ("" if unit.startswith("per") else f" {unit}")
    return f"{nf(v, 0)} {unit}".strip()


def _sgn(v):
    if v is None:
        return "n/a"
    if abs(v) < 0.05:
        return "±0"
    return f"+{v:g}" if v > 0 else f"{v:g}"


LABEL = {"utilisation_pct": "garment utilisation", "ontime_pct": "on-time cycles", "requests_per_1000_garments": "service requests per 1000 garments",
         "repairs_per_100_garments": "repairs per 100 garments", "water_saving_l": "water saved", "energy_saving_kwh": "energy saved",
         "co2_saving_kg": "service CO2e saved", "washed_kg": "washed kg", "garments_not_scanned": "garments not scanned", "service_requests": "service requests",
         "late_cycles": "late cycles", "avg_cycle_hours": "average cycle time", "purchases_avoided_eur": "purchases avoided (upper bound)",
         "garments_allocated": "garments allocated", "active_wearers": "active wearers", "repairs": "repairs"}
PLURAL = {"country": "countries", "laundry": "laundries", "repair_type": "repair types", "product_group": "product groups", "site_type": "site types"}


def _pl(g):
    return PLURAL.get(g, g.replace("_", " ") + "s")


def _chg(v, unit):
    if v is None:
        return "n/a"
    if unit == "%":
        return f"{v:+.1f} pp"
    return ("+" if v >= 0 else "−") + _fmtv(abs(v), unit)
