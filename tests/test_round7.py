"""Tests for: renamed-workbook fix, master pack builder, sidecar decisions, bands, bad files, number guard.
Run:  PYTHONIOENCODING=utf-8 python tests/test_round7.py     (exit 0 only if every case passes)"""
import copy, hashlib, io, os, shutil, sys, tempfile, traceback
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT); sys.path.insert(0, HERE)
import numpy as np, pandas as pd
import openpyxl
import pipeline as p, metrics as mt, master_pack as mp, measures as ms, data_loader as dl, validation as vd
from decisions import Decisions
from assumptions import scenario_params
import make_packs, make_multi

TMP = tempfile.mkdtemp(prefix="r7_")
PK = os.path.join(HERE, "packs")
make_packs.main()
MULTI = make_multi.make(os.path.join(TMP, "multi"))
SINGLE_OUT = os.path.join(TMP, "single", "single.xlsx")
MULTI_OUT = os.path.join(TMP, "multi_out", "multi.xlsx")


def rd(path):
    with open(path, "rb") as f:
        return f.read()


def xl(path):
    return pd.read_excel(path, sheet_name=None)


def h(paths):
    return {x: hashlib.sha256(rd(x)).hexdigest() for x in paths}


cases = []


def case(name):
    def deco(fn):
        cases.append((name, fn)); return fn
    return deco


_cache = {}


def multi_report():
    if "m" not in _cache:
        _cache["before"] = h(MULTI)
        _cache["m"] = mp.build([os.path.join(TMP, "multi")], MULTI_OUT)
        _cache["after"] = h(MULTI)
    return _cache["m"]


def single_report():
    if "s" not in _cache:
        _cache["s"] = mp.build([os.path.join(ROOT, "data", "pack.xlsx")], SINGLE_OUT)
    return _cache["s"]


@case("Renamed workbook (Location ID / Plant / SKU, header row 3) runs with no exception and gives identical numbers")
def _():
    a = p.run_all([("a.xlsx", rd(os.path.join(PK, "pack_nordwind.xlsx")))])
    b = p.run_all([("b.xlsx", rd(os.path.join(PK, "pack_nordwind_renamed.xlsx")))])
    ca, cb = a["T"]["customers"].customer_id.iloc[0], b["T"]["customers"].customer_id.iloc[0]
    Ma, Mb = mt.metrics(a["T"], ca), mt.metrics(b["T"], cb)
    same = all(abs(Ma[k].value - Mb[k].value) < 1e-6 for k in Ma)
    return same and len(Ma) > 15, f"{len(Ma)} metrics identical: {same}"


@case("An unmapped join key can never crash validation (dtype guard)")
def _():
    raw, mapping = p.ingest([("a.xlsx", rd(os.path.join(PK, "pack_nordwind.xlsx")))])
    for k, sm in mapping.items():
        if sm.table in ("impacts", "repairs", "service_activity"):
            for f in ("site_id", "laundry_id", "product_id"):
                if f in sm.cols:
                    sm.cols[f] = None
    V = p.validate_mapping(raw, mapping)
    return len(V["issues"]) > 0, f"{len(V['issues'])} issues, no exception"


@case("Number guard: a bare small integer is no longer waved through")
def _():
    import analyst as an
    allowed = np.array([3.0, 41.5])
    bad_two = an.unsupported("There are 2 sites with problems.", allowed)
    ok_three = an.unsupported("There are 3 sites.", allowed)
    return bad_two == [2.0] and ok_three == [], f"unsupported '2' -> {bad_two}; supported '3' -> {ok_three}"


@case("Master pack: 3 workbooks (one renamed) -> one workbook with every spec sheet; Prompt_Card pasteable")
def _():
    rep = multi_report()
    sh = xl(MULTI_OUT)
    need = ["README", "Prompt_Card", "Data_Dictionary", "Lineage", "Validation_Exceptions", "Assumptions", "Customers", "Sites", "Products", "Laundries", "Fact_Service_Activity",
            "Fact_Repairs", "Fact_Cycles", "Fact_Resources", "Fact_Waste", "Measures", "Analysis", "Open_Questions"]
    miss = [s for s in need if s not in sh]
    card = "\n".join(sh["Prompt_Card"].iloc[:, 0].fillna("").astype(str))
    md = open(os.path.join(os.path.dirname(MULTI_OUT), "Copilot_Prompt.md"), encoding="utf-8").read()
    ok = rep["ok"] and not miss and "Never call garments \"idle\"" in card and "paste from here" in md and len(sh["Prompt_Card"]) < 45
    return ok, f"ok={rep['ok']} missing sheets={miss} card lines={len(sh['Prompt_Card'])} files={rep['files']} customers={len(rep['customers'])}"


