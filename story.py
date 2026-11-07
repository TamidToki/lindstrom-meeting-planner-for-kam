"""Priority parsing, metric ordering, rules-based recommendations and the customer story.
All figures come from metrics.Metric. An LLM (optional) may only phrase text or parse a priority."""
from __future__ import annotations
import providers
import os
import pandas as pd

THEMES = {
    "water": ["water", "energy", "kwh", "litre", "liter", "resource"],
    "cost": ["cost", "money", "saving", "budget", "euro", "eur", "price", "utilis", "utiliz", "allocation"],
    "emissions": ["emission", "co2", "carbon", "climate", "scope", "footprint", "ghg"],
    "circularity": ["circular", "repair", "recycl", "waste", "lifetime", "reuse"],
    "service": ["service", "hygiene", "late", "deliver", "reliab", "continuity", "compliance", "traceab", "turnaround"],
}
INDUSTRY_DEFAULT = {"Food & Beverage": ["service", "water", "service"], "Manufacturing": ["cost", "circularity", "service"],
                    "Healthcare": ["service", "service", "service"]}


def _theme_of(text: str):
    t = str(text).lower()
    for th, kws in THEMES.items():
        if any(k in t for k in kws):
            return th
    return None


def industry_order(T: dict, industry: str) -> list[str]:
    P = T.get("industry_priorities")
    if P is not None and not P.empty and industry:
        p = P[P.industry.astype(str).str.lower() == str(industry).lower()].sort_values("priority_rank")
        out = [x for x in (_theme_of(v) for v in p.priority_theme) if x]
        if out:
            return out
    return INDUSTRY_DEFAULT.get(industry, ["service", "cost", "water"])


def parse_priority(text: str, T: dict, industry: str, llm: bool = True) -> list[str]:
    """Ordered themes. Keyword rules always work; an LLM may refine free text but never touches numbers."""
    text = (text or "").lower()
    hits = []
    for th, kws in THEMES.items():
        pos = [text.find(k) for k in kws if k in text]
        if pos:
            hits.append((min(pos), th))
    ordered = [t for _, t in sorted(hits)]
    if not ordered and llm and text.strip() and providers.current() is not None:
        out = providers.complete_text(f"Customer priority: '{text}'. Pick the best matching themes in order from {list(THEMES)}. Reply with a comma-separated list only.", 40)
        if out:
            ordered = [t.strip() for t in out.split(",") if t.strip() in THEMES]
    for t in industry_order(T, industry) + list(THEMES):
        if t not in ordered:
            ordered.append(t)
    return ordered


def order_metrics(M: dict, themes: list[str]) -> list:
    rank = {t: i for i, t in enumerate(themes)}
    return sorted((m for m in M.values() if m.theme != "scale"), key=lambda m: rank.get(m.theme, 99))


def _have(M, *keys):
    return all(k in M for k in keys)


