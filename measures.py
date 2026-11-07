"""Pre-computed KPIs for the master pack (and the Simple-mode summary).
One vectorised pass over the clean tables, grouped at any level (customer/site/month, customer/month, site, customer).
It reuses the app's own laundry intensities (metrics._intensities) and the default baseline, so every figure reconciles
with the app's metric engine (tests/test_master_pack.py checks this). No LLM, only pandas arithmetic."""
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
import pandas as pd
import metrics as mt

# ----------------------------------------------------------------------------------------------------------
# Utilisation band: default, industry hint, per-customer override. All values are recorded in the output.
DEFAULT_BAND = (30.0, 70.0)
HIGHER_RUN_INDUSTRIES = ("food", "beverage", "hygiene", "pharma", "cleanroom", "health")
HIGHER_RUN_BAND = (40.0, 80.0)


@dataclass
class Bands:
    default: tuple = DEFAULT_BAND
    industry_aware: bool = True
    overrides: dict = field(default_factory=dict)       # customer_id -> (low, high)

    def for_customer(self, cid, industry=None):
        """-> (low, high, source, rationale)"""
        if cid in self.overrides:
            lo, hi = self.overrides[cid]
            return float(lo), float(hi), "KAM override", "Set by the KAM for this customer's contract circumstances."
        if self.industry_aware and industry and any(k in str(industry).lower() for k in HIGHER_RUN_INDUSTRIES):
            return HIGHER_RUN_BAND[0], HIGHER_RUN_BAND[1], "Industry default (TEAM_ASSUMPTION)", \
                "Hygiene/food-type industries naturally run higher washing rates (Lindström); the +10 point shift is a team assumption until Lindström confirms."
        return float(self.default[0]), float(self.default[1]), "General default (TEAM_ASSUMPTION)", \
            "General healthy band discussed with Lindström (30-70 %); the preferred range varies by account."


# ----------------------------------------------------------------------------------------------------------
# name, unit, status, definition   (plain column name -> metadata; used by Data_Dictionary and the Measures sheet)
MEASURES = {
    "Washed kg": ("kg", "CALCULATED", "Customer-attributed washed weight: sum of customer_washed_kg."),
    "Garments allocated": ("garments", "CALCULATED", "Sum of allocated_pieces (garments assigned). For a period this is the sum of monthly snapshots."),
    "Garments with scan activity": ("garments", "CALCULATED", "Sum of active_assets_scanned: garments that recorded scan activity in the month."),
    "Allocated garments with no scan activity": ("garments", "CALCULATED",
                                                 "Allocated minus with-scan-activity, floored at 0. An investigation signal, not a conclusion: the garment may not have needed washing, not yet been picked up, or scan data may be incomplete."),
    "Utilisation %": ("%", "CALCULATED", "Garments with scan activity / garments allocated x 100. A signal, not proof of idleness."),
    "Service requests": ("requests", "CALCULATED", "Sum of service_requests."),
    "Service requests per 1000 garments": ("per 1000 garments", "CALCULATED", "Service requests / garments allocated x 1000."),
    "Service cycles": ("cycles", "CALCULATED", "Number of RFID service cycles picked up in the period."),
    "On-time %": ("%", "CALCULATED", "Share of service cycles whose performance flag is ON_TIME."),
    "Average cycle hours": ("hours", "CALCULATED", "Mean hours from pickup to delivery (stated cycle_hours, else delivered minus pickup timestamp)."),
    "Repairs": ("repairs", "CALCULATED", "Sum of repair_count: counted repair events."),
    "Repairs per 1000 garments": ("per 1000 garments", "CALCULATED", "Repairs / garments allocated x 1000."),
    "Repairs per 1000 kg": ("per 1000 kg", "CALCULATED", "Repairs / washed kg x 1000."),
    "Replacements postponed (estimate)": ("pieces", "ESTIMATED", "Repairs x replacements-postponed factor (Base case 1.0). A repair is not proof that a replacement was avoided."),
    "Purchases avoided EUR (estimate)": ("EUR", "ESTIMATED", "Sum of repair_count x product purchase cost x repair factor (Base 1.0). Upper-bound estimate; no labour or lifetime effects."),
    "Water L": ("L", "ALLOCATED", "Laundry fresh water per kg x customer washed kg, allocated by washed-kg share. Only kg matched to laundry data."),
    "Energy kWh": ("kWh", "ALLOCATED", "Laundry energy per kg x customer washed kg (matched kg only)."),
    "Process CO2e kg": ("kgCO2e", "ALLOCATED", "Laundry process emissions per kg x customer washed kg."),
    "Delivery CO2e kg": ("kgCO2e", "ALLOCATED", "Laundry delivery emissions per kg x customer washed kg."),
    "Total CO2e kg": ("kgCO2e", "ALLOCATED", "Process + delivery CO2e."),
    "Water saved vs baseline L": ("L", "ALLOCATED", "Baseline L/kg x matched kg minus allocated water. Baseline named in the 'Baseline' column."),
    "Energy saved vs baseline kWh": ("kWh", "ALLOCATED", "Baseline kWh/kg x matched kg minus allocated energy."),
    "CO2e saved vs baseline kg": ("kgCO2e", "ALLOCATED", "Baseline (process+delivery) kgCO2e/kg x matched kg minus allocated CO2e."),
    "Textile waste kg": ("kg", "ALLOCATED", "Laundry textile waste per washed kg x customer washed kg."),
    "Recycling %": ("%", "ALLOCATED", "Share of textile waste recycled or reused (recycling_kg + reuse_kg) / total textile waste."),
    "Diversion %": ("%", "ALLOCATED", "Share of textile waste diverted from incineration: (recycling + reuse + energy recovery) / total. Energy recovery is recovery, not recycling."),
}
ADDITIVE = ["Washed kg", "Garments allocated", "Garments with scan activity", "Service requests", "Service cycles", "Repairs",
            "Replacements postponed (estimate)", "Purchases avoided EUR (estimate)", "Water L", "Energy kWh", "Process CO2e kg", "Delivery CO2e kg",
            "Water saved vs baseline L", "Energy saved vs baseline kWh", "CO2e saved vs baseline kg", "Textile waste kg"]