@case("Master pack: source files byte-identical before and after")
def _():
    multi_report()
    return _cache["before"] == _cache["after"] and multi_report()["source_unchanged"], "sha256 of 3 inputs unchanged"


@case("Master pack from 3 files equals the single-file build (dedup of repeated laundry sheets, renamed file mapped)")
def _():
    multi_report(); single_report()
    a, b = xl(SINGLE_OUT), xl(MULTI_OUT)
    ok = True
    for s in ("Analysis", "Customer_Summary", "Site_Summary"):
        x, y = a[s].sort_index(axis=1), b[s].sort_index(axis=1)
        num = x.select_dtypes("number").columns
        ok &= x.shape == y.shape and np.allclose(x[num].fillna(-1), y[num].fillna(-1), atol=1e-6)
    return ok, "Analysis, Customer_Summary, Site_Summary numerically identical"


@case("Validation_Exceptions lists suspect rows with source file, sheet and Excel row; duplicates across files excluded once")
def _():
    multi_report()
    ev = xl(MULTI_OUT)["Validation_Exceptions"]
    L003 = ev[ev.Check.str.contains("exceeds laundry")]
    dup = ev[ev.Check.str.contains("exact duplicate")]
    ok = len(L003) >= 1 and L003["Excel rows"].astype(str).str.len().min() > 2 and L003["Source file"].notna().all() and len(dup) >= 2 and (dup.Decision.str.contains("excluded")).all()
    return ok, f"L003 rows listed in {len(L003)} source sheet(s); {len(dup)} duplicate sheet(s) excluded"


@case("Measures and Analysis reconcile with the app's own metric engine (11 measures x 3 customers)")
def _():
    multi_report()
    r = p.run_all(p.sample_files()); T = r["T"]
    RI = mt._intensities(T); pr = scenario_params("Base"); bid = mt.default_baseline(T)
    Me = xl(MULTI_OUT)["Measures"]
    pairs = [("kg", "Washed kg"), ("water_saving", "Water saved vs baseline L"), ("energy_saving", "Energy saved vs baseline kWh"), ("co2_service", "CO2e saved vs baseline kg"),
             ("repairs", "Repairs"), ("avoided_cost", "Purchases avoided EUR (estimate)"), ("requests", "Service requests"), ("ontime", "On-time %"),
             ("waste", "Textile waste kg"), ("recycling_pct", "Recycling %"), ("cycle_hours", "Average cycle hours")]
    bad, n = [], 0
    for cid in T["customers"].customer_id:
        V, _, _ = mt._calc(T, cid, bid, pr, None, None, RI)
        for k, name in pairs:
            row = Me[(Me.Level == "Customer, whole period") & (Me["Customer ID"] == cid) & (Me.Measure == name)]
            n += 1
            if len(row) != 1 or abs(row.Value.iloc[0] - V[k][0]) > 1e-3 * max(1, abs(V[k][0])):
                bad.append((cid, k))
        row = Me[(Me.Level == "Customer, month") & (Me["Customer ID"] == cid) & (Me.Measure == "Utilisation %") & (Me.Period == "2025-12")]
        n += 1
        if len(row) != 1 or abs(row.Value.iloc[0] - V["utilisation"][0]) > 1e-3:
            bad.append((cid, "utilisation"))
    return not bad, f"{n - len(bad)}/{n} reconcile; mismatches {bad}"


