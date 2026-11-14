"""Deterministic metric engine on cleaned canonical tables. Every number is a Metric with its formula,
inputs, calculation status, input-data status, source tables and a Low/Base/High range.
No LLM, no vector search: plain pandas arithmetic."""
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
import pandas as pd
from assumptions import Params, Uncertainty, scenario_params, scenario_text
from data_loader import status_summary


@dataclass
class Metric:
    key: str
    label: str
    value: float
    unit: str
    theme: str
    status: str                    # CALCULATED | ALLOCATED | ESTIMATED (how the number was produced)
    formula: str
    inputs: dict = field(default_factory=dict)
    note: str = ""
    low: float = None
    high: float = None
    range_basis: str = ""
    input_status: str = ""         # data_status labels of the source tables (e.g. SYNTHETIC)
    sources: tuple = ()
    caveat: str = ""

    def __post_init__(self):
        self.low = self.value if self.low is None else self.low
        self.high = self.value if self.high is None else self.high

    @staticmethod
    def _f(v, unit):
        if unit == "%":
            return f"{v:.1f} %"
        if float(v).is_integer() and abs(v) < 10_000:
            return f"{v:.0f} {unit}"
        if abs(v) >= 1e6:
            return f"{v/1e6:.2f} M {unit}"
        if abs(v) >= 1e4:
            return f"{v/1e3:.1f} k {unit}"
        if abs(v) >= 100:
            return f"{v:,.0f} {unit}".replace(",", " ")
        return f"{v:.1f} {unit}".strip()

    def fmt(self):
        return self._f(self.value, self.unit)

    @property
    def exact(self):
        return abs(self.high - self.low) < 1e-9

    def fmt_range(self):
        if self.exact:
            return "exact: no assumption applied"
        return f"{self._f(self.low, self.unit)} to {self._f(self.high, self.unit)}"


class MetricSet(dict):
    missing: dict
    coverage: dict
    scenario: str
    baseline_name: str


