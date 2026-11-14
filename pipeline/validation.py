"""Cross-sheet validation. Every issue has: severity, check, table, location, plain explanation,
suggested fix, and (where rows are to blame) the exact source rows so the user can exclude them."""
from __future__ import annotations
import numpy as np
import pandas as pd
from schema import TABLES, status_tokens
from assumptions import THRESH, PLAUSIBLE
import metrics as mt

SEV_ORDER = {"ERROR": 0, "WARNING": 1, "INFO": 2}
FACT = ("service_activity", "repairs", "service_cycles", "impacts")
META = {"_uid", "_sheet", "_row", "value_text"}


class Issues:
    def __init__(self):
        self.rows: list[dict] = []

    def add(self, sev, check, table, location, explanation, fix, uids=None, default="keep", scope=""):
        uids = list(dict.fromkeys(uids or []))
        self.rows.append(dict(severity=sev, check=check, table=table, location=location, explanation=explanation,
                              fix=fix, n_rows=len(uids), uids=uids, default_action=("exclude" if (default == "exclude" and uids) else "keep"),
                              scope=scope))

    def frame(self) -> pd.DataFrame:
        df = pd.DataFrame(self.rows, columns=["severity", "check", "table", "location", "explanation", "fix", "n_rows", "uids", "default_action", "scope"])
        if df.empty:
            df.insert(0, "id", [])
            return df
        df["_o"] = df.severity.map(SEV_ORDER)
        df = df.sort_values(["_o", "table", "check"], kind="stable").drop(columns="_o").reset_index(drop=True)
        df.insert(0, "id", [f"V{i+1:03d}" for i in range(len(df))])
        return df



def _sk(df, cols):
    """Coerce join keys to string so a stray float/NaN key column can never crash a merge."""
    df = df.copy()
    for c in cols:
        if c in df.columns:
            df[c] = df[c].map(lambda x: x if (isinstance(x, str) or x != x) else str(x)).astype(object)
    return df


def _merge(left, right, on, **kw):
    on_l = [on] if isinstance(on, str) else list(on)
    return _sk(left, on_l).merge(_sk(right, on_l), on=on, **kw)

def _sheet(key):
    return key.split("::")[-1]


def _where(df, mask, n=4):
    sub = df[mask]
    parts = []
    for sh, g in sub.groupby("_sheet"):
        rows = sorted(g._row.tolist())
        parts.append(f"{_sheet(sh)} row{'s' if len(rows) > 1 else ''} {', '.join(map(str, rows[:n]))}" + (f" (+{len(rows)-n} more)" if len(rows) > n else ""))
    return "; ".join(parts)


def _uids(df, mask):
    return df.loc[mask, "_uid"].tolist()


def _short(vals, n=6):
    vals = [str(v) for v in vals]
    return ", ".join(vals[:n]) + (f" (+{len(vals)-n} more)" if len(vals) > n else "")


def _has(df, col):
    return df is not None and col in df and df[col].notna().any()


def _cal(months):
    if not len(months):
        return []
    return [str(p) for p in pd.period_range(min(months), max(months), freq="M")]


# =================================================================================== checks
def check_structure(T, mapping, raw, presence, I):
    used = {sm.table for sm in mapping.values() if sm.include and sm.table}
    for tname in ("sites", "service_activity"):
        if tname not in T:
            I.add("ERROR", "missing required sheet", tname, "no sheet recognised",
                  f"No uploaded sheet was recognised as '{TABLES[tname].label}', which every calculation needs.",
                  "Upload it, or assign one of the uploaded sheets to this table in the mapping step.")
    consequences = {
        "resources": "Water, energy, emissions and waste metrics cannot be calculated.",
        "baselines": "Comparison with a baseline (water/energy/emissions saved) cannot be calculated; no default factors are invented.",
        "repairs": "Repair, replacements-postponed and avoided-purchase metrics cannot be calculated.",
        "service_cycles": "On-time and turnaround KPIs cannot be calculated.",
        "products": "Purchases avoided (EUR) and the kg-per-piece check are unavailable.",
        "waste": "Textile waste and recycling metrics are unavailable.",
        "customers": "Customer name and industry are unknown, so industry-aware priorities fall back to generic defaults.",
    }
    for tname, msg in consequences.items():
        if tname not in used:
            I.add("WARNING", "missing optional sheet", tname, "no sheet recognised", f"No sheet for '{TABLES[tname].label}'. {msg}",
                  "Upload it if you have it; otherwise accept the reduced view.")
    for key, sm in mapping.items():
        if not (sm.include and sm.table):
            continue
        t = TABLES[sm.table]
        sh = _sheet(key)
        miss_req = [f.name for f in t.fields if f.required and not sm.cols.get(f.name)]
        if miss_req:
            I.add("ERROR", "missing required column", sm.table, f"{sh}: {', '.join(miss_req)}",
                  f"Required column(s) {', '.join(miss_req)} were not found in sheet '{sh}', so this sheet cannot be used reliably.",
                  "Map the right source column in the mapping step, or exclude the sheet.", scope=sh)
        feeds = [(f.name, f.feeds) for f in t.fields if not f.required and f.feeds and not sm.cols.get(f.name)]
        if feeds:
            I.add("WARNING", "missing optional column", sm.table, f"{sh}: {', '.join(n for n, _ in feeds)}",
                  f"Optional column(s) not found in '{sh}'; this disables: {'; '.join(sorted({f for _, f in feeds}))}.",
                  "Map the column if it exists under another name, or provide it.", scope=sh)
        low = [(f, c) for f, c in sm.conf.items() if sm.cols.get(f) and c < 0.75]
        if low:
            I.add("INFO", "low-confidence mapping", sm.table, f"{sh}: " + ", ".join(f"{f}←'{sm.cols[f]}'" for f, _ in low),
                  "These columns were matched by approximate name; please confirm they mean what the internal field means.",
                  "Check in the mapping step and correct if needed.", scope=sh)
        conv = [(f, sm.factor[f], sm.why[f]) for f in sm.factor if sm.factor[f] != 1.0]
        if conv:
            I.add("INFO", "unit conversion applied", sm.table, f"{sh}: " + ", ".join(f"{f} ×{x:g}" for f, x, _ in conv),
                  "; ".join(f"{f}: {w}" for f, _, w in conv), "Confirm the conversion in the mapping step (editable factor).", scope=sh)