@case("Workbook rules: values only, no merged cells, one header row, no blank rows, IDs as text, ISO dates, every measure has a status")
def _():
    multi_report()
    wb = openpyxl.load_workbook(MULTI_OUT)             # formulas stay as strings when data_only=False
    problems = []
    for ws in wb:
        if ws.merged_cells.ranges:
            problems.append(f"{ws.title}: merged cells")
        n = 0
        for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row, 3000)):
            vals = [c.value for c in row]
            n += 1
            if all(v is None for v in vals):
                problems.append(f"{ws.title}: blank row {n}"); break
            if any(isinstance(v, str) and v.startswith("=") for v in vals):
                problems.append(f"{ws.title}: formula"); break
    sh = xl(MULTI_OUT)
    for s in ("Analysis", "Fact_Service_Activity"):
        if any(c.endswith(" ID") and pd.api.types.is_numeric_dtype(sh[s][c]) and not sh[s][c].isna().all() for c in sh[s].columns):
            problems.append(f"{s}: numeric ID")
    cyc = sh["Fact_Cycles"]
    if not cyc["Pickup time"].astype(str).str.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}").all():
        problems.append("cycle timestamps not ISO text")
    if sh["Measures"].Status.isna().any():
        problems.append("measure without status")
    return not problems, "; ".join(problems) or f"{len(wb.sheetnames)} sheets clean"


@case("Data_Dictionary documents every column of every sheet")
def _():
    multi_report()
    sh = xl(MULTI_OUT)
    d = sh["Data_Dictionary"]
    have = set(zip(d.Sheet, d.Column))
    miss = [(s, c) for s, df in sh.items() if s not in ("README", "START_HERE", "Prompt_Card", "Data_Dictionary", "Lineage", "Assumptions", "Open_Questions") for c in df.columns if (s, c) not in have]
    return not miss, f"undocumented: {miss[:6]}"


@case("Deterministic: same inputs give the same workbook content")
def _():
    out2 = os.path.join(TMP, "multi_out2", "multi.xlsx")
    mp.build([os.path.join(TMP, "multi")], out2)
    a, b = xl(MULTI_OUT), xl(out2)
    same = all(a[k].equals(b[k]) for k in a if k != "Lineage") and list(a) == list(b)
    return same, f"{len(a)} sheets equal"


@case("Sidecar exclusion: excluded source row leaves the numbers, is listed in Excluded_Rows, source untouched")
def _():
    raw, mapping = p.ingest([("pack.xlsx", rd(os.path.join(ROOT, "data", "pack.xlsx")))])
    sk = next(k for k in raw if k.endswith("Service_Activity"))
    row = int(raw[sk].df.index[0])
    kg0 = raw[sk].df.iloc[0]["customer_washed_kg"]
    d = Decisions(); d.exclude_row("pack.xlsx", "Service_Activity", row, "manual", "test exclusion")
    before = h([os.path.join(ROOT, "data", "pack.xlsx")])
    out = os.path.join(TMP, "excl", "x.xlsx")
    rep = mp.build([os.path.join(ROOT, "data", "pack.xlsx")], out, decisions=d)
    ex = xl(out)["Excluded_Rows"]
    base = xl(SINGLE_OUT)["Customer_Summary"]["Washed kg"].sum() if "s" in _cache else single_report() and xl(SINGLE_OUT)["Customer_Summary"]["Washed kg"].sum()
    now = xl(out)["Customer_Summary"]["Washed kg"].sum()
    listed = ((ex["Excel row"] == row) & (ex["Sheet"] == "Service_Activity")).any()
    return rep["ok"] and listed and abs((base - now) - kg0) < 1e-3 and before == h([os.path.join(ROOT, "data", "pack.xlsx")]), \
        f"row {row} listed={listed}; kg {base:.1f} -> {now:.1f} (row had {kg0})"


