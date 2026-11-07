"""Anomalies: what is not working or not doing well for one customer, ranked by how much it matters.

RANKING RULE (shown to the user in the deck appendix and in START_HERE):
    size  = garments the finding touches (the site's allocated garments, or the product's)
    gap   = how far the value is from its reference, as a share of that reference (capped at 100 %)
    score = size x gap x weight
Reference: utilisation -> the customer's healthy range; on-time and requests -> the median of this customer's own sites;
repairs -> the customer's all-products rate. Weight 1.0, except utilisation ABOVE the range (0.3): heavy use is a question
about supply, not a failure. Only findings that clear a threshold are listed. Every number comes from the calculated tables."""
from __future__ import annotations
import numpy as np
import pandas as pd
import measures as ms

ABOVE_WEIGHT = 0.3
REPAIR_RATIO_MIN, REPAIR_MIN = 1.5, 10


def _n(x, d=0):
    return f"{x:,.{d}f}".replace(",", " ")


def find(S: pd.DataFrame, RI: pd.DataFrame | None, cid, lo: float, hi: float, limit: int | None = None) -> list[dict]:
    """S: this customer's site table (portfolio SA filtered). RI: repair intensity (all customers). -> ranked list of dicts."""
    out = []
    S = S.reset_index(drop=True)
    labels = list(S.site)

    def series(col):
        return [(r.site, float(getattr(r, col))) for r in S.itertuples() if pd.notna(getattr(r, col))]

    # ---- utilisation vs the customer's healthy range
    for r in S.dropna(subset=["utilisation"]).itertuples():
        v = float(r.utilisation)
        if lo <= v <= hi:
            continue
        below = v < lo
        gap = min(1.0, ((lo - v) / lo) if below else ((v - hi) / hi))
        w = 1.0 if below else ABOVE_WEIGHT
        out.append(dict(
            kind="utilisation", entity=r.site, metric="Garment use", unit="%", value=v, ref=(lo, hi), pieces=float(r.pieces), gap=gap, score=float(r.pieces) * gap * w,
            direction="below" if below else "above",
            short=f"{r.site}: garment use {'below' if below else 'above'} range",
            headline=f"{r.site} uses {v:.0f} % of its garments, {'below' if below else 'above'} the {lo:.0f} to {hi:.0f} % range",
            reference_text=f"Healthy range {lo:.0f} to {hi:.0f} %",
            question=(f"What changed at {r.site}: headcount, shift pattern, or a deliberate stock buffer?" if below else f"Is supply keeping up at {r.site}? Heavy use can mean shortages or wear."),
            chart=series("utilisation"), fmt="{:.0f} %"))
    # ---- on-time delivery vs the customer's other sites
    if S.ontime.notna().sum() >= 3:
        med = float(S.ontime.median())
        for r in S[S.get("flag_ontime", False) == True].itertuples():   # noqa: E712
            v = float(r.ontime)
            gap = min(1.0, max(0.0, (med - v) / med)) if med else 0
            if gap <= 0:
                continue
            out.append(dict(kind="ontime", entity=r.site, metric="On-time delivery", unit="%", value=v, ref=med, pieces=float(r.pieces), gap=gap, score=float(r.pieces) * gap,
                            short=f"{r.site}: late deliveries",
                            headline=f"On-time delivery at {r.site} is {v:.1f} %, against {med:.1f} % at this customer's other sites",
                            reference_text=f"Median of this customer's sites: {med:.1f} %",
                            question=f"What is different about deliveries at {r.site}: access, timing windows or routing?", chart=series("ontime"), fmt="{:.1f} %"))
    # ---- service requests per 1000 garments
    if S.requests_per_1000.notna().sum() >= 3:
        med = float(S.requests_per_1000.median())
        for r in S[S.get("flag_requests", False) == True].itertuples():  # noqa: E712
            v = float(r.requests_per_1000)
            gap = min(1.0, max(0.0, (v - med) / med)) if med else 0
            if gap <= 0:
                continue
            out.append(dict(kind="requests", entity=r.site, metric="Service requests per 1000 garments", unit="", value=v, ref=med, pieces=float(r.pieces), gap=gap, score=float(r.pieces) * gap,
                            short=f"{r.site}: many service requests",
                            headline=f"{r.site} raises {v:.0f} service requests per 1000 garments, against {med:.0f} typical for this customer",
                            reference_text=f"Median of this customer's sites: {med:.0f}",
                            question=f"What are the requests at {r.site} about, and are they the same few items?", chart=series("requests_per_1000"), fmt="{:.0f}"))
    # ---- repair-heavy products
    if RI is not None and len(RI):
        own = RI[RI.customer_id == cid]
        if len(own) and own.pieces.sum() > 0:
            overall = float(own.repairs.sum() / own.pieces.sum())
            for r in own.itertuples():
                if overall <= 0 or r.per_piece < overall * REPAIR_RATIO_MIN or r.repairs < REPAIR_MIN:
                    continue
                gap = min(1.0, r.per_piece / overall - 1)
                out.append(dict(kind="repairs", entity=str(r.product), metric="Repairs per garment per year", unit="", value=float(r.per_piece), ref=overall, pieces=float(r.pieces), gap=gap,
                                score=float(r.pieces) * gap, short=f"{r.product}: repaired often",
                                headline=f"{r.product} needs {r.per_piece:.2f} repairs per garment a year, against {overall:.2f} across all products",
                                reference_text=f"All products: {overall:.2f}",
                                question=f"Do wearers report fit or wear problems with {r.product}, and is the damage always the same?",
                                chart=[(str(p.product), float(p.per_piece)) for p in own.sort_values("per_piece", ascending=False).itertuples()], fmt="{:.2f}"))
    out.sort(key=lambda a: (-a["score"], a["kind"], a["entity"]))
    for i, a in enumerate(out, 1):
        a["rank"] = i
        a["id"] = f"{a['kind']}:{a['entity']}"
    return out[:limit] if limit else out


def rule_text() -> str:
    return ("Ranked largest first by: garments touched x how far the value is from its reference (capped at 100 %) x weight. "
            "References: utilisation against the customer's healthy range, on-time and service requests against the median of the customer's own sites, "
            f"repairs against the customer's all-products rate. Utilisation above the range counts at {ABOVE_WEIGHT:.0%} weight, because heavy use is a supply question, not a failure.")


def to_lines(items: list[dict], n: int = 5) -> list[str]:
    return [f"{a['rank']}. {a['headline']}. Affects about {_n(a['pieces'])} garments. Question to explore: {a['question']}" for a in items[:n]]