def check_load(load_issues, I):
    names = {"non_numeric": ("non-numeric value", "contains text where a number is required"),
             "bad_month": ("unreadable month", "cannot be read as a month (expected e.g. 2025-03)"),
             "bad_ts": ("unreadable timestamp", "cannot be read as a date/time")}
    for li in load_issues:
        chk, what = names[li["kind"]]
        sh = _sheet(li["sheet"])
        rows = sorted(int(u.split("#")[-1]) for u in li["uids"])
        I.add("ERROR", chk, li["table"], f"{sh} row{'s' if len(rows) > 1 else ''} {_short(rows, 5)}, column {li['field']}",
              f"{len(rows)} cell(s) in '{li['field']}' {what}, e.g. {_short(li['examples'], 3)}. They cannot be used in any calculation.",
              "Correct the cell in the source file, or exclude these rows.", li["uids"], "exclude", scope=sh)


def check_duplicates(T, I):
    for tname, df in T.items():
        t = TABLES[tname]
        key = [k for k in t.key if _has(df, k)]
        if tname == "service_cycles" and not _has(df, "cycle_number"):
            key = [k for k in ("asset_id", "pickup_timestamp") if _has(df, k)]
        if not key or tname in ("reference_totals",):
            continue
        dup_all = df.duplicated(key, keep=False)
        if not dup_all.any():
            continue
        content = [c for c in df.columns if c not in META and c not in key]
        later = df.duplicated(key, keep="first")
        exact = df.duplicated(key + content, keep="first") if content else later
        conflict = later & ~exact
        if exact.any():
            I.add("ERROR", "exact duplicate rows", tname, _where(df, exact),
                  f"{int(exact.sum())} row(s) repeat an earlier row exactly (same {', '.join(key)} and identical values). Totals would be double-counted.",
                  "Remove the repeated rows (the first occurrence is kept).", _uids(df, exact), "exclude",
                  scope=_short(sorted(df[exact].get('site_id', df[exact][key[0]]).astype(str).unique()), 6))
        if conflict.any():
            I.add("ERROR", "conflicting duplicate keys", tname, _where(df, conflict),
                  f"{int(conflict.sum())} row(s) share {', '.join(key)} with an earlier row but carry different values; one of them is wrong.",
                  "Decide which row is right in the source file. By default the later row is excluded and the first kept.",
                  _uids(df, conflict), "exclude", scope=_short(sorted(df[conflict][key[0]].astype(str).unique()), 6))


def check_blanks(T, I):
    for tname, df in T.items():
        if tname in ("reference_totals", "assumptions", "industry_priorities"):
            continue
        for f in TABLES[tname].fields:
            if not f.required or f.name not in df or not df[f.name].notna().any():
                continue
            b = df[f.name].isna()
            if b.any():
                I.add("ERROR", "blank required value", tname, f"{_where(df, b)}; column {f.name}",
                      f"{int(b.sum())} row(s) have no value in required column '{f.name}' (empty, or text such as n/a that spreadsheets read as empty). They cannot be placed or summed.",
                      "Fill the value in the source file, or exclude these rows.", _uids(df, b), "exclude")