def recommendations(M: dict, S: pd.DataFrame, themes: list[str], bname: str, issues: pd.DataFrame | None = None, log: pd.DataFrame | None = None) -> list[dict]:
    """Rules-generated discussion points. Each cites the calculated facts it rests on and is skipped if its data is missing."""
    R = []
    if _have(M, "utilisation") and S["utilisation"].notna().any():
        w = S.dropna(subset=["utilisation"]).sort_values("utilisation").head(3)
        idle = (S.pieces * (1 - S.utilisation / 100)).sum()
        R.append(dict(theme="cost", title="Right-size the garment allocation",
                      text=f"Garment utilisation is {M['utilisation'].fmt()}. Lowest sites: {', '.join(w.site)} ({w.utilisation.min():.0f}-{w.utilisation.max():.0f} %). "
                           f"About {format(idle, ',.0f').replace(',', ' ')} allocated garments were not scanned in the last month: review allocation or wearer-to-garment ratios before next year's order.",
                      basis="utilisation = scanned ÷ allocated (CALCULATED)"))
    att = S[S.attention]
    if len(att):
        R.append(dict(theme="service", title="Agree an action plan for flagged sites",
                      text=f"{len(att)} of {len(S)} sites combine at least two weak signals (low garment utilisation, late cycles, high service-request rate), e.g. {', '.join(att.site.head(4))}. "
                           f"By country: {att.groupby('country').size().to_dict()}. Ask the site managers what is behind it.",
                      basis="Relative rule: robust outlier vs the customer's own sites (median/MAD) on ≥2 indicators, or extreme on one"))
    if "wearers" in S and "pieces" in S:
        over = S[S.wearers > S.pieces]
        if len(over):
            R.append(dict(theme="service", title="Clarify garment sharing and traceability",
                          text=f"{len(over)} site(s) report more active wearers than allocated garments ({', '.join(over.site.head(3))}). Garments are probably shared. "
                               "Agree how wearer counts should be defined, and keep reporting at site/group level, never named individuals.",
                          basis="wearers > allocated pieces (data gap, GDPR-safe aggregation)"))
    if _have(M, "water_saving", "water_per_kg"):
        R.append(dict(theme="water", title="Make the resource story explicit",
                      text=f"Allocated water use is {M['water_per_kg'].fmt()} against {bname}; {M['water_saving'].fmt()} saved in the period (range {M['water_saving'].fmt_range()}). "
                           "The result is sensitive to the baseline; agree with the customer which baseline fits their situation before using it in sustainability reporting.",
                      basis="water saving = washed kg × baseline L/kg − allocated water (ALLOCATED; range from baseline and allocation sensitivity)"))
    if _have(M, "repairs", "postponed"):
        extra = f" and avoids about {M['avoided_cost'].fmt()} of purchases (range {M['avoided_cost'].fmt_range()})" if "avoided_cost" in M else ""
        R.append(dict(theme="circularity", title="Extend garment life with repair",
                      text=f"{M['repairs'].fmt()} completed; at the selected assumption that postpones {M['postponed'].fmt()}{extra}. Discuss repair-heavy products and whether damage prevention could cut repairs further.",
                      basis="postponed = repairs × factor (ESTIMATED, sensitivity-tested)"))
    if _have(M, "co2_service"):
        extra = f", plus {M['avoided_co2'].fmt()} of avoided product emissions (estimate)" if "avoided_co2" in M else ""
        R.append(dict(theme="emissions", title="Provide Scope 3 evidence",
                      text=f"Service emissions are {M['co2_service'].fmt()} lower than {bname}{extra}. Agree which of these the customer may use in its own reporting once real data replaces synthetic factors.",
                      basis="ALLOCATED + ESTIMATED; status shown per number"))
    if issues is not None and len(issues):
        keep = issues[issues.severity.isin(["ERROR", "WARNING"])]
        if len(keep):
            R.append(dict(theme="data", title="Agree data fixes that would firm up next year's review",
                          text=f"{(keep.severity == 'ERROR').sum()} error(s) and {(keep.severity == 'WARNING').sum()} warning(s) were found in the data, e.g. "
                               f"{'; '.join(keep.check.drop_duplicates().head(3))}. "
                               + (f"{len(log)} row(s) were excluded from the calculation. " if log is not None and len(log) else "")
                               + "Assign owners for the fixes before the next review.",
                          basis="validation report (all issues listed in the app and the deck)"))
    rank = {t: i for i, t in enumerate(themes)}
    return sorted(R, key=lambda r: rank.get(r["theme"], 50))


def narrative(customer: str, themes: list[str], M: dict, recs: list[dict]) -> str:
    """Hero story. A deterministic template, optionally rephrased by an LLM that is given the figures and told not to compute."""
    f = {k: m.fmt() for k, m in M.items()}
    top = next((t for t in themes if any(m.theme == t for m in M.values())), themes[0])
    lead = {
        "water": f"{f.get('water_saving','n/a')} of water and {f.get('energy_saving','n/a')} of energy were saved versus the chosen baseline (range for water: {M['water_saving'].fmt_range()})." if "water_saving" in M else "water data is not available.",
        "cost": f"garment utilisation is {f.get('utilisation','n/a')}" + (f" and repairs avoided about {f['avoided_cost']} of purchases ({M['avoided_cost'].fmt_range()})." if "avoided_cost" in M else "."),
        "emissions": f"service emissions are {f.get('co2_service','n/a')} below baseline" + (f", plus {f['avoided_co2']} avoided through repair." if "avoided_co2" in M else "."),
        "circularity": f"{f.get('repairs','n/a')} were completed" + (f" and {f['recycling_pct']} of textile waste is recycled or reused." if "recycling_pct" in M else "."),
        "service": f"{f.get('ontime','n/a')} of service cycles were on time" + (f" at {f['cycle_hours']} average turnaround" if "cycle_hours" in M else "") + (f", with {f['requests']}." if "requests" in M else "."),
    }[top]
    scale = f"{f.get('kg','n/a')} of textiles washed across {f.get('sites','n/a')}"
    base = f"In the review period {customer} had {scale}. With the focus on **{top}**: {lead}" + (f" Next: {recs[0]['title'].lower()}." if recs else "")
    if providers.current() is not None:
        out = providers.complete_text("Rewrite this steering-committee summary in plain business English, 3 sentences. Keep EVERY number exactly as written, add none, "
                                      f"and say they are synthetic estimates. Text: {base}", 300)
        if out:
            import re
            nums = lambda s: sorted(re.findall(r"\d[\d\s.,]*", s))
            if set(nums(out)) <= set(nums(base)) | set(nums("synthetic")):   # reject if the LLM introduced any new number
                return out
    return base