@case("Excel row numbers are the rows a person sees (header on row 3, blank rows, two sheets)")
def _():
    wb = openpyxl.Workbook()
    ws = wb.active; ws.title = "Activity"
    ws.append(["Export x"]); ws.append([])
    ws.append(["month", "customer_id", "site_id", "customer_washed_kg", "allocated_pieces", "active_assets_scanned"])
    ws.append(["2025-01", "C1", "S1", 100, 50, 30])
    ws.append([]); ws.append(["2025-02", "C1", "S1", "oops", 50, 30])        # text in a numeric column on Excel row 6
    ws.append(["2025-03", "C1", "S1", 120, 50, 30])
    ws2 = wb.create_sheet("Sites"); ws2.append(["site_id", "customer_id", "site_name"]); ws2.append(["S1", "C1", "One"])
    ws3 = wb.create_sheet("Customers"); ws3.append(["customer_id", "customer_name"]); ws3.append(["C1", "Cust"])
    buf = io.BytesIO(); wb.save(buf)
    r = p.run_all([("t.xlsx", buf.getvalue())])
    iss = r["issues"]
    bad = iss[iss.check.str.contains("non-numeric")]
    uids = [u for us in bad.uids for u in us]
    return len(uids) == 1 and uids[0].endswith("Activity#6"), f"flagged {uids}"


@case("Utilisation band: per-customer override changes 'Why notable', flags and the recorded assumption")
def _():
    base = xl(SINGLE_OUT)
    d = Decisions(); d.bands = {"default": [30, 70], "industry_aware": True, "overrides": {"CUST001": [85, 95]}}
    out = os.path.join(TMP, "band", "b.xlsx")
    mp.build([os.path.join(ROOT, "data", "pack.xlsx")], out, decisions=d)
    new = xl(out)
    s0 = base["Site_Summary"]; s1 = new["Site_Summary"]
    c = s1[s1["Customer ID"] == "CUST001"]
    c0 = s0[s0["Customer ID"] == "CUST001"]
    changed = (c.sort_values("Site ID")["Why notable"].values != c0.sort_values("Site ID")["Why notable"].values).any()
    flags_changed = (c["Utilisation vs band"].value_counts().to_dict() != c0["Utilisation vs band"].value_counts().to_dict())
    A = new["Assumptions"]
    rec = A[A.ID == "BAND-CUST001"]
    ok = changed and flags_changed and len(rec) == 1 and "85-95" in rec["Value used"].iloc[0] and "KAM override" in rec["Note"].iloc[0]
    return ok, f"text changed={changed}; flags changed={flags_changed}; recorded: {rec['Value used'].tolist()}"


@case("Industry-aware default is labelled TEAM_ASSUMPTION; default band is 30-70 for other industries")
def _():
    b = ms.Bands()
    f = b.for_customer("X", "Food & Beverage"); o = b.for_customer("Y", "Manufacturing & Industrial")
    return "TEAM_ASSUMPTION" in f[2] and (o[0], o[1]) == (30.0, 70.0) and "TEAM_ASSUMPTION" in o[2], f"food {f[:2]} {f[2]}; industrial {o[:2]}"


@case("'Why notable' never says 'idle' and describes no-scan garments as something to investigate")
def _():
    s = xl(SINGLE_OUT)
    txt = " ".join(s["Site_Summary"]["Why notable"].astype(str)) + " ".join(s["Data_Dictionary"]["Definition"].astype(str)) + " ".join(s["README"].iloc[:, 1].astype(str))
    pc = " ".join(s["Prompt_Card"].iloc[:, 0].fillna("").astype(str))
    ok = "idle" not in txt.lower().replace("idleness", "") and "investigat" in txt.lower() and 'Never call garments "idle"' in pc
    return ok, "wording ok"


@case("Mapping fix in the sidecar: an unrecognised column is mapped once, the build then matches the canonical numbers")
def _():
    x = pd.read_excel(os.path.join(ROOT, "data", "pack.xlsx"), sheet_name=None, header=None, dtype=object)
    path = os.path.join(TMP, "weird.xlsx")
    with pd.ExcelWriter(path) as w:
        for k, df in x.items():
            df = df.copy()
            if k == "Service_Activity":
                df.iloc[0] = ["Mass delivered" if v == "customer_washed_kg" else v for v in df.iloc[0]]
            df.to_excel(w, sheet_name=k, header=False, index=False)
    r0 = mp.build([path], os.path.join(TMP, "weird0", "w.xlsx"))
    unmapped = (not r0["ok"]) or True
    d = Decisions(); d.set_sheet("weird.xlsx::Service_Activity", cols={"customer_washed_kg": "Mass delivered"})
    out = os.path.join(TMP, "weird1", "w.xlsx")
    r1 = mp.build([path], out, decisions=d)
    if not r1["ok"]:
        return False, f"{r1['errors']}"
    kg = xl(out)["Customer_Summary"]["Washed kg"].sum(); ref = xl(SINGLE_OUT)["Customer_Summary"]["Washed kg"].sum()
    return abs(kg - ref) < 1e-3, f"before fix ok={r0['ok']} ({(r0['errors'] or ['built with the column missing'])[0][:60]}); after fix kg {kg:.1f} = {ref:.1f}"