def check_values(T, I):
    for tname, df in T.items():
        t = TABLES[tname]
        for f in t.fields:
            if f.kind != "num" or not _has(df, f.name):
                continue
            s = df[f.name]
            if f.nonneg:
                neg = s < 0
                if neg.any():
                    I.add("ERROR", "negative value", tname, f"{_where(df, neg)}; column {f.name}",
                          f"{int(neg.sum())} negative value(s) in '{f.name}' (min {s.min():g}); this quantity cannot be negative.",
                          "Correct the source value, or exclude these rows.", _uids(df, neg), "exclude")
            if f.hi is not None:
                over = s > f.hi
                if over.any():
                    sev = "ERROR" if f.name != "washing_pct" else "WARNING"
                    I.add(sev, "value above limit", tname, f"{_where(df, over)}; column {f.name}",
                          f"{int(over.sum())} value(s) in '{f.name}' exceed {f.hi:g} (max {s.max():g}). "
                          + ("A percentage cannot exceed 100; check whether the column holds fractions or another unit." if f.dim == "pct" and f.hi == 100 else
                             "A share cannot exceed 1 (100 %); check units." if f.hi == 1 else "Implausibly high; check units."),
                          "Correct or exclude the rows; if the whole column is in another unit, set the conversion factor in the mapping.",
                          _uids(df, over), "exclude")
    A = T.get("service_activity")
    if A is not None and _has(A, "active_assets_scanned") and _has(A, "allocated_pieces"):
        m = A.active_assets_scanned > A.allocated_pieces * THRESH["scanned_over_allocated"]
        if m.any():
            I.add("WARNING", "scanned exceeds allocated", "service_activity", _where(A, m),
                  f"{int(m.sum())} row(s) show more scanned garments than allocated garments (>{THRESH['scanned_over_allocated']-1:.0%} over). Garment utilisation would exceed 100 %.",
                  "Check allocation vs scan definitions or exclude the rows.", _uids(A, m), "keep")
    if A is not None and _has(A, "active_wearers") and _has(A, "allocated_pieces"):
        m = A.active_wearers > A.allocated_pieces
        if m.mean() > 0.05:
            I.add("INFO", "wearers exceed allocated garments", "service_activity", f"{int(m.sum())} of {len(A)} rows ({m.mean():.0%})",
                  "Many rows report more active wearers than allocated garments. Garments are probably shared between wearers, or wearers are counted per product.",
                  "Agree a wearer definition with Lindström; report at site/group level only (no named individuals).")
    if A is not None and _has(A, "customer_washed_kg") and _has(A, "washed_pieces"):
        kgp = A.customer_washed_kg / A.washed_pieces.replace(0, np.nan)
        lo, hi = PLAUSIBLE["kg_per_piece"]
        bad = (kgp < lo) | (kgp > hi)
        if bad.mean() > 0.02:
            I.add("WARNING", "implausible kg per piece", "service_activity", _where(A, bad),
                  f"{int(bad.sum())} rows imply {kgp[bad].median():.3g} kg per washed piece (plausible {lo}–{hi}). kg or piece counts may be in the wrong unit.",
                  "Check the kg unit (tonnes? grams?) or the piece counts.", _uids(A, bad))
    R = T.get("repairs")
    if A is not None and R is not None and not A.empty and not R.empty and _has(R, "repair_count") and _has(A, "allocated_pieces") and _has(R, "product_id"):
        pieces = A.groupby(["customer_id", "product_id", "month"]).allocated_pieces.sum().groupby(["customer_id", "product_id"]).mean()
        rate = (R.groupby(["customer_id", "product_id"]).repair_count.sum() / pieces).dropna()
        hi = rate[rate > THRESH["repairs_per_piece_max"]]
        if len(hi):
            P = T.get("products")
            nm = P.set_index("product_id").product_name if P is not None and not P.empty and _has(P, "product_name") else {}
            ex = "; ".join(f"{c}/{nm.get(p, p) if hasattr(nm, 'get') else p}: {v:.1f}" for (c, p), v in hi.sort_values(ascending=False).head(4).items())
            I.add("WARNING", "implausible repair rate", "repairs", f"{len(hi)} customer-product(s): {ex}",
                  f"{len(hi)} customer-product combination(s) show more than {THRESH['repairs_per_piece_max']:g} repairs per allocated garment per year (e.g. {ex}). "
                  "A garment repaired that often is unusual; repair lines may be counted per defect or the allocation may be understated. Repair-based figures (postponed replacements, avoided purchases) inherit this uncertainty.",
                  "Check with the data owner what one repair row counts, and whether allocated pieces cover all garments in use.", scope=_short([c for c, _ in hi.index], 6))
    C = T.get("service_cycles")
    if C is not None and not C.empty:
        ts = ["pickup_timestamp", "in_laundry_timestamp", "out_laundry_timestamp", "delivered_timestamp"]
        pres = [c for c in ts if _has(C, c)]
        bad = pd.Series(False, index=C.index)
        for a, b in zip(pres, pres[1:]):
            bad |= (C[a] > C[b])
        if bad.any():
            I.add("ERROR", "timestamps out of order", "service_cycles", _where(C, bad),
                  f"{int(bad.sum())} cycle(s) have scan timestamps in impossible order (pickup → in laundry → out of laundry → delivered).",
                  "Fix the scans in the source or exclude these cycles.", _uids(C, bad), "exclude")
        if _has(C, "cycle_hours") and _has(C, "pickup_timestamp") and _has(C, "delivered_timestamp"):
            d = ((C.delivered_timestamp - C.pickup_timestamp).dt.total_seconds() / 3600 - C.cycle_hours).abs() > THRESH["cycle_hours_tol"]
            if d.any():
                I.add("WARNING", "cycle hours disagree with timestamps", "service_cycles", _where(C, d),
                      f"{int(d.sum())} row(s): cycle_hours differs by more than {THRESH['cycle_hours_tol']:g} h from delivered − pickup. Hours may be in another unit.",
                      "Check the unit of cycle_hours (minutes? days?).", _uids(C, d))
    Rs = T.get("resources")
    if Rs is not None and not Rs.empty:
        for col, lo_hi, nm in (("fresh_water_l_per_kg", PLAUSIBLE["fresh_water_l_per_kg"], "litres per kg"), ("energy_kwh_per_kg", PLAUSIBLE["energy_kwh_per_kg"], "kWh per kg")):
            if _has(Rs, col):
                s = Rs[col]
                bad = (s < lo_hi[0]) | (s > lo_hi[1])
                if bad.any():
                    frac = bad.mean()
                    I.add("ERROR" if frac > THRESH["unit_majority"] else "WARNING", "implausible intensity (wrong unit?)", "resources", _where(Rs, bad),
                          f"{int(bad.sum())} of {len(Rs)} rows have {nm} outside {lo_hi[0]}–{lo_hi[1]} (median {s.median():.3g}). "
                          + ("Most rows are off, which points to a unit problem (e.g. m³ instead of litres, MWh instead of kWh)." if frac > THRESH["unit_majority"] else "Possible typo or unit slip."),
                          "Set the unit conversion factor in the mapping, or correct/exclude the rows.", _uids(Rs, bad), "keep" if frac > THRESH["unit_majority"] else "exclude")
        for tot, per, nm in (("fresh_water_l", "fresh_water_l_per_kg", "water"), ("process_energy_kwh", "energy_kwh_per_kg", "energy")):
            if _has(Rs, tot) and _has(Rs, per) and _has(Rs, "washed_kg"):
                d = (Rs[tot] / Rs.washed_kg.replace(0, np.nan) - Rs[per]).abs() / Rs[per].replace(0, np.nan) > THRESH["intensity_tol"] * 5
                if d.any():
                    I.add("WARNING", f"{nm} total and per-kg disagree", "resources", _where(Rs, d),
                          f"{int(d.sum())} row(s): {tot} ÷ washed_kg does not equal {per} (>{THRESH['intensity_tol']*5:.0%} apart). Metrics use the per-kg value.",
                          "Check units or the washed_kg of that laundry-month.", _uids(Rs, d))
    W = T.get("waste")
    if W is not None and not W.empty and _has(W, "textile_waste_total_kg"):
        routes = W[["recycling_kg", "reuse_kg", "energy_recovery_kg", "incineration_kg"]].sum(axis=1, min_count=1)
        d = ((routes - W.textile_waste_total_kg).abs() / W.textile_waste_total_kg.replace(0, np.nan)) > THRESH["waste_sum_tol"]
        if d.any():
            I.add("WARNING", "waste routes do not sum to total", "waste", _where(W, d),
                  f"{int(d.sum())} row(s): recycling + reuse + energy recovery + incineration differs from textile_waste_total_kg by more than {THRESH['waste_sum_tol']:.0%}.",
                  "Check treatment routes or the total.", _uids(W, d))
    B = T.get("baselines")
    if B is not None and not B.empty:
        for col, key in (("water_l_per_kg", "water_l_per_kg"), ("energy_kwh_per_kg", "energy_kwh_per_kg")):
            if _has(B, col):
                lo, hi = PLAUSIBLE[key]
                bad = (B[col] < lo) | (B[col] > hi)
                if bad.any():
                    I.add("WARNING", "implausible baseline value", "baselines", _where(B, bad),
                          f"Baseline {col} outside {lo}–{hi}: likely a unit problem.", "Check baseline units.", _uids(B, bad))


