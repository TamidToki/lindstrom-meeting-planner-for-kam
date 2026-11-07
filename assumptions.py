"""Every assumption and threshold the app itself introduces, in one place.
These are OUR prototype settings, not Lindström-approved values; the sidebar lets a user change them
and every output records which values were used."""
from __future__ import annotations
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Uncertainty:
    baseline_pct: float = 0.20      # +/- on comparison-baseline intensities (pack baselines are illustrative)
    allocation_pct: float = 0.10    # +/- on allocated laundry resource use (allocation by washed-kg share)
    repair_low: float = 0.5         # share of repairs that really postpone a purchase, low case
    repair_high: float = 1.0        # pack assumption A002 is an upper bound: 1 repair = 1 postponed replacement


@dataclass(frozen=True)
class Params:
    name: str
    repair_factor: float
    baseline_mult: float            # multiplies baseline L/kg, kWh/kg, kgCO2e/kg
    alloc_mult: float               # multiplies allocated actual use (water, energy, emissions, waste)


def scenario_params(name: str, u: Uncertainty = Uncertainty()) -> Params:
    """Low = conservative (smaller benefit), Base = pack values as given, High = favourable."""
    if name == "Low":
        return Params("Low", u.repair_low, 1 - u.baseline_pct, 1 + u.allocation_pct)
    if name == "High":
        return Params("High", u.repair_high, 1 + u.baseline_pct, 1 - u.allocation_pct)
    return Params("Base", 1.0, 1.0, 1.0)


SCENARIO_TEXT = {
    "Low": "Conservative: baseline intensities −{b:.0%}, allocated use +{a:.0%}, repair factor {r}.",
    "Base": "Pack values as supplied; 1 completed repair postpones 1 replacement (pack assumption A002).",
    "High": "Favourable: baseline intensities +{b:.0%}, allocated use −{a:.0%}, repair factor {r}.",
}


def scenario_text(name: str, u: Uncertainty) -> str:
    return SCENARIO_TEXT[name].format(b=u.baseline_pct, a=u.allocation_pct, r=u.repair_low if name == "Low" else u.repair_high)


# ---- validation thresholds --------------------------------------------------------------------
THRESH = dict(
    rel_tol=0.005,          # totals must agree within 0.5 %
    abs_tol_kg=1.0,
    ref_rel_tol=0.01,       # control totals within 1 %
    min_cover_months=0.0,
    scanned_over_allocated=1.05,
    cycle_hours_tol=1.0,    # hours between timestamps and stated cycle_hours
    waste_sum_tol=0.01,
    intensity_tol=0.01,     # stated per-kg value vs total/kg
    unit_majority=0.5,
    repairs_per_piece_max=2.0,   # repairs per allocated garment per year above this is implausible      # if more than this share of rows is implausible, suspect a unit problem
)
PLAUSIBLE = {               # (low, high) per unit; outside = suspect wrong unit
    "fresh_water_l_per_kg": (0.3, 60.0),
    "energy_kwh_per_kg": (0.05, 8.0),
    "water_l_per_kg": (0.3, 60.0),
    "kg_per_piece": (0.03, 6.0),
    "cycle_hours": (0.0, 24 * 30),
}

# ---- the app's own assumption registry (shown in the UI, the deck and the methodology note) ----
APP_ASSUMPTIONS = [
    ("X01", "Allocation of laundry resources", "customer water/energy/emissions/waste = customer washed kg × laundry intensity per kg (same month and laundry)",
     "Source data is laundry-level; customer use is an allocated estimate", "Medium", "Disclosed on every affected number"),
    ("X02", "Comparison baseline sensitivity", "Baseline intensities ±{baseline_pct:.0%} in Low/High",
     "Pack baselines are illustrative single values; no uncertainty supplied", "Low", "Editable in sidebar"),
    ("X03", "Allocation sensitivity", "Allocated use ±{allocation_pct:.0%} in Low/High", "Allocation key (washed-kg share) is a simplification", "Low-Medium", "Editable in sidebar"),
    ("X04", "Repair factor", "Low {repair_low}, Base 1.0, High {repair_high} replacements postponed per repair",
     "Pack assumption A002 is an upper bound; no evidence for more than 1:1", "Low-Medium", "Editable in sidebar"),
    ("X05", "Purchases avoided (EUR)", "Σ repairs × product purchase cost × repair factor; no labour, lifetime or residual-value effects",
     "Direct avoided purchase only, the safest claim", "Low", "Estimated; needs real replacement cost"),
    ("X06", "Site attention flag", "Robust outlier (median/MAD z≥1.5) with a minimum effect (utilisation ≥3 pp, on-time ≥1 pp, requests ≥25 % above median) on ≥2 indicators, or z≥3 on one; needs ≥4 sites",
     "No external benchmark in the pack; relative ranking only, guarded against noise", "Low", "Signal, not a performance verdict"),
    ("X07", "Garment utilisation", "active_assets_scanned ÷ allocated_pieces in the last month", "Signal for allocated garments with no scan activity (investigate; not proof of idleness)", "Medium", "Calculated"),
    ("X08", "Validation tolerance", "Totals must agree within {rel_tol:.1%}; control totals within {ref_rel_tol:.0%}", "Rounding in exports", "Medium", "Editable in code"),
    ("X09", "Excluded rows", "Rows the user excludes are removed from every calculation and listed with the reason", "Only data that passes validation is used", "High", "Visible in dashboard and deck"),
    ("X10", "No LLM numbers", "Every figure is computed in code; an LLM (optional) may only phrase text and parse a priority", "Auditability", "High", "Mandatory"),
]