MEASURE_ORDER = list(MEASURES)
STATUS_NOTE = ("Calculated: utilisation, service, repairs. Allocated: water, energy, CO2e, waste (by washed-kg share). "
               "Estimated: replacements postponed, purchases avoided.")


def _sum(g, col):
    return g[col].sum(min_count=1)


def laundry_month(T):
    """App intensities + diversion share per (month, laundry)."""
    RI = mt._intensities(T)
    if RI is None:
        return None
    RI = RI.copy()
    W = T.get("waste")
    RI["div_share"] = np.nan
    if W is not None and not W.empty:
        w = W.copy()
        routes = w[["recycling_kg", "reuse_kg", "energy_recovery_kg", "incineration_kg"]].sum(axis=1, min_count=1)
        tot = w.textile_waste_total_kg.where(w.textile_waste_total_kg.notna(), routes)
        w["div_share"] = (w.recycling_kg.fillna(0) + w.reuse_kg.fillna(0) + w.energy_recovery_kg.fillna(0)) / tot.replace(0, np.nan)
        d = w[["month", "laundry_id", "div_share"]].drop_duplicates(["month", "laundry_id"])
        RI = RI.drop(columns="div_share").merge(d, on=["month", "laundry_id"], how="left")
    return RI


def baseline_row(T, baseline_id=None):
    bid = baseline_id or mt.default_baseline(T)
    B = T.get("baselines")
    if B is None or B.empty or bid is None:
        return None, "no baseline"
    r = B[B.baseline_id == bid]
    return (r.iloc[0] if len(r) else None), mt.baseline_name(T, bid)


def _activity_rows(T, RI, bl):
    A = T["service_activity"].copy()
    A["kg"] = A.customer_washed_kg
    if RI is not None:
        A = A.merge(RI[["month", "laundry_id", "water", "energy", "proc", "deliv", "co2", "waste_ratio", "rec_share", "div_share"]],
                    on=["month", "laundry_id"], how="left")
    else:
        for c in ("water", "energy", "proc", "deliv", "co2", "waste_ratio", "rec_share", "div_share"):
            A[c] = np.nan
    kg = A.kg
    A["Water L"] = kg * A.water
    A["Energy kWh"] = kg * A.energy
    A["Process CO2e kg"] = kg * A.proc
    A["Delivery CO2e kg"] = kg * A.deliv
    A["Total CO2e kg"] = kg * A.co2
    bw = float(bl.water_l_per_kg) if bl is not None and pd.notna(bl.get("water_l_per_kg")) else np.nan
    be = float(bl.energy_kwh_per_kg) if bl is not None and pd.notna(bl.get("energy_kwh_per_kg")) else np.nan
    bc = (float(bl.process_kgco2e_per_kg) + (0 if pd.isna(bl.get("delivery_kgco2e_per_kg")) else float(bl.delivery_kgco2e_per_kg))) \
        if bl is not None and pd.notna(bl.get("process_kgco2e_per_kg")) else np.nan
    A["Water saved vs baseline L"] = kg * bw - A["Water L"]
    A["Energy saved vs baseline kWh"] = kg * be - A["Energy kWh"]
    A["CO2e saved vs baseline kg"] = kg * bc - A["Total CO2e kg"]
    A["Textile waste kg"] = kg * A.waste_ratio
    A["_rec_w"] = A["Textile waste kg"].where(A.rec_share.notna()) * A.rec_share
    A["_rec_den"] = A["Textile waste kg"].where(A.rec_share.notna())
    A["_div_w"] = A["Textile waste kg"].where(A.div_share.notna()) * A.div_share
    A["_div_den"] = A["Textile waste kg"].where(A.div_share.notna())
    A["Garments allocated"] = A.allocated_pieces
    A["Garments with scan activity"] = A.active_assets_scanned
    A["Service requests"] = A.service_requests
    A["Washed kg"] = kg
    return A


