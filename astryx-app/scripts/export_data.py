"""Export the meeting planner's computed results into JSON for the Astryx web app.

Run from the repo root:

    python astryx-app/scripts/export_data.py

Uses the repo's own headless pipeline (pipeline.run_all on the synthetic
sample pack) and its deterministic metrics engine - the same numbers the
Streamlit app shows. Writes astryx-app/public/data/demo-data.json, committed
so the web demo runs without Python. Synthetic sample data, not real customer
numbers.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import pipeline  # noqa: E402
import portfolio  # noqa: E402
import metrics as mt  # noqa: E402
import story  # noqa: E402

OUT = REPO / "astryx-app" / "public" / "data" / "demo-data.json"


def num(v, nd=1):
    if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        return round(float(v), nd)
    return v


def maybe_list(v):
    """Opportunity fields are sometimes a stringified python list."""
    if isinstance(v, str) and v.startswith("[") and v.endswith("]"):
        try:
            out = ast.literal_eval(v)
            if isinstance(out, list):
                return [str(x) for x in out]
        except (ValueError, SyntaxError):
            pass
    return v


def metric_json(m) -> dict:
    return {
        "key": m.key,
        "label": m.label,
        "value": num(m.value, 2),
        "unit": m.unit,
        "theme": m.theme,
        "status": m.status,
        "formula": m.formula,
        "note": m.note,
        "low": num(m.low, 2),
        "high": num(m.high, 2),
        "caveat": getattr(m, "caveat", "") or "",
        "inputStatus": getattr(m, "input_status", "") or "",
    }


def main() -> None:
    R = pipeline.run_all(pipeline.sample_files())
    T, issues, log = R["T"], R["issues"], R["log"]

    customers_df = portfolio.customers(T)
    portfolio_df, sites_df = portfolio.portfolio(T)
    RI = portfolio.repair_intensity(T)

    customers = []
    for _, c in customers_df.iterrows():
        customers.append({
            "id": c["customer_id"],
            "name": c["customer"],
            "industry": c["industry"],
            "segment": c["segment"],
            "topics": [t.strip() for t in str(c["topics"]).split("|") if t.strip()],
        })

    portfolio_rows = []
    for _, r in portfolio_df.iterrows():
        portfolio_rows.append({
            "customerId": r["customer_id"],
            "customer": r["customer"],
            "industry": r["industry"],
            "segment": r["segment"],
            "sites": int(r["sites"]),
            "countries": r["countries"],
            "kg": num(r["kg"], 0),
            "utilisation": num(r["utilisation"], 1),
            "ontime": num(r["ontime"], 1),
            "requestsPer1000": num(r["requests_per_1000"], 1),
            "repairsPer100": num(r["repairs_per_100"], 1),
            "sitesAttention": int(r["sites_attention"]),
            "waterSaving": num(r["water_saving"], 0),
            "waterLow": num(r["water_low"], 0),
            "waterHigh": num(r["water_high"], 0),
            "co2Saving": num(r["co2_saving"], 0),
            "shareKg": num(r["share_of_portfolio_kg"], 1),
        })

    site_rows = []
    for _, s in sites_df.iterrows():
        site_rows.append({
            "siteId": s["site_id"],
            "site": s["site"],
            "customerId": s["customer_id"],
            "customer": s["customer"],
            "country": s["country"],
            "type": s["type"],
            "kg": num(s["kg"], 0),
            "utilisation": num(s["utilisation"], 1),
            "ontime": num(s["ontime"], 1),
            "requests": num(s["requests"], 0),
            "repairs": num(s["repairs"], 0),
            "recyclingPct": num(s.get("recycling_pct"), 1),
            "attention": bool(s["attention"]) if not pd.isna(s["attention"]) else False,
            "nFlags": int(s["n_flags"]) if not pd.isna(s["n_flags"]) else 0,
        })

    issue_rows = []
    for _, i in issues.iterrows():
        issue_rows.append({
            "severity": i["severity"],
            "check": i["check"],
            "table": i["table"],
            "location": str(i["location"]),
            "explanation": i["explanation"],
            "fix": i["fix"],
        })

    per_customer = {}
    for c in customers:
        cid = c["id"]
        M = mt.metrics(T, cid)
        S = mt.site_table(T, cid)
        monthly = portfolio.monthly(T, cid)
        opps = portfolio.opportunities(T, cid, M, S, RI)
        themes = story.industry_order(T, c["industry"])
        recs = story.recommendations(M, S, themes, M.baseline_name if hasattr(M, "baseline_name") else "baseline", issues, log)
        try:
            narrative = story.narrative(c["name"], themes, M, recs)
        except Exception:
            narrative = ""

        per_customer[cid] = {
            "metrics": [metric_json(m) for m in M.values()],
            "monthly": [
                {
                    "month": r["month"],
                    "kg": num(r["kg"], 0),
                    "requests": num(r["requests"], 0),
                    "utilisation": num(r["utilisation"], 1),
                    "repairs": num(r["repairs"], 0),
                }
                for _, r in monthly.iterrows()
            ],
            "opportunities": [
                {
                    "id": o.get("id"),
                    "theme": o.get("theme"),
                    "title": o.get("title"),
                    "hypothesis": o.get("hypothesis"),
                    "sizing": o.get("sizing"),
                    "status": o.get("status"),
                    "evidence": maybe_list(o.get("evidence_customer")),
                    "assumptions": maybe_list(o.get("assumptions")),
                    "confirm": maybe_list(o.get("confirm")),
                    "caveat": o.get("caveat") or "",
                }
                for o in opps
            ],
            "recommendations": [
                {"theme": r.get("theme"), "title": r.get("title"), "text": r.get("text"), "basis": r.get("basis")}
                for r in recs
            ],
            "narrative": narrative,
        }

    payload = {
        "generatedFrom": "synthetic sample pack (data/pack.xlsx)",
        "customers": customers,
        "portfolio": portfolio_rows,
        "sites": site_rows,
        "issues": issue_rows,
        "perCustomer": per_customer,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, separators=(",", ":")))
    print(f"Wrote {OUT} ({OUT.stat().st_size/1024:.0f} KiB): "
          f"{len(customers)} customers, {len(site_rows)} sites, {len(issue_rows)} issues")


if __name__ == "__main__":
    main()