def check_months(T, I):
    A = T.get("service_activity")
    if A is None or A.empty or not _has(A, "month"):
        return
    cal = _cal(sorted(A.month.dropna().unique()))
    present = set(A.month.dropna())
    gaps = [m for m in cal if m not in present]
    if gaps:
        I.add("WARNING", "calendar gap in service activity", "service_activity", f"months {_short(gaps)}",
              f"No service-activity rows at all for {len(gaps)} month(s) inside the reporting range. Totals and trends understate those months.",
              "Provide the missing months or restrict the reporting period.")

    def per_entity(df, ent, tname, label):
        if df is None or df.empty or not _has(df, "month") or ent not in df:
            return
        miss = {}
        for e, g in df.dropna(subset=[ent]).groupby(ent):
            ms = set(g.month.dropna())
            m = [x for x in cal if x not in ms]
            if m and ms:
                miss[e] = m
        if miss:
            ex = "; ".join(f"{e}: {_short(m, 3)}" for e, m in list(miss.items())[:4])
            I.add("WARNING", "missing months", tname, f"{len(miss)} {label}(s): {ex}",
                  f"{len(miss)} {label}(s) lack rows for some months in the range {cal[0]}–{cal[-1]}. Their totals are understated and year-on-year comparison is unreliable.",
                  "Provide the missing months, or exclude the incomplete entities from comparisons.", scope=_short(list(miss), 8))
    per_entity(A, "site_id", "service_activity", "site")
    per_entity(T.get("repairs"), "site_id", "repairs", "site")
    per_entity(T.get("resources"), "laundry_id", "resources", "laundry")
    per_entity(T.get("waste"), "laundry_id", "waste", "laundry")
    Rs = T.get("resources")
    if Rs is not None and not Rs.empty and _has(A, "laundry_id"):
        k = _merge(A[["month", "laundry_id"]].dropna().drop_duplicates(), Rs[["month", "laundry_id"]].drop_duplicates(), on=["month", "laundry_id"], how="left", indicator=True)
        un = k[k._merge == "left_only"]
        if len(un):
            I.add("WARNING", "activity without laundry resource data", "resources", f"{len(un)} laundry-month(s): " + _short(sorted(f"{r.laundry_id} {r.month}" for r in un.itertuples()), 4),
                  "Customer washed kg exists for these laundry-months but the laundry resource sheet has no row, so water/energy/emissions cannot be allocated for them.",
                  "Provide the missing laundry-month data; the app excludes unmatched kg from allocated metrics and reports the coverage.")