# key -> (label, unit, theme, status, formula, tables used, range basis when not exact)
SPEC = {
    "sites": ("Delivery sites", "sites", "scale", "CALCULATED", "count of distinct site_id in service activity", ("service_activity",), ""),
    "wearers": ("Active wearers ({m}, may double-count)", "wearers", "scale", "CALCULATED", "sum of active_wearers over product rows in the last month", ("service_activity",), ""),
    "pieces": ("Garments allocated ({m})", "pieces", "scale", "CALCULATED", "sum of allocated_pieces in the last month", ("service_activity",), ""),
    "kg": ("Textiles washed", "kg", "scale", "CALCULATED", "sum of customer_washed_kg", ("service_activity",), ""),
    "water_saving": ("Water saved vs {b}", "L", "water", "ALLOCATED",
                     "Σ matched kg × baseline L/kg × baseline factor − Σ matched kg × laundry L/kg × allocation factor", ("service_activity", "resources", "baselines"), "baseline and allocation sensitivity"),
    "water_per_kg": ("Water intensity (Lindström)", "L/kg", "water", "ALLOCATED", "Σ(kg × laundry L/kg) ÷ Σ kg × allocation factor", ("service_activity", "resources"), "allocation sensitivity"),
    "energy_saving": ("Energy saved vs {b}", "kWh", "water", "ALLOCATED",
                      "Σ matched kg × baseline kWh/kg × baseline factor − Σ matched kg × laundry kWh/kg × allocation factor", ("service_activity", "resources", "baselines"), "baseline and allocation sensitivity"),
    "energy_per_kg": ("Energy intensity (Lindström)", "kWh/kg", "water", "ALLOCATED", "Σ(kg × laundry kWh/kg) ÷ Σ kg × allocation factor", ("service_activity", "resources"), "allocation sensitivity"),
    "co2_service": ("Service emissions saved vs {b}", "kgCO2e", "emissions", "ALLOCATED",
                    "Σ matched kg × baseline (process+delivery kgCO2e/kg) × baseline factor − Σ matched kg × laundry (process+delivery kgCO2e/kg) × allocation factor",
                    ("service_activity", "resources", "baselines"), "baseline and allocation sensitivity"),
    "repairs": ("Repairs completed", "repairs", "circularity", "CALCULATED", "sum of repair_count", ("repairs",), ""),
    "postponed": ("Replacements postponed", "pieces", "circularity", "ESTIMATED", "repairs × replacements-postponed factor", ("repairs",), "repair factor"),
    "avoided_cost": ("Purchases avoided, upper-bound estimate", "EUR", "cost", "ESTIMATED", "Σ repair_count × product purchase cost × repair factor", ("repairs", "products"), "repair factor"),
    "avoided_co2": ("Avoided product emissions", "kgCO2e", "emissions", "ESTIMATED", "Σ repair_count × product footprint (or stated avoided kgCO2e) × repair factor", ("repairs", "products"), "repair factor"),
    "waste": ("Textile waste attributed", "kg", "circularity", "ALLOCATED", "Σ kg × laundry textile waste per washed kg × allocation factor", ("service_activity", "resources", "waste"), "allocation sensitivity"),
    "recycling_pct": ("Textile waste recycled or reused", "%", "circularity", "ALLOCATED", "Σ(kg × waste/kg × (recycling+reuse share)) ÷ Σ(kg × waste/kg)", ("service_activity", "resources", "waste"), ""),
    "ontime": ("On-time service cycles", "%", "service", "CALCULATED", "share of service cycles with performance_flag = ON_TIME", ("service_cycles",), ""),
    "cycle_hours": ("Avg. cycle time (pickup→delivery)", "h", "service", "CALCULATED", "mean cycle_hours (or delivered − pickup timestamp)", ("service_cycles",), ""),
    "requests": ("Service requests", "requests", "service", "CALCULATED", "sum of service_requests", ("service_activity",), ""),
    "utilisation": ("Garment utilisation (garments with scan activity ÷ allocated)", "%", "cost", "CALCULATED", "Σ active_assets_scanned ÷ Σ allocated_pieces in the last month", ("service_activity",), ""),
}
NOTES = {
    "wearers": "Summed across product rows: a person wearing two products is counted twice (pack caveat).",
    "water_saving": "Laundry water is allocated to the customer by washed kg (assumption X01).",
    "postponed": "Pack assumption A002: 1 completed repair postpones 1 replacement. Low case 0.5.",
    "avoided_cost": "Direct avoided purchase only; no labour or lifetime effects (assumption X05).",
    "avoided_co2": "Product footprints are illustrative, not approved LCA values.",
    "utilisation": "Allocated garments with no scan activity are an investigation signal, not a conclusion: they may not have needed washing, may not yet be picked up, or scan data may be incomplete.",
    "recycling_pct": "Laundry-level treatment routes allocated by washed kg.",
}


# ----------------------------------------------------------------------------------------------
def _flt(df, cid, sites, months):
    if df is None or df.empty:
        return None
    d = df[df.customer_id == cid] if "customer_id" in df and df.customer_id.notna().any() else df
    if sites is not None:
        d = d[d.site_id.isin(sites)]
    if months is not None and "month" in d:
        d = d[d.month.isin(months)]
    return d


