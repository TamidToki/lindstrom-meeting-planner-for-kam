"""Browser runner: execute the repo's own pipeline (Pyodide) on an uploaded workbook.

Mirrors astryx-app/scripts/export_data.py exactly, so an uploaded file produces
the same numbers as the desktop app and the built-in sample demo. Returns a JSON
string: {"ok": True, "payload": <same shape as data/demo-data.json>} or
{"ok": False, "errors": [<plain-English reasons the file failed the checks>]}.
Everything runs in the browser; the file never leaves the device.
"""

from __future__ import annotations

import ast
import json
import os
import sys

# openpyxl + et_xmlfile ship next to this file as vendor.zip (pure Python
# wheels, zipped - Python imports straight from it), so the Excel reader
# needs no package download at upload time. The unpacked vendor/ dir is
# used instead when present (local runs).
_BASE = os.path.dirname(__file__)
for _p in (os.path.join(_BASE, "vendor.zip"), os.path.join(_BASE, "vendor")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import numpy as np
import pandas as pd

EXPECTED_SHEETS = [
    "Customers", "Laundries", "Products", "Sites", "Industry_Priorities",
    "Service_Activity", "Repairs", "Service_Cycles", "Laundry_Resources",
    "Waste_Circularity", "Baselines", "Customer_Impacts", "Assumptions",
]


def num(v, nd=1):
    if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        return round(float(v), nd)
    return v


def maybe_list(v):
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


def fail(errors: list[str]) -> str:
    return json.dumps({"ok": False, "errors": errors})


def build_payload(T, issues, log, source_label: str) -> dict:
    import portfolio
    import metrics as mt
    import story

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

    return {
        "generatedFrom": source_label,
        "customers": customers,
        "portfolio": portfolio_rows,
        "sites": site_rows,
        "issues": issue_rows,
        "perCustomer": per_customer,
    }


def run_upload(path: str, filename: str) -> str:
    return run_uploads([path], [filename])


def run_uploads(paths, filenames) -> str:
    files = []
    for p, n in zip(paths, filenames):
        try:
            with open(p, "rb") as f:
                files.append((n, f.read()))
        except Exception:
            return fail([f"'{n}' could not be read by the browser. Try saving it again and re-uploading."])
    if not files:
        return fail(["No files reached the checker. Pick one or more .xlsx or .csv files and try again."])
    many = len(files) > 1

    try:
        import pipeline
        import data_loader as dl
    except Exception as e:
        return fail([f"The calculation engine did not load correctly ({type(e).__name__}: {str(e)[:120]}). Reload the page and try again."])

    read_errors = []
    try:
        raw = dl.read_workbooks(files, errors=read_errors)
        mapping = dl.auto_map(raw)
    except Exception as e:
        return fail([
            "A file could not be opened as an Excel workbook. Save it as .xlsx (or CSV) and try again.",
            f"Technical detail: {type(e).__name__}: {str(e)[:150]}",
        ])

    if read_errors:
        msgs = ["Some files could not be opened as Excel workbooks, so nothing was calculated. Save them as .xlsx (or CSV) and upload again:"]
        msgs += [f"{fn}: {msg}" for fn, msg in read_errors]
        return fail(msgs)

    if not raw:
        return fail([
            "The files opened, but no data sheets were found in them." if many else "The file opened, but no data sheets were found in it.",
            "Download the template below and copy your data into a workbook that looks like it.",
        ])

    included = [sm for sm in mapping.values() if sm.include and sm.table]
    if not included:
        sheets = sorted({rs.sheet for rs in raw.values()})
        return fail([
            ("The files opened, but none of their sheets matched the Lindstrom review format." if many
             else "The file opened, but none of its sheets matched the Lindstrom review format."),
            "Sheets found in your upload: " + ", ".join(sheets[:12]),
            "The checker recognises sheets like: " + ", ".join(EXPECTED_SHEETS[:8]) + " (and more).",
            "Download the template below and copy your data into its columns, then upload again.",
        ])

    if many:
        recognised = {raw[k].file for k, sm in mapping.items() if sm.include and sm.table}
        unused = [n for n in filenames if n not in recognised]
        if unused:
            return fail(["These files contain no recognised data sheets: " + ", ".join(unused),
                         "Nothing was calculated. Check these files against the template, or remove them and select the full set again."])

    try:
        V = pipeline.validate_mapping(raw, mapping)
        T, log = pipeline.finalize(V)
    except Exception as e:
        return fail([
            "Your sheets were recognised, but the data failed the checks while the tables were being built.",
            f"Technical detail: {type(e).__name__}: {str(e)[:150]}",
            "Compare your columns with the template below - a missing or renamed required column is the usual cause.",
        ])

    label = ("uploaded files: " if many else "uploaded file: ") + ", ".join(filenames)
    try:
        payload = build_payload(T, V["issues"], log, label)
    except Exception as e:
        return fail([
            "The checks passed, but calculating the review numbers failed.",
            f"Technical detail: {type(e).__name__}: {str(e)[:150]}",
        ])

    if not payload["customers"]:
        return fail([
            "The upload was read, but no customers were found in it.",
            "Make sure the workbook has a Customers sheet with at least one customer row, like the template below.",
        ])

    return json.dumps({"ok": True, "payload": payload, "issueCount": len(payload["issues"])})