def check_membership(T, I):
    S, C = T.get("sites"), T.get("customers")
    sites = set(S.site_id.dropna()) if S is not None and not S.empty else None
    if sites is not None:
        for fname in FACT:
            df = T.get(fname)
            if df is None or df.empty or not _has(df, "site_id"):
                continue
            orphan = ~df.site_id.isin(sites) & df.site_id.notna()
            if orphan.any():
                ids = sorted(df[orphan].site_id.unique())
                I.add("ERROR", "site missing from site master", fname, f"{_short(ids)}; {_where(df, orphan)}",
                      f"{len(ids)} site(s) ({_short(ids, 4)}) appear in '{TABLES[fname].label}' but not in the Sites sheet. {int(orphan.sum())} row(s) cannot be assigned to a customer.",
                      "Add the site(s) to the Sites sheet, or exclude these rows.", _uids(df, orphan), "exclude", scope=_short(ids, 8))
            have = set(df.site_id.dropna())
            absent = sorted(sites - have)
            if absent and fname != "impacts":
                I.add("WARNING", "site has no rows in sheet", fname, f"{_short(absent)}",
                      f"{len(absent)} site(s) in the Sites sheet ({_short(absent, 4)}) have no rows in '{TABLES[fname].label}'. They will show zero/blank there, which can be misread as 'no activity'.",
                      "Add the missing rows, or confirm the sites really had none.", scope=_short(absent, 8))
        hier = {}
        for fname in FACT:
            df = T.get(fname)
            if df is None or df.empty or not _has(df, "customer_id"):
                continue
            m = _merge(df, S[["site_id", "customer_id"]].drop_duplicates("site_id"), on="site_id", how="inner", suffixes=("", "_site"))
            bad = m.customer_id.notna() & (m.customer_id != m.customer_id_site)
            if bad.any():
                I.add("ERROR", "customer hierarchy conflict", fname, f"{_where(m, bad)}",
                      f"{int(bad.sum())} row(s) name a different customer than the Sites sheet does for the same site.",
                      "Fix the customer/site assignment in the source, or exclude the rows.", _uids(m, bad), "exclude")
    if C is not None and not C.empty:
        cust = set(C.customer_id.dropna())
        for fname in ("sites", *FACT):
            df = T.get(fname)
            if df is None or df.empty or not _has(df, "customer_id"):
                continue
            unk = ~df.customer_id.isin(cust) & df.customer_id.notna()
            if unk.any():
                ids = sorted(df[unk].customer_id.unique())
                I.add("ERROR", "customer missing from customer master", fname, f"{_short(ids)}; {_where(df, unk)}",
                      f"Customer(s) {_short(ids, 4)} appear in '{TABLES[fname].label}' but not in the Customers sheet.",
                      "Add to the Customers sheet, or exclude the rows.", _uids(df, unk), "exclude")
    for fname, fld, master in (("service_activity", "laundry_id", "resources"), ("service_activity", "product_id", "products"), ("repairs", "product_id", "products")):
        df, m = T.get(fname), T.get(master)
        if df is None or m is None or df.empty or m.empty or not _has(df, fld) or not _has(m, fld):
            continue
        unk = ~df[fld].isin(set(m[fld].dropna())) & df[fld].notna()
        if unk.any():
            ids = sorted(df[unk][fld].unique())
            I.add("WARNING", f"{fld} not in {master}", fname, f"{_short(ids)}; {_where(df, unk)}",
                  f"{len(ids)} {fld} value(s) ({_short(ids, 4)}) in '{TABLES[fname].label}' have no match in '{TABLES[master].label}'. Metrics needing that lookup skip these rows.",
                  f"Add them to '{TABLES[master].label}'.", _uids(df, unk))