def _intensities(T):
    """Per (month, laundry): water, energy, process/delivery kgCO2e per kg, waste per kg, recycle share."""
    Rs = T.get("resources")
    if Rs is None or Rs.empty:
        return None
    r = Rs[["month", "laundry_id"]].copy()
    kg = Rs.washed_kg.replace(0, np.nan)
    r["water"] = Rs.fresh_water_l_per_kg.where(Rs.fresh_water_l_per_kg.notna(), Rs.fresh_water_l / kg)
    r["energy"] = Rs.energy_kwh_per_kg.where(Rs.energy_kwh_per_kg.notna(), Rs.process_energy_kwh / kg)
    r["proc"] = Rs.process_emissions_kgco2e / kg
    r["deliv"] = Rs.delivery_emissions_kgco2e / kg
    r["co2"] = r.proc.fillna(0) + r.deliv.fillna(0)
    r.loc[r.proc.isna() & r.deliv.isna(), "co2"] = np.nan
    W = T.get("waste")
    if W is not None and not W.empty:
        w = W.copy()
        routes = w[["recycling_kg", "reuse_kg", "energy_recovery_kg", "incineration_kg"]].sum(axis=1, min_count=1)
        tot = w.textile_waste_total_kg.where(w.textile_waste_total_kg.notna(), routes)
        w["waste_total"] = tot
        w["rec_share"] = (w.recycling_kg.fillna(0) + w.reuse_kg.fillna(0)) / tot.replace(0, np.nan)
        r = r.merge(w[["month", "laundry_id", "waste_total", "rec_share", "waste_kg_per_washed_kg"]], on=["month", "laundry_id"], how="left")
        r = r.merge(Rs[["month", "laundry_id", "washed_kg"]], on=["month", "laundry_id"], how="left")
        ratio = r.waste_total / r.washed_kg.replace(0, np.nan)
        r["waste_ratio"] = ratio.where(ratio.notna(), r.waste_kg_per_washed_kg)
    else:
        r["waste_ratio"], r["rec_share"] = np.nan, np.nan
    return r.drop_duplicates(["month", "laundry_id"])