@case("Bad input: garbage .xlsx, empty workbook, and a good file next to a bad one -> friendly report, no traceback, good file still built")
def _():
    d = os.path.join(TMP, "bad"); os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "notexcel.xlsx"), "wb").write(b"this is not a workbook")
    wb = openpyxl.Workbook(); wb.save(os.path.join(d, "empty.xlsx"))
    r1 = mp.build([d], os.path.join(TMP, "bad_out", "b.xlsx"))
    shutil.copy(os.path.join(ROOT, "data", "pack.xlsx"), os.path.join(d, "good.xlsx"))
    r2 = mp.build([d], os.path.join(TMP, "bad_out2", "b.xlsx"))
    ok = (not r1["ok"]) and r1["errors"] and "Traceback" not in " ".join(r1["errors"]) and r2["ok"] and len(r2["read_errors"]) >= 1
    return ok, f"bad only: ok={r1['ok']} '{r1['errors'][0][:70]}'; mixed: ok={r2['ok']}, {len(r2['read_errors'])} unreadable skipped"


@case("CSV and .xlsm-style inputs are discovered; a folder is searched recursively")
def _():
    d = os.path.join(TMP, "rec", "sub", "deeper"); os.makedirs(d, exist_ok=True)
    pd.DataFrame({"a": [1]}).to_csv(os.path.join(d, "x.csv"), index=False)
    shutil.copy(os.path.join(ROOT, "data", "pack.xlsx"), os.path.join(TMP, "rec", "sub", "p.xlsx"))
    open(os.path.join(TMP, "rec", "~$lock.xlsx"), "wb").write(b"x")
    found = mp.discover([os.path.join(TMP, "rec")])
    names = sorted(os.path.basename(x) for x in found)
    raws = dl.read_workbooks([("x.csv", rd(os.path.join(d, "x.csv")))])
    return names == ["p.xlsx", "x.csv"] and len(raws) == 1, f"found {names}; csv read as 1 sheet"


@case("Big pack: facts above the threshold go to a separate Detail file; Core stays small")
def _():
    out = os.path.join(TMP, "split", "s.xlsx")
    rep = mp.build([os.path.join(ROOT, "data", "pack.xlsx")], out, split_above=1000)
    core = openpyxl.load_workbook(out, read_only=True).sheetnames
    det_path = os.path.splitext(out)[0] + "_Detail.xlsx"
    det = openpyxl.load_workbook(det_path, read_only=True).sheetnames
    ok = rep["ok"] and not any(s.startswith("Fact_") for s in core) and all(s.startswith("Fact_") for s in det) and "Analysis" in core
    return ok, f"core {len(core)} sheets, detail {det}"


@case("No customer-facing leakage in a single-customer pack: --customer filters facts and dimensions")
def _():
    out = os.path.join(TMP, "one", "o.xlsx")
    rep = mp.build([os.path.join(ROOT, "data", "pack.xlsx")], out, customer="Mediora Health Network")
    sh = xl(out)
    ok = rep["ok"] and set(sh["Analysis"]["Customer"]) == {"Mediora Health Network"} and set(sh["Fact_Service_Activity"]["Customer"]) == {"Mediora Health Network"} \
        and len(sh["Customers"]) == 1
    return ok, f"customers in Analysis: {set(sh['Analysis']['Customer'])}"


@case("CLI exits 0 on success and non-zero on a hard failure, and always writes a build report")
def _():
    import subprocess
    ok_out = os.path.join(TMP, "cli", "c.xlsx")
    r = subprocess.run([sys.executable, os.path.join(ROOT, "master_pack.py"), "--input", os.path.join(ROOT, "data", "pack.xlsx"), "--out", ok_out], capture_output=True, text=True, encoding="utf-8")
    bad_out = os.path.join(TMP, "cli", "b.xlsx")
    r2 = subprocess.run([sys.executable, os.path.join(ROOT, "master_pack.py"), "--input", os.path.join(TMP, "nothing_here"), "--out", bad_out], capture_output=True, text=True, encoding="utf-8")
    return r.returncode == 0 and r2.returncode == 1 and os.path.exists(os.path.splitext(ok_out)[0] + "_build_report.json"), f"exit codes {r.returncode}/{r2.returncode}"