def check_totals(T, I):
    A, Imp, Rs = T.get("service_activity"), T.get("impacts"), T.get("resources")
    key = ["month", "site_id", "product_id", "laundry_id"]
    if A is not None and Imp is not None and not A.empty and not Imp.empty and _has(A, "customer_washed_kg") and _has(Imp, "customer_washed_kg"):
        k = [c for c in key if _has(A, c) and _has(Imp, c)]
        a = A.groupby(k, dropna=False).agg(kg=("customer_washed_kg", "sum"), uid=("_uid", list)).reset_index()
        b = Imp.groupby(k, dropna=False).agg(kg_i=("customer_washed_kg", "sum")).reset_index()
        j = _merge(a, b, on=k, how="outer", indicator=True)
        both = j[j._merge == "both"].copy()
        both["d"] = both.kg - both.kg_i
        bad = both[(both.d.abs() > THRESH["abs_tol_kg"]) & (both.d.abs() / both.kg_i.abs().replace(0, np.nan) > THRESH["rel_tol"])]
        only_a, only_b = j[j._merge == "left_only"], j[j._merge == "right_only"]
        if len(bad) or len(only_a) or len(only_b):
            tot = (A.customer_washed_kg.sum(), Imp.customer_washed_kg.sum())
            ex = "; ".join(f"{r.site_id} {r.month}: activity {r.kg:,.0f} vs impacts {r.kg_i:,.0f} kg" for r in bad.sort_values("d", key=abs, ascending=False).head(3).itertuples())
            I.add("ERROR", "washed kg differs between sheets", "service_activity vs impacts", ex or "row sets differ",
                  f"Total washed kg is {tot[0]:,.0f} in Service activity but {tot[1]:,.0f} in Customer impacts ({(tot[0]-tot[1])/tot[1]:+.1%}). {len(bad)} site-product-month key(s) disagree, {len(only_a)} exist only in activity, {len(only_b)} only in impacts. "
                  "Calculations use Service activity; the impacts sheet is a cross-check only.",
                  "Find out which sheet is right and correct the other. To drop the activity rows that disagree, choose 'Exclude rows'.",
                  [u for us in bad.uid for u in us], "keep", scope=_short(sorted(bad.site_id.astype(str).unique()), 8))
    if A is not None and Rs is not None and not A.empty and not Rs.empty and _has(A, "laundry_id") and _has(Rs, "washed_kg"):
        a = _merge(A.groupby(["month", "laundry_id"]).customer_washed_kg.sum().reset_index(), Rs.groupby(["month", "laundry_id"]).washed_kg.sum().reset_index(), on=["month", "laundry_id"])
        a["share"] = a.customer_washed_kg / a.washed_kg.replace(0, np.nan)
        over = a[a.share > 1.0 + THRESH["rel_tol"]]
        if len(over):
            lg = over.groupby("laundry_id").share.agg(["count", "min", "max"])
            ex = "; ".join(f"{i}: {int(r['count'])} month(s), customer kg = {r['min']:.1f}–{r['max']:.1f}× the laundry's total" for i, r in lg.iterrows())
            I.add("ERROR", "customer kg exceeds laundry total kg", "service_activity vs resources", ex,
                  f"For {len(over)} laundry-month(s) customers' washed kg is larger than the laundry's own washed kg ({ex}). A share above 100 % is impossible, so one of the two volumes is wrong (a unit slip of ~10× is typical). "
                  "Allocated metrics use per-kg intensities, which do not depend on these absolute volumes, but the laundry figures should be verified.",
                  "Verify the laundry washed_kg (and units) for the listed laundries with the data owner. Metrics are kept by default.",
                  uids=_uids(A, pd.MultiIndex.from_frame(A[["month", "laundry_id"]]).isin(list(zip(over.month, over.laundry_id)))),
                  scope=_short(sorted(lg.index), 8))
    R = T.get("repairs")
    if R is not None and not R.empty and _has(R, "repair_count") and _has(R, "estimated_replacements_postponed"):
        d = (R.repair_count - R.estimated_replacements_postponed).abs() > 0.5
        if d.any():
            I.add("WARNING", "repairs vs postponed replacements", "repairs", _where(R, d),
                  f"{int(d.sum())} row(s) where estimated_replacements_postponed ≠ repair_count (total {R.repair_count.sum():,.0f} vs {R.estimated_replacements_postponed.sum():,.0f}). "
                  "The app derives postponed replacements from repair_count × factor, not from this column.",
                  "Check the assumption behind the column (pack assumption A002: 1:1).", _uids(R, d))
    if Imp is not None and not Imp.empty and A is not None and Rs is not None:
        RI = mt._intensities(T)
        if RI is not None and _has(Imp, "allocated_water_l"):
            j = _merge(Imp, RI[["month", "laundry_id", "water"]], on=["month", "laundry_id"], how="left")
            exp = j.customer_washed_kg * j.water
            d = (j.allocated_water_l - exp).abs() / exp.replace(0, np.nan) > 0.01
            if d.any():
                I.add("WARNING", "allocated water differs from recalculation", "impacts", _where(j, d),
                      f"{int(d.sum())} row(s) of the pre-calculated allocated water differ >1 % from customer kg × laundry L/kg. The app recomputes allocations itself.",
                      "Check the allocation method in the source.", _uids(j, d))
    check_reference(T, I)