def _calc(T, cid, baseline_id, p: Params, sites=None, months=None, RI=None):
    """-> (values {key: (value, inputs)}, missing {key: reason}, coverage {name: share})."""
    A = _flt(T.get("service_activity"), cid, sites, months)
    R = _flt(T.get("repairs"), cid, sites, months)
    C = T.get("service_cycles")
    if C is not None and not C.empty:
        C = C.assign(month=C.pickup_timestamp.dt.strftime("%Y-%m") if C.pickup_timestamp.notna().any() else np.nan)
        C = _flt(C, cid, sites, months)
    B = T.get("baselines")
    P = T.get("products")
    V, miss, cov = {}, {}, {}
    if A is None or A.empty:
        return V, {k: "no service-activity rows for this customer after validation" for k in SPEC}, cov
    last = A.month.max()
    dec = A[A.month == last]
    V["sites"] = (A.site_id.nunique(), {})
    kg = A.customer_washed_kg.sum()
    V["kg"] = (kg, {"kg": kg})
    for k, col in (("wearers", "active_wearers"), ("pieces", "allocated_pieces")):
        if dec[col].notna().any():
            V[k] = (dec[col].sum(), {"month": last})
        else:
            miss[k] = f"column {col} not provided"
    if A.service_requests.notna().any():
        V["requests"] = (A.service_requests.sum(), {})
    else:
        miss["requests"] = "column service_requests not provided"
    if dec.active_assets_scanned.notna().any() and dec.allocated_pieces.sum() > 0:
        V["utilisation"] = (100 * dec.active_assets_scanned.sum() / dec.allocated_pieces.sum(),
                            {"scanned": dec.active_assets_scanned.sum(), "allocated": dec.allocated_pieces.sum(), "month": last})
    else:
        miss["utilisation"] = "active_assets_scanned or allocated_pieces not provided"

    # ---- resources vs baseline (matched kg only)
    if RI is None:
        miss.update({k: "no laundry-resource sheet passed validation" for k in
                     ("water_saving", "water_per_kg", "energy_saving", "energy_per_kg", "co2_service", "waste", "recycling_pct")})
    else:
        a = A[["month", "laundry_id", "customer_washed_kg"]].merge(RI, on=["month", "laundry_id"], how="left")
        bl = None
        if B is not None and not B.empty:
            bl = B[B.baseline_id == baseline_id]
            bl = bl.iloc[0] if len(bl) else None

        def block(col, per_kg_key, sav_key, base_col, unit_in):
            m = a[a[col].notna()]
            if m.empty:
                miss[per_kg_key] = miss[sav_key] = f"no laundry-resource values for '{col}' matching the customer's months/laundries"
                return
            kgm = m.customer_washed_kg.sum()
            cov[col] = kgm / kg if kg else 0
            act = (m.customer_washed_kg * m[col]).sum() * p.alloc_mult
            V[per_kg_key] = (act / kgm, {"matched_kg": kgm, "allocated_total": act})
            if bl is not None and pd.notna(bl.get(base_col)):
                base = kgm * float(bl[base_col]) * p.baseline_mult
                V[sav_key] = (base - act, {"matched_kg": kgm, f"baseline_{unit_in}": float(bl[base_col]), "baseline_total": base, "allocated_total": act})
            else:
                miss[sav_key] = "no comparison baseline available" if bl is None else f"baseline lacks {base_col}"
        block("water", "water_per_kg", "water_saving", "water_l_per_kg", "L_per_kg")
        block("energy", "energy_per_kg", "energy_saving", "energy_kwh_per_kg", "kWh_per_kg")
        m = a[a.co2.notna()]
        if m.empty:
            miss["co2_service"] = "no process/delivery emissions in the laundry-resource sheet"
        elif bl is None:
            miss["co2_service"] = "no comparison baseline available"
        else:
            kgm = m.customer_washed_kg.sum()
            act = (m.customer_washed_kg * m.co2).sum() * p.alloc_mult
            bi = float(bl.process_kgco2e_per_kg) + (0 if pd.isna(bl.delivery_kgco2e_per_kg) else float(bl.delivery_kgco2e_per_kg))
            base = kgm * bi * p.baseline_mult
            V["co2_service"] = (base - act, {"matched_kg": kgm, "baseline_kgCO2e_per_kg": bi, "baseline_total": base, "allocated_total": act})
        w = a[a.waste_ratio.notna()]
        if w.empty:
            miss["waste"] = miss["recycling_pct"] = "no textile-waste values matching the customer's months/laundries"
        else:
            wt = (w.customer_washed_kg * w.waste_ratio)
            V["waste"] = (wt.sum() * p.alloc_mult, {"matched_kg": w.customer_washed_kg.sum()})
            rs = w.rec_share
            if rs.notna().any() and wt[rs.notna()].sum() > 0:
                V["recycling_pct"] = (100 * (wt[rs.notna()] * rs[rs.notna()]).sum() / wt[rs.notna()].sum(), {})
            else:
                miss["recycling_pct"] = "recycling/reuse kg not provided"

    # ---- repairs
    if R is None or R.empty or not R.repair_count.notna().any():
        miss.update({k: "no repair sheet passed validation" for k in ("repairs", "postponed", "avoided_cost", "avoided_co2")})
    else:
        reps = R.repair_count.sum()
        V["repairs"] = (reps, {})
        V["postponed"] = (reps * p.repair_factor, {"repairs": reps, "factor": p.repair_factor})
        if P is not None and not P.empty and P.purchase_cost_eur.notna().any() and R.product_id.notna().any():
            cost = R.product_id.map(P.set_index("product_id").purchase_cost_eur)
            ok = cost.notna()
            V["avoided_cost"] = ((R.repair_count[ok] * cost[ok]).sum() * p.repair_factor,
                                 {"factor": p.repair_factor, "gross_EUR": (R.repair_count[ok] * cost[ok]).sum(), "repairs_without_cost": int((~ok).sum())})
        else:
            miss["avoided_cost"] = "product purchase cost not provided"
        if R.estimated_avoided_product_kgco2e.notna().any():
            g = R.estimated_avoided_product_kgco2e.sum()
        elif P is not None and not P.empty and P.product_footprint_kgco2e.notna().any():
            fp = R.product_id.map(P.set_index("product_id").product_footprint_kgco2e)
            g = (R.repair_count * fp).sum()
        else:
            g = None
        if g is None:
            miss["avoided_co2"] = "product footprint not provided"
        else:
            V["avoided_co2"] = (g * p.repair_factor, {"factor": p.repair_factor, "gross_kgCO2e": g})

    # ---- service cycles
    if C is None or C.empty:
        miss["ontime"] = miss["cycle_hours"] = "no service-cycle sheet passed validation for this customer"
    else:
        if C.performance_flag.notna().any():
            late = (C.performance_flag.astype(str).str.upper().str.replace(" ", "_") != "ON_TIME")[C.performance_flag.notna()]
            V["ontime"] = (100 * (1 - late.mean()), {"cycles": int(late.size), "late": int(late.sum())})
        else:
            miss["ontime"] = "performance_flag not provided"
        hrs = C.cycle_hours if C.cycle_hours.notna().any() else (C.delivered_timestamp - C.pickup_timestamp).dt.total_seconds() / 3600
        if hrs.notna().any():
            V["cycle_hours"] = (hrs.mean(), {"cycles": int(hrs.notna().sum())})
        else:
            miss["cycle_hours"] = "cycle_hours and pickup/delivered timestamps not provided"
    return V, miss, cov