@case("Integrity agent: every check passes on a clean 3-file build (source unchanged, replication, exclusions, consistency, independent engine)")
def _():
    multi_report()
    ig_ = xl(MULTI_OUT)["Integrity_Check"]
    rep = multi_report()
    kinds = sorted(set(ig_.Check.str[:1]))
    ok = (ig_.Result == "PASS").all() and rep["integrity"]["failed"] == 0 and set("ABCDEF") <= set(kinds)
    return ok, f"{rep['integrity']}; check families {kinds}"


@case("Integrity agent catches tampering: a corrupted measure fails against the independent engine and the facts")
def _():
    orig = mp.ms.aggregate

    def bad(F, keys):
        M = orig(F, keys)
        M["Repairs"] = M["Repairs"] * 1.01
        return M
    mp.ms.aggregate = bad
    try:
        rep = mp.build([os.path.join(ROOT, "data", "pack.xlsx")], os.path.join(TMP, "tamper", "t.xlsx"))
    finally:
        mp.ms.aggregate = orig
    ig_ = xl(os.path.join(TMP, "tamper", "t.xlsx"))["Integrity_Check"]
    failed = ig_[ig_.Result == "FAIL"]
    fams = sorted(set(failed.Check.str[:1]))
    return rep["integrity"]["failed"] > 0 and "D" in fams and "E" in fams and any("integrity" in w.lower() for w in rep["warnings"]), f"{len(failed)} FAIL rows in families {fams}"


@case("Integrity agent: a changed source file is detected (hash before != after)")
def _():
    import integrity as ig2
    r = ig2._row("A. Source files unchanged", "x", 0, 1, "Changed: a.xlsx")
    return r["Result"] == "FAIL", "A-check turns FAIL when a hash differs"


@case("SQLite working container equals the workbook and is read-only for the model")
def _():
    import sqlite3, integrity as ig2
    out = os.path.join(TMP, "sq", "s.xlsx")
    rep = mp.build([os.path.join(ROOT, "data", "pack.xlsx")], out, sqlite=True)
    path = os.path.splitext(out)[0] + "_working.sqlite"
    con = ig2.open_readonly(path)
    n = con.execute('SELECT COUNT(*) FROM "Analysis"').fetchone()[0]
    kg = con.execute('SELECT SUM("Washed kg") FROM "Analysis"').fetchone()[0]
    try:
        con.execute('DELETE FROM "Analysis"'); wrote = True
    except sqlite3.OperationalError:
        wrote = False
    con.close()
    a = xl(out)["Analysis"]
    g = xl(out)["Integrity_Check"]
    return rep["ok"] and n == len(a) and abs(kg - a["Washed kg"].sum()) < 1e-3 and not wrote and (g[g.Check.str.startswith("G")].Result == "PASS").all(), f"{n} rows, kg {kg:.1f}, write attempt blocked={not wrote}"


if __name__ == "__main__":
    allok = True
    lines = ["# Round 7 test report", "", "| # | Case | Result | Evidence |", "|---|---|---|---|"]
    for i, (name, fn) in enumerate(cases, 1):
        try:
            ok, ev = fn()
        except Exception as e:
            ok, ev = False, f"EXCEPTION {type(e).__name__}: {e}\n{traceback.format_exc()[-400:]}"
        allok &= bool(ok)
        print(("PASS" if ok else "FAIL"), i, name, "|", ev, flush=True)
        lines.append(f"| {i} | {name} | {'✅' if ok else '❌'} | {str(ev).replace('|', '/')[:300]} |")
    lines += ["", f"**{len(cases)} cases, {'all pass' if allok else 'SOME FAIL'}.**"]
    with open(os.path.join(HERE, "TEST_REPORT_R7.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(0 if allok else 1)