def _repair_rows(T):
    R = T.get("repairs")
    if R is None or R.empty:
        return None
    R = R.copy()
    P = T.get("products")
    cost = R.product_id.map(P.set_index("product_id").purchase_cost_eur) if P is not None and not P.empty and P.purchase_cost_eur.notna().any() else pd.Series(np.nan, index=R.index)
    R["Repairs"] = R.repair_count
    R["Replacements postponed (estimate)"] = R.repair_count * 1.0
    R["Purchases avoided EUR (estimate)"] = R.repair_count * cost * 1.0
    return R


def _cycle_rows(T):
    C = T.get("service_cycles")
    if C is None or C.empty:
        return None
    C = C.copy()
    C["month"] = C.pickup_timestamp.dt.strftime("%Y-%m") if C.pickup_timestamp.notna().any() else np.nan
    C["Service cycles"] = 1.0
    if C.performance_flag.notna().any():
        late = C.performance_flag.astype(str).str.upper().str.replace(" ", "_") != "ON_TIME"
        C["_ontime"] = (~late).astype(float).where(C.performance_flag.notna())
    else:
        C["_ontime"] = np.nan
    hrs = C.cycle_hours if C.cycle_hours.notna().any() else (C.delivered_timestamp - C.pickup_timestamp).dt.total_seconds() / 3600
    C["_hrs"] = hrs
    return C


def build_frames(T, baseline_id=None):
    """Row-level frames reused by every grouping level."""
    RI = laundry_month(T)
    bl, bname = baseline_row(T, baseline_id)
    A = _activity_rows(T, RI, bl) if T.get("service_activity") is not None and not T["service_activity"].empty else None
    return dict(A=A, R=_repair_rows(T), C=_cycle_rows(T), baseline=bname)


def aggregate(F, keys: list[str]) -> pd.DataFrame:
    """Measures at the requested grain, with derived ratios. Missing source -> NaN (never 0)."""
    parts = []
    A, R, C = F["A"], F["R"], F["C"]
    if A is not None:
        cols = [c for c in ADDITIVE if c in A.columns] + ["Total CO2e kg", "_rec_w", "_rec_den", "_div_w", "_div_den"]
        cols = [c for c in dict.fromkeys(cols) if c not in ("Replacements postponed (estimate)", "Purchases avoided EUR (estimate)", "Repairs", "Service cycles")]
        parts.append(A.groupby(keys, dropna=False)[cols].sum(min_count=1))
    if R is not None:
        rk = [k for k in keys if k in R.columns]
        g = R.groupby(rk, dropna=False)[["Repairs", "Replacements postponed (estimate)", "Purchases avoided EUR (estimate)"]].sum(min_count=1)
        parts.append(g)
    if C is not None:
        ck = [k for k in keys if k in C.columns]
        g = C.groupby(ck, dropna=False).agg(**{"Service cycles": ("Service cycles", "sum"), "_ot_sum": ("_ontime", "sum"), "_ot_n": ("_ontime", "count"),
                                              "Average cycle hours": ("_hrs", "mean")})
        parts.append(g)
    if not parts:
        return pd.DataFrame(columns=keys)
    M = parts[0]
    for p in parts[1:]:
        M = M.join(p, how="outer") if list(M.index.names) == list(p.index.names) else M.join(p, how="outer")
    M = M.reset_index()
    d = lambda a, b: (a / b.replace(0, np.nan))
    if "Garments allocated" in M:
        M["Allocated garments with no scan activity"] = (M["Garments allocated"] - M["Garments with scan activity"]).clip(lower=0)
        M["Utilisation %"] = 100 * d(M["Garments with scan activity"], M["Garments allocated"])
        M["Service requests per 1000 garments"] = 1000 * d(M["Service requests"], M["Garments allocated"])
        if "Repairs" in M:
            M["Repairs per 1000 garments"] = 1000 * d(M["Repairs"], M["Garments allocated"])
            M["Repairs per 1000 kg"] = 1000 * d(M["Repairs"], M["Washed kg"])
    if "_ot_n" in M:
        M["On-time %"] = 100 * d(M["_ot_sum"], M["_ot_n"])
    if "_rec_den" in M:
        M["Recycling %"] = 100 * d(M["_rec_w"], M["_rec_den"])
        M["Diversion %"] = 100 * d(M["_div_w"], M["_div_den"])
    M = M.drop(columns=[c for c in M.columns if c.startswith("_")])
    for c in MEASURE_ORDER:
        if c not in M:
            M[c] = np.nan
    return M[keys + MEASURE_ORDER]