def default_baseline(T) -> str | None:
    B = T.get("baselines")
    if B is None or B.empty:
        return None
    d = B[B.selection_status.astype(str).str.upper().str.contains("DEFAULT")] if B.selection_status.notna().any() else B.iloc[0:0]
    return (d if len(d) else B).iloc[0].baseline_id


def baseline_name(T, bid) -> str:
    B = T.get("baselines")
    if B is None or B.empty or bid is None:
        return "no baseline"
    r = B[B.baseline_id == bid]
    return str(r.iloc[0].baseline_name) if len(r) and pd.notna(r.iloc[0].baseline_name) else str(bid)


def metrics(T, cid, baseline_id=None, scenario="Base", unc: Uncertainty = Uncertainty(), sites=None, months=None) -> MetricSet:
    baseline_id = baseline_id or default_baseline(T)
    RI = _intensities(T)
    runs = {s: _calc(T, cid, baseline_id, scenario_params(s, unc), sites, months, RI) for s in ("Low", "Base", "High")}
    sel_v, miss, cov = runs[scenario]
    bname = baseline_name(T, baseline_id)
    M = MetricSet()
    M.missing, M.coverage, M.scenario, M.baseline_name = miss, cov, scenario, bname
    last = ""
    A = _flt(T.get("service_activity"), cid, sites, months)
    if A is not None and not A.empty:
        last = A.month.max()
    for key, (v, inp) in sel_v.items():
        label, unit, theme, status, formula, tabs, basis = SPEC[key]
        vals = [runs[s][0][key][0] for s in runs if key in runs[s][0]]
        lo, hi = min(vals), max(vals)
        caveat = ""
        if key in ("water_saving", "water_per_kg", "energy_saving", "energy_per_kg", "co2_service", "waste", "recycling_pct") and cov:
            worst = min(cov.values())
            if worst < 0.999:
                caveat = f"Only {worst:.0%} of washed kg could be matched to laundry resource data (missing month/laundry); the rest is not included."
        M[key] = Metric(key, label.format(m=last, b=bname), float(v), unit, theme, status, formula, dict(inp), NOTES.get(key, ""),
                        float(lo), float(hi), (basis if hi - lo > 1e-9 else ""), status_summary(T, list(tabs)), tuple(tabs), caveat)
    return M


def site_table(T, cid, baseline_id=None, scenario="Base", unc: Uncertainty = Uncertainty(), months=None) -> pd.DataFrame:
    baseline_id = baseline_id or default_baseline(T)
    RI = _intensities(T)
    p = scenario_params(scenario, unc)
    S = T["sites"][T["sites"].customer_id == cid]
    rows = []
    for _, s in S.iterrows():
        V, _, _ = _calc(T, cid, baseline_id, p, [s.site_id], months, RI)
        r = {"site_id": s.site_id, "site": s.site_name if pd.notna(s.site_name) else s.site_id,
             "country": s.country if pd.notna(s.country) else "n/a", "type": s.site_type}
        r.update({k: v[0] for k, v in V.items()})
        rows.append(r)
    t = pd.DataFrame(rows)
    for c in ("pieces", "wearers", "requests", "utilisation", "ontime", "kg", "water_saving", "co2_service", "repairs"):
        if c not in t:
            t[c] = np.nan
    t["requests_per_1000"] = 1000 * t.requests / t.pieces.replace(0, np.nan)
    return flag_sites(t)