REF_KEYS = [("delivery sites", "sites"), ("active wearers", "wearers"), ("garments allocated", "pieces"), ("washed kg", "kg"),
            ("replacements postponed", "postponed"), ("repairs", "repairs"), ("water saving", "water_saving"),
            ("emission", "co2_service"), ("textile waste", "waste"), ("service requests", "requests")]


def check_reference(T, I):
    Ref = T.get("reference_totals")
    if Ref is None or Ref.empty or T.get("service_activity") is None:
        return
    cust = None
    yr = None
    C = T.get("customers")
    for r in Ref.itertuples():
        m = str(r.metric).lower()
        if m.strip() == "customer" and C is not None:
            hit = C[C.customer_name.astype(str).str.lower() == str(getattr(r, "value_text", "")).lower()]
            cust = hit.iloc[0].customer_id if len(hit) else None
        if "year" in m and pd.notna(r.value):
            yr = int(r.value)
    if cust is None:
        I.add("INFO", "control totals not reconciled", "reference_totals", "customer not identified",
              "A control-total sheet was found but no 'Customer' row matching the Customers sheet, so totals could not be reconciled.", "Add a Customer row with the exact customer name.")
        return
    calc = mt.quick_totals(T, cust, yr)
    ok, bad, lines = 0, [], []
    for r in Ref.itertuples():
        m = str(r.metric).lower()
        key = next((v for k, v in REF_KEYS if k in m), None)
        if key is None or pd.isna(r.value) or m.strip() in ("customer", "reporting year"):
            continue
        if key not in calc:
            lines.append(f"{r.metric}: cannot be calculated from the uploaded data")
            continue
        rel = abs(calc[key] - r.value) / max(abs(r.value), 1e-9)
        if rel > THRESH["ref_rel_tol"]:
            bad.append(f"{r.metric}: sheet says {r.value:,.1f}, calculated {calc[key]:,.1f} ({(calc[key]-r.value)/r.value:+.1%})")
        else:
            ok += 1
    if bad:
        I.add("ERROR", "control total does not match calculation", "reference_totals", "; ".join(bad[:4]),
              f"{len(bad)} control total(s) in the reference sheet disagree with the totals calculated from the detailed sheets by more than {THRESH['ref_rel_tol']:.0%}: {'; '.join(bad)}.",
              "Find which side is wrong (detail rows changed or deleted, or the control total is stale) and correct it.", default="keep")
    if ok:
        I.add("INFO", "control totals reconcile", "reference_totals", f"{ok} control total(s)",
              f"{ok} control total(s) reconcile with the calculated totals within {THRESH['ref_rel_tol']:.0%}." + (f" Not checkable: {'; '.join(lines)}." if lines else ""), "No action.")


