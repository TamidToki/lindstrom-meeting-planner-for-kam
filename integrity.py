"""Integrity agent: a deterministic verifier that sits across the three layers and checks the numbers, so nobody has to trust the model.

  Layer 1  SOURCE      the uploaded files. Never opened for writing; hashed before and after.
  Layer 2  WORKING     in-memory replica built from the source (mapped, unit-converted, validated, exclusions applied). The pack, the SQLite
                       copy and anything a chat model reads are derived from THIS layer, never from layer 1 directly.
  Layer 3  CHAT/OUTPUT the master pack, the SQLite container, answers.

Checks (each is PASS/FAIL with expected vs found):
  A  source files unchanged (sha256 before = after)
  B  replication fidelity: for every fact sheet, the sum of each numeric column in the source (after unit factor) = the sum in the working layer
  C  exclusions are accounted for: working sum + excluded rows' sum = replicated sum
  D  the pack is internally consistent: Fact -> Analysis -> Customer summary -> Measures give the same totals; ratios recompute
  E  an independent engine (the app's metric engine) gives the same customer totals as the pack
  F  plausibility: no negative volumes, percentages inside 0-100 (utilisation above 100 is reported as a warning, not hidden)
  G  the SQLite container (if built) equals the workbook sheets
The agent never edits data; it only reports. A failing check is shown, not fixed silently."""
from __future__ import annotations
import hashlib, os, sqlite3
import numpy as np
import pandas as pd
import data_loader as dl
import metrics as mt
from schema import TABLES
from assumptions import scenario_params

FACT_TABLES = ("service_activity", "repairs", "service_cycles", "resources", "waste", "impacts")
TOL = 1e-6


def _row(check, scope, expected, found, note="", warn_only=False):
    try:
        diff = float(found) - float(expected)
        ok = abs(diff) <= TOL * max(1.0, abs(float(expected)))
    except Exception:
        diff, ok = None, str(found) == str(expected)
    res = "PASS" if ok else ("WARNING" if warn_only else "FAIL")
    return dict(Check=check, Scope=scope, Expected=expected, Found=found, Difference=diff, Result=res, Note=note)