def _outlier(series: pd.Series, bad_is_high: bool, min_abs=None, min_rel=None, z=1.5):
    """Robust outlier in the bad direction (median/MAD) AND a minimum practical effect.
    Returns (flag, extreme). Needs >= 4 sites; otherwise nothing is flagged (too few to compare)."""
    s = series.dropna()
    if len(s) < 4:
        return pd.Series(False, index=series.index), pd.Series(False, index=series.index)
    med = s.median()
    spread = (s - med).abs().median() * 1.4826
    spread = spread if spread > 0 else (s.std() or 1.0)
    dev = (series - med) * (1 if bad_is_high else -1)
    zs = dev / spread
    practical = pd.Series(True, index=series.index)
    if min_abs is not None:
        practical &= dev >= min_abs
    if min_rel is not None:
        practical &= dev >= min_rel * abs(med)
    flag = series.notna() & (zs >= z) & practical
    return flag, series.notna() & (zs >= 3) & practical


def flag_sites(t: pd.DataFrame) -> pd.DataFrame:
    """A site needs attention when it is a robust outlier (median/MAD z>=1.5) with a real effect size on >=2 indicators,
    or an extreme outlier (z>=3) on one. Relative to this customer's own sites, so a signal, not a diagnosis."""
    t = t.copy()
    t["flag_utilisation"], e1 = _outlier(t.utilisation, False, min_abs=3.0)
    t["flag_ontime"], e2 = _outlier(t.ontime, False, min_abs=1.0)
    t["flag_requests"], e3 = _outlier(t.requests_per_1000, True, min_rel=0.25)
    t["n_flags"] = t[["flag_utilisation", "flag_ontime", "flag_requests"]].sum(axis=1)
    t["extreme"] = e1 | e2 | e3
    t["attention"] = (t.n_flags >= 2) | t.extreme
    return t


def country_rollup(t: pd.DataFrame) -> pd.DataFrame:
    g = t.groupby("country").agg(sites=("site_id", "count"), attention=("attention", "sum"), kg=("kg", "sum"),
                                 water_saving=("water_saving", "sum"), co2=("co2_service", "sum"),
                                 repairs=("repairs", "sum"), requests=("requests", "sum"))
    return g.reset_index()


def quick_totals(T, cid, year=None) -> dict:
    """Base-scenario totals for reconciling against a control-total sheet."""
    months = None
    A = T.get("service_activity")
    if year is not None and A is not None:
        months = sorted(m for m in A.month.dropna().unique() if str(m).startswith(str(int(year))))
    V, _, _ = _calc(T, cid, default_baseline(T), scenario_params("Base"), None, months, _intensities(T))
    return {k: v[0] for k, v in V.items()}


def enrich(T: dict) -> dict:
    """Fill hierarchy gaps deterministically: customer_id from sites, laundry_id from primary laundry."""
    T = {k: v.copy() for k, v in T.items()}
    S = T.get("sites")
    if S is None or S.empty:
        return T
    c_map = S.drop_duplicates("site_id").set_index("site_id").customer_id
    l_map = S.drop_duplicates("site_id").set_index("site_id").primary_laundry_id
    for name in ("service_activity", "repairs", "service_cycles", "impacts"):
        d = T.get(name)
        if d is None or d.empty:
            continue
        if "customer_id" in d:
            d["customer_id"] = d.customer_id.where(d.customer_id.notna(), d.site_id.map(c_map))
        if "laundry_id" in d and name != "impacts":
            d["laundry_id"] = d.laundry_id.where(d.laundry_id.notna(), d.site_id.map(l_map))
    return T