def check_status(T, mapping, I):
    DERIVED = {"impacts": {"ALLOCATED", "ESTIMATED", "CALCULATED"}}
    cats_by = {}
    for tname, df in T.items():
        if tname in ("reference_totals", "assumptions", "industry_priorities"):
            continue
        t = TABLES[tname]
        if "data_status" not in df or df.data_status.isna().all():
            I.add("WARNING", "no status label", tname, f"all {len(df)} rows",
                  f"'{t.label}' has no data_status (measured / estimated / synthetic) values. Outputs from it are shown as UNLABELLED and cannot be classed.",
                  "Add a data_status column, or confirm the status for the whole sheet.")
            continue
        blank = df.data_status.isna()
        if blank.any():
            I.add("WARNING", "blank status label", tname, _where(df, blank),
                  f"{int(blank.sum())} row(s) have no status label while others do; the sheet mixes labelled and unlabelled data.", "Fill the status or exclude these rows.", _uids(df, blank))
        vals = df.data_status.dropna().astype(str)
        unk = {}
        for v in vals.unique():
            rec, u = status_tokens(v)
            if not rec:
                unk[v] = u
        if unk:
            I.add("WARNING", "unrecognised status label", tname, _short(unk, 4),
                  f"Status label(s) {_short(unk, 4)} are not one of measured / calculated / allocated / estimated / synthetic / public reference.", "Use the standard vocabulary.")
        norm = {}
        for v in vals.unique():
            norm.setdefault("".join(ch for ch in v.lower() if ch.isalnum()), []).append(v)
        spell = [v for v in norm.values() if len(v) > 1]
        if spell:
            I.add("WARNING", "inconsistent status spelling", tname, _short(sum(spell, []), 6),
                  "The same status is written in different ways (case/spacing).", "Use one spelling.")
        cats = set().union(*[status_tokens(v)[0] for v in vals.unique()])
        cats_by[tname] = cats
        if tname in DERIVED and cats and not (cats & DERIVED[tname]):
            I.add("WARNING", "status inconsistent with content", tname, _short(sorted(cats)),
                  f"'{t.label}' is a derived/allocated sheet but is labelled {'/'.join(sorted(cats))}.", "Label derived values as calculated, allocated or estimated.")
        if tname == "repairs" and _has(df, "estimated_avoided_product_kgco2e") and cats == {"MEASURED"}:
            I.add("WARNING", "status inconsistent with content", tname, "MEASURED",
                  "Repairs contains estimated avoided-emission columns but is labelled MEASURED only.", "Label estimated columns as estimated.")
    allc = set().union(*cats_by.values()) if cats_by else set()
    if "MEASURED" in allc and "SYNTHETIC" in allc:
        a = sorted(t for t, c in cats_by.items() if "MEASURED" in c)
        b = sorted(t for t, c in cats_by.items() if "SYNTHETIC" in c)
        I.add("WARNING", "mixed measured and synthetic data", "all", f"measured: {_short(a)}; synthetic: {_short(b)}",
              "The dataset mixes MEASURED and SYNTHETIC sheets. Combined outputs must not be presented as measured customer performance.",
              "Keep the status badge on every number; report synthetic parts separately.")


def validate(T, load_issues, mapping, raw, presence) -> pd.DataFrame:
    I = Issues()
    check_structure(T, mapping, raw, presence, I)
    check_load(load_issues, I)
    check_blanks(T, I)
    check_duplicates(T, I)
    check_values(T, I)
    check_months(T, I)
    check_membership(T, I)
    check_totals(T, I)
    check_status(T, mapping, I)
    return I.frame()


# =================================================================================== correct and continue
def apply_exclusions(T, issues: pd.DataFrame, actions: dict, extra_uids: dict | None = None, reasons: dict | None = None):
    """actions: issue id -> 'exclude' | 'keep'.  extra_uids: uid -> reason (manual exclusions).
    Returns (clean tables, exclusion log). Referential cascade: facts whose site disappeared are dropped too."""
    reason = {}
    for _, r in issues.iterrows():
        if actions.get(r.id, r.default_action) == "exclude":
            for u in r.uids:
                reason.setdefault(u, f"{r.id} {r.check}")
    for u, why in (extra_uids or {}).items():
        reason.setdefault(u, why)
    T2, log = {}, []
    for n, df in T.items():
        hit = df._uid.isin(reason)
        for u, sh, rw in df.loc[hit, ["_uid", "_sheet", "_row"]].itertuples(index=False, name=None):
            log.append(dict(table=n, sheet=_sheet(sh), row=rw, reason=reason[u], source=sh))
        T2[n] = df[~hit].reset_index(drop=True)
    S = T2.get("sites")
    if S is not None:
        sites = set(S.site_id)
        for n in FACT:
            df = T2.get(n)
            if df is None or df.empty or "site_id" not in df:
                continue
            orphan = df.site_id.notna() & ~df.site_id.isin(sites)
            for sh, rw in df.loc[orphan, ["_sheet", "_row"]].itertuples(index=False, name=None):
                log.append(dict(table=n, sheet=_sheet(sh), row=rw, reason="site no longer in Sites sheet after exclusions", source=sh))
            T2[n] = df[~orphan].reset_index(drop=True)
    return T2, pd.DataFrame(log, columns=["table", "sheet", "row", "reason", "source"])