# ----------------------------------------------------------------------------------------------------------
def _num(v, nd=1):
    return "n/a" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v:,.{nd}f}".replace(",", " ")


def notable_text(row, cust_rows: pd.DataFrame, port_rows: pd.DataFrame, band, name_col="Site", prior=None):
    """Plain-language reasons why a site stands out; most informative first. -> (text, n_reasons, level)"""
    lo, hi = band
    reasons, strength = [], []
    u = row.get("Utilisation % (latest month)")
    if pd.notna(u):
        peers = cust_rows["Utilisation % (latest month)"].drop(row.name, errors="ignore").dropna()
        pa = port_rows["Utilisation % (latest month)"].dropna()
        if u < lo:
            s = f"utilisation is {u:.0f} %, {lo - u:.0f} points below the {lo:.0f}-{hi:.0f} % band: some allocated garments show no scan activity, which may mean the allocation is larger than needed (to investigate)"
            reasons.append(s); strength.append((lo - u) / 10 + 1)
        elif u > hi:
            s = f"utilisation is {u:.0f} %, {u - hi:.0f} points above the {lo:.0f}-{hi:.0f} % band: garments are heavily used, so more garments may be needed (to investigate)"
            reasons.append(s); strength.append((u - hi) / 10 + 1)
        if len(peers) >= 3 and abs(u - peers.mean()) >= 10:
            reasons.append(f"{abs(u - peers.mean()):.0f} points {'above' if u > peers.mean() else 'below'} this customer's other sites ({peers.mean():.0f} % on average)")
            strength.append(abs(u - peers.mean()) / 20)
    r = row.get("Service requests per 1000 garments")
    if pd.notna(r):
        peers = cust_rows["Service requests per 1000 garments"].drop(row.name, errors="ignore").dropna()
        if len(peers) >= 3 and peers.mean() > 0 and r >= 1.25 * peers.mean():
            reasons.append(f"{100 * (r / peers.mean() - 1):.0f} % more service requests per 1000 garments than this customer's other sites ({r:.1f} vs {peers.mean():.1f})")
            strength.append(r / peers.mean() - 1)
    o = row.get("On-time %")
    if pd.notna(o):
        peers = cust_rows["On-time %"].drop(row.name, errors="ignore").dropna()
        if len(peers) >= 3 and peers.mean() - o >= 1.5:
            reasons.append(f"on-time delivery is {o:.1f} %, {peers.mean() - o:.1f} points below this customer's other sites ({peers.mean():.1f} %)")
            strength.append((peers.mean() - o) / 3)
    rp = row.get("Repairs per 1000 kg")
    if pd.notna(rp):
        peers = cust_rows["Repairs per 1000 kg"].drop(row.name, errors="ignore").dropna()
        if len(peers) >= 3 and peers.mean() > 0 and rp >= 1.3 * peers.mean():
            reasons.append(f"{100 * (rp / peers.mean() - 1):.0f} % more repairs per 1000 kg washed than this customer's other sites (a cost and circularity signal)")
            strength.append(rp / peers.mean() - 1)
    if prior is not None and pd.notna(prior):
        if abs(prior) >= 10:
            reasons.append(f"washed kg is {abs(prior):.0f} % {'higher' if prior > 0 else 'lower'} than the same period last year")
            strength.append(abs(prior) / 40)
    if not reasons:
        return "Nothing stands out against the band or this customer's other sites.", 0, "none"
    order = np.argsort(strength)[::-1]
    text = "; ".join(reasons[i] for i in order)
    text = text[0].upper() + text[1:] + "."
    return text, len(reasons), ("notable" if len(reasons) >= 2 or max(strength) >= 1.5 else "minor")


def yoy_pct(monthly: pd.DataFrame, col: str):
    """Latest 12 months vs the 12 before, only when 24 months exist. Else None (the file cannot answer)."""
    s = monthly.dropna(subset=[col]).sort_values("month")
    months = sorted(s.month.unique())
    if len(months) < 24:
        return None
    last12, prev12 = months[-12:], months[-24:-12]
    a, b = s[s.month.isin(last12)][col].sum(), s[s.month.isin(prev12)][col].sum()
    return None if b == 0 else 100 * (a / b - 1)