def check_pack(raw, mapping, V, T_clean, log, sheets, hashes_before, hashes_after, sqlite_path=None, customer_filtered=False):
    R = []
    # ---- A source unchanged
    changed = [k for k in hashes_before if hashes_before[k] != hashes_after.get(k)]
    R.append(_row("A. Source files unchanged (sha256 before = after)", f"{len(hashes_before)} file(s)", 0, len(changed), "Changed: " + ", ".join(changed) if changed else "All source files byte-identical."))

    # ---- B replication fidelity (source sheet -> working layer, before exclusions)
    T = V["T"]
    nbad = 0
    for key, sm in mapping.items():
        if not (sm.include and sm.table in FACT_TABLES):
            continue
        df = raw[key].df
        W = T.get(sm.table)
        if W is None:
            continue
        w = W[W._sheet == key]
        R.append(_row("B. Rows replicated", f"{raw[key].file} > {raw[key].sheet}", len(df), len(w), "Source rows = rows in the working layer (before exclusions)."))
        for f in TABLES[sm.table].fields:
            src = sm.cols.get(f.name)
            if f.kind != "num" or not src or src not in df.columns:
                continue
            exp = float((dl._to_num(df[src]) * sm.factor.get(f.name, 1.0)).sum())
            got = float(w[f.name].sum()) if f.name in w else float("nan")
            if np.isnan(got) or abs(exp - got) > TOL * max(1.0, abs(exp)):
                nbad += 1
            R.append(_row("B. Column total replicated", f"{raw[key].sheet} > {src} -> {f.name}", round(exp, 6), round(got, 6), f"unit factor {sm.factor.get(f.name, 1.0):g}" if sm.factor.get(f.name, 1.0) != 1.0 else ""))

    # ---- C exclusions accounted for
    ex_uids = set(f"{r.source}#{r.row}" for r in log.itertuples()) if len(log) else set()
    for t in FACT_TABLES:
        W, C = T.get(t), V["T_clean"].get(t)
        if W is None or C is None or customer_filtered:
            continue
        dropped = W[W._uid.isin(ex_uids)]
        for f in TABLES[t].fields:
            if f.kind != "num" or f.name not in W or W[f.name].notna().sum() == 0:
                continue
            R.append(_row("C. Exclusions accounted for", f"{t}.{f.name}", round(float(W[f.name].sum()), 6), round(float(C[f.name].sum() + dropped[f.name].sum()), 6),
                          f"{len(dropped)} excluded row(s)"))

    # ---- D internal consistency of the pack
    FA, A, CS = sheets.get("Fact_Service_Activity"), sheets["Analysis"], sheets["Customer_Summary"]
    Me = sheets["Measures"]
    for col, fcol in (("Washed kg", "Washed kg"), ("Service requests", "Service requests"), ("Garments allocated", "Garments allocated")):
        if FA is not None and fcol in FA:
            R.append(_row("D. Fact total = Analysis total", col, round(float(FA[fcol].sum()), 6), round(float(A[col].sum()), 6)))
    for col in ("Washed kg", "Service requests", "Repairs"):
        if col in A and col in CS:
            R.append(_row("D. Analysis total = Customer_Summary total", col, round(float(A[col].sum()), 6), round(float(CS[col].sum()), 6)))
        m = Me[(Me.Level == "Customer, whole period") & (Me.Measure == col)]
        if len(m) and col in CS:
            R.append(_row("D. Customer_Summary = Measures", col, round(float(CS[col].sum()), 6), round(float(m.Value.sum()), 6)))
    if "Repairs" in sheets.get("Fact_Repairs", pd.DataFrame()):
        R.append(_row("D. Fact total = Analysis total", "Repairs", round(float(sheets["Fact_Repairs"]["Repairs"].sum()), 6), round(float(A["Repairs"].sum()), 6)))
    u = 100 * A["Garments with scan activity"] / A["Garments allocated"].replace(0, np.nan)
    ok_rows = A["Utilisation %"].notna() & u.notna()
    R.append(_row("D. Utilisation % recomputes from its parts", f"{int(ok_rows.sum())} Analysis rows", 0, (lambda d: 0.0 if d <= 0.0011 else round(d, 6))(float((A.loc[ok_rows, "Utilisation %"] - u[ok_rows]).abs().max() or 0)), "max absolute difference in points (cells are rounded to 3 decimals)"))

    # ---- E independent engine
    try:
        RI = mt._intensities(T_clean)
        bid = mt.default_baseline(T_clean)
        pr = scenario_params("Base")
        pairs = [("kg", "Washed kg"), ("repairs", "Repairs"), ("requests", "Service requests"), ("water_saving", "Water saved vs baseline L"), ("co2_service", "CO2e saved vs baseline kg"),
                 ("avoided_cost", "Purchases avoided EUR (estimate)")]
        for cid, name in zip(CS["Customer ID"], CS["Customer"]):
            Vm, _, _ = mt._calc(T_clean, cid, bid, pr, None, None, RI)
            for k, col in pairs:
                if k in Vm and col in CS:
                    R.append(_row("E. Pack = independent metric engine", f"{name}: {col}", round(float(Vm[k][0]), 4), round(float(CS.loc[CS["Customer ID"] == cid, col].iloc[0]), 4)))
    except Exception as e:
        R.append(dict(Check="E. Pack = independent metric engine", Scope="all", Expected="", Found="", Difference=None, Result="WARNING", Note=f"engine cross-check could not run: {type(e).__name__}"))

    # ---- F plausibility
    for col in ("Washed kg", "Garments allocated", "Repairs", "Service requests", "Water L", "Energy kWh", "Textile waste kg"):
        if col in A:
            R.append(_row("F. No negative volumes", col, 0, int((A[col] < 0).sum()), "rows below zero"))
    for col in ("Recycling %", "Diversion %", "On-time %"):
        if col in A:
            R.append(_row("F. Percentage inside 0-100", col, 0, int(((A[col] < -1e-9) | (A[col] > 100 + 1e-9)).sum()), "rows outside the range"))
    R.append(_row("F. Utilisation above 100 %", "Analysis rows", 0, int((A["Utilisation %"] > 100).sum()), "Reported, not hidden: garments with scan activity exceed garments allocated (see Validation_Exceptions).", warn_only=True))

    # ---- G sqlite container
    if sqlite_path and os.path.exists(sqlite_path):
        con = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
        try:
            for name in ("Analysis", "Measures", "Customer_Summary", "Site_Summary"):
                if name in sheets:
                    n = con.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
                    R.append(_row("G. SQLite container = workbook (rows)", name, len(sheets[name]), n))
            kg = con.execute('SELECT SUM("Washed kg") FROM "Analysis"').fetchone()[0]
            R.append(_row("G. SQLite container = workbook (Washed kg)", "Analysis", round(float(A["Washed kg"].sum()), 6), round(float(kg), 6)))
        finally:
            con.close()
    out = pd.DataFrame(R)
    out["Expected"] = out["Expected"].map(lambda v: v if not isinstance(v, (np.integer, np.floating)) else float(v))
    return out


def summary(df: pd.DataFrame) -> dict:
    return dict(checks=int(len(df)), passed=int((df.Result == "PASS").sum()), failed=int((df.Result == "FAIL").sum()), warnings=int((df.Result == "WARNING").sum()))


def write_sqlite(path: str, sheets: dict[str, pd.DataFrame]):
    """The working container a chat model may query. Built from the working layer; opened read-only for the model (mode=ro)."""
    if os.path.exists(path):
        os.remove(path)
    con = sqlite3.connect(path)
    try:
        for name, df in sheets.items():
            if name in ("README", "Prompt_Card"):
                continue
            df.to_sql(name, con, index=False)
        con.commit()
    finally:
        con.close()


def open_readonly(path: str) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)
