"""Break the sample pack on purpose and prove the validation catches each break.
Run:  python tests/test_breaks.py      (writes tests/TEST_REPORT.md)"""
import io, os, sys, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np, pandas as pd
import pipeline as pl, metrics as mt

ROOT = os.path.join(os.path.dirname(__file__), "..")
PACK = pd.read_excel(os.path.join(ROOT, "data", "pack.xlsx"), sheet_name=None)
CID = "CUST001"


def pack():
    return {k: v.copy() for k, v in PACK.items()}


def xlsx(sheets: dict) -> bytes:
    b = io.BytesIO()
    with pd.ExcelWriter(b, engine="openpyxl") as w:
        for n, d in sheets.items():
            d.to_excel(w, sheet_name=n[:31], index=False)
    return b.getvalue()


def one(sheets, name="broken.xlsx"):
    return [(name, xlsx(sheets))]


def run(files):
    r = pl.run_all(files)
    return r


def has(r, check, table=None, contains=None):
    I = r["issues"]
    m = I[I.check == check]
    if table:
        m = m[m.table.str.contains(table)]
    if contains:
        m = m[(m.location + " " + m.explanation + " " + m.scope).str.contains(contains)]
    return m


BASE = run(one(pack()))
BASE_M = mt.metrics(BASE["T"], CID)
cases = []


def case(name, what):
    def deco(fn):
        cases.append((name, what, fn))
        return fn
    return deco


@case("Remove site S005 from Service_Activity only", "site exists in Sites/Repairs/Cycles but not in activity")
def _():
    s = pack(); s["Service_Activity"] = s["Service_Activity"][s["Service_Activity"].site_id != "S005"]
    r = run(one(s)); m = has(r, "site has no rows in sheet", "service_activity", "S005")
    k = has(r, "washed kg differs between sheets")
    return len(m) == 1 and len(k) == 1, f"{m.severity.iloc[0] if len(m) else '-'} 'site has no rows' + ERROR kg totals differ vs impacts"


@case("Remove site S005 from Sites only", "orphan rows in 4 data sheets")
def _():
    s = pack(); s["Sites"] = s["Sites"][s["Sites"].site_id != "S005"]
    r = run(one(s)); m = has(r, "site missing from site master", None, "S005")
    tabs = sorted(m.table)
    ex = len(r["log"]); sites = mt.metrics(r["T"], CID)["sites"].value
    return len(m) == 4 and ex > 0 and sites == 23, f"{tabs}; {ex} orphan rows auto-excluded; calculation now sees {int(sites)} sites"


@case("Change a total: Customer_Impacts washed kg ×1.25 for site S008", "totals disagree between two sheets")
def _():
    s = pack(); I = s["Customer_Impacts"]; I.loc[I.site_id == "S008", "customer_washed_kg"] *= 1.25
    r = run(one(s)); m = has(r, "washed kg differs between sheets")
    return len(m) == 1 and "S008" in m.iloc[0].scope, m.iloc[0].location[:110] if len(m) else "-"


@case("Change a control total: Sample_Output 'Washed kg 2025' → 450 000", "reference total ≠ detail rows")
def _():
    s = pack(); o = s["Sample_Output"]; o.loc[o.metric == "Washed kg 2025", "value"] = 450000
    r = run(one(s)); m = has(r, "control total does not match calculation")
    return len(m) == 1 and "Washed kg" in m.iloc[0].location, m.iloc[0].location[:110] if len(m) else "-"


@case("Delete 400 repair rows (Repairs 2025 control total now wrong)", "detail rows deleted, control total stale")
def _():
    s = pack(); R = s["Repairs"]; s["Repairs"] = R[~((R.customer_id == CID) & (R.index % 9 == 0))]
    r = run(one(s)); m = has(r, "control total does not match calculation")
    return len(m) == 1 and "Repairs" in m.iloc[0].location, m.iloc[0].location[:110] if len(m) else "-"


@case("Rename column repair_count → 'Repairs completed'", "valid rename must still map and give identical numbers")
def _():
    s = pack(); s["Repairs"] = s["Repairs"].rename(columns={"repair_count": "Repairs completed"})
    r = run(one(s)); sm = next(v for v in r["mapping"].values() if v.table == "repairs")
    M = mt.metrics(r["T"], CID)
    return sm.cols["repair_count"] == "Repairs completed" and abs(M["repairs"].value - BASE_M["repairs"].value) < 1e-6 and len(r["issues"]) == len(BASE["issues"]), \
        f"mapped repair_count ← '{sm.cols['repair_count']}', repairs = {M['repairs'].value:,.0f}, no new issues"


@case("Rename column repair_count → 'qty_xyz'", "unrecognisable required column")
def _():
    s = pack(); s["Repairs"] = s["Repairs"].rename(columns={"repair_count": "qty_xyz"})
    r = run(one(s)); m = has(r, "missing required column", "repairs", "repair_count")
    M = mt.metrics(r["T"], CID)
    return len(m) == 1 and "repairs" in M.missing, f"ERROR raised; repair metrics reported as not calculable: {M.missing.get('repairs')}"


@case("Add 30 exact duplicate rows to Service_Activity", "double counting")
def _():
    s = pack(); A = s["Service_Activity"]; s["Service_Activity"] = pd.concat([A, A.iloc[100:130]])
    r = run(one(s)); m = has(r, "exact duplicate rows", "service_activity")
    M = mt.metrics(r["T"], CID)
    return len(m) == 1 and m.iloc[0].n_rows == 30 and abs(M["kg"].value - BASE_M["kg"].value) < 1e-6, \
        f"{m.iloc[0].n_rows} rows flagged & auto-excluded; washed kg back to {M['kg'].value:,.1f} (pristine {BASE_M['kg'].value:,.1f})"


@case("Add conflicting duplicate keys to Repairs", "same key, different counts")
def _():
    s = pack(); R = s["Repairs"]; d = R.iloc[50:55].copy(); d["repair_count"] += 7; s["Repairs"] = pd.concat([R, d])
    r = run(one(s)); m = has(r, "conflicting duplicate keys", "repairs")
    return len(m) == 1 and m.iloc[0].n_rows == 5, f"{m.iloc[0].n_rows} conflicting rows; first occurrence kept"


@case("Negative values (3 repair counts, 2 washed kg)", "impossible values")
def _():
    s = pack(); s["Repairs"].loc[[10, 11, 12], "repair_count"] = -4; s["Service_Activity"].loc[[5, 6], "customer_washed_kg"] = -100
    r = run(one(s)); m = has(r, "negative value")
    return set(m.table) == {"repairs", "service_activity"} and m.n_rows.sum() == 5, f"{m.n_rows.sum()} rows in {sorted(m.table)}"


@case("Percentage over limit (repair_quotient_pct = 250 on 3 rows)", "percentage > 100")
def _():
    s = pack(); s["Repairs"].loc[[20, 21, 22], "repair_quotient_pct"] = 250
    r = run(one(s)); m = has(r, "value above limit", "repairs")
    return len(m) == 1 and m.iloc[0].n_rows == 3, m.iloc[0].explanation[:120] if len(m) else "-"


@case("Wrong unit: water per kg in m³ (÷1000) for every laundry row", "unit error across a whole column")
def _():
    s = pack(); s["Laundry_Resources"]["fresh_water_l_per_kg"] /= 1000
    r = run(one(s)); m = has(r, "implausible intensity (wrong unit?)", "resources")
    return len(m) == 1 and m.iloc[0].severity == "ERROR", f"{m.iloc[0].severity}: {m.iloc[0].explanation[:110]}" if len(m) else "-"


@case("Missing months: S003 June removed; laundry L001 September removed from resources", "gaps")
def _():
    s = pack(); A = s["Service_Activity"]; s["Service_Activity"] = A[~((A.site_id == "S003") & (A.month == "2025-06"))]
    L = s["Laundry_Resources"]; s["Laundry_Resources"] = L[~((L.laundry_id == "L001") & (L.month == "2025-09"))]
    r = run(one(s)); a = has(r, "missing months", "service_activity", "S003"); b = has(r, "activity without laundry resource data", None, "L001")
    M = mt.metrics(r["T"], CID)
    return len(a) == 1 and len(b) == 1 and M.coverage["water"] < 1, f"S003 gap flagged; L001-2025-09 flagged; water coverage {M.coverage['water']:.1%} of washed kg (caveat shown on metrics)"


@case("Status labels: blank on 10 rows, 'LOOKS_GOOD', 'measured' mixed into synthetic", "status inconsistencies")
def _():
    s = pack(); A = s["Service_Activity"]; A.loc[A.index[:10], "data_status"] = np.nan
    R = s["Repairs"]; R.loc[R.index[:5], "data_status"] = "LOOKS_GOOD"; R.loc[R.index[5:9], "data_status"] = "measured"
    r = run(one(s))
    ok = len(has(r, "blank status label", "service_activity")) == 1 and len(has(r, "unrecognised status label", "repairs")) == 1 and len(has(r, "mixed measured and synthetic data")) == 1
    return ok, "blank / unrecognised / mixed measured+synthetic all raised"


@case("Text in a numeric cell ('n/a' in washed kg)", "unparseable value")
def _():
    s = pack(); A = s["Service_Activity"]; A["customer_washed_kg"] = A.customer_washed_kg.astype(object); A.loc[A.index[7], "customer_washed_kg"] = "approx 500"
    r = run(one(s)); m = has(r, "non-numeric value", "service_activity")
    return len(m) == 1 and m.iloc[0].n_rows == 1, m.iloc[0].location[:90] if len(m) else "-"


@case("Blank required value (washed kg empty / 'n/a' on 2 rows)", "missing value in required column")
def _():
    s = pack(); A = s["Service_Activity"]; A["customer_washed_kg"] = A.customer_washed_kg.astype(object); A.loc[A.index[3], "customer_washed_kg"] = None; A.loc[A.index[9], "customer_washed_kg"] = "n/a"
    r = run(one(s)); m = has(r, "blank required value", "service_activity")
    return len(m) == 1 and m.iloc[0].n_rows == 2, m.iloc[0].location[:90] if len(m) else "-"


@case("Cycle timestamps out of order (5 cycles)", "pickup after delivery")
def _():
    s = pack(); C = s["Service_Cycles"]; i = C.index[:5]
    a, b = C.loc[i, "pickup_timestamp"].copy(), C.loc[i, "delivered_timestamp"].copy(); C.loc[i, "pickup_timestamp"], C.loc[i, "delivered_timestamp"] = b, a
    r = run(one(s)); m = has(r, "timestamps out of order")
    return len(m) == 1 and m.iloc[0].n_rows == 5, f"{m.iloc[0].n_rows} cycles flagged"


@case("Remove the Laundry_Resources sheet entirely", "missing optional sheet")
def _():
    s = pack(); del s["Laundry_Resources"]
    r = run(one(s)); m = has(r, "missing optional sheet", "resources"); M = mt.metrics(r["T"], CID)
    return len(m) == 1 and "water_saving" in M.missing and "repairs" in M, "WARNING raised; water/energy/CO2 not calculated, repair metrics still shown (no invented numbers)"


@case("Same data, different shape: 3 files, renamed sheets, shuffled/renamed columns, tonnes, m³, MWh, tCO2e, MM/YYYY months",
      "auto-mapping + units must reproduce the sample's numbers")
def _():
    P = pack()
    def ren(d, mp, order=None):
        d = d.rename(columns=mp)
        cols = list(d.columns)
        return d[cols[::-1]] if order == "rev" else d
    A = P["Service_Activity"].copy(); A["customer_washed_kg"] /= 1000; A["month"] = pd.to_datetime(A.month).dt.strftime("%m/%Y")
    A = ren(A, {"month": "Reporting month", "customer_id": "Account Top Level", "site_id": "Delivery Customer", "laundry_id": "Laundry", "product_id": "Product Code",
                "active_wearers": "Active wearers", "allocated_pieces": "Allocated pieces", "active_assets_scanned": "Scanned assets", "washed_pieces": "Washed pieces",
                "packed_pieces": "Packed pieces", "washing_pct": "Washing %", "customer_washed_kg": "Washed (t)", "service_requests": "Service requests", "data_status": "Data status"}, "rev")
    R = ren(P["Repairs"], {"month": "Month", "customer_id": "Account Top Level", "site_id": "Delivery Customer", "product_id": "Product Code", "laundry_id": "Laundry",
                           "repair_type": "Repair Name", "repair_count": "Number of repairs", "repair_quotient_pct": "Repair quotient %",
                           "estimated_replacements_postponed": "Replacements postponed", "estimated_avoided_product_kgco2e": "Avoided product kgCO2e", "data_status": "Status"})
    Rs = P["Laundry_Resources"].copy()
    Rs["fresh_water_m3"] = Rs.fresh_water_l / 1000; Rs["energy_mwh"] = Rs.process_energy_kwh / 1000
    Rs["pc"] = Rs.process_emissions_kgco2e / 1000; Rs["dc"] = Rs.delivery_emissions_kgco2e / 1000
    Rs = Rs[["month", "laundry_id", "laundry_name", "country", "washed_kg", "fresh_water_m3", "energy_mwh", "pc", "dc", "data_status"]]
    Rs.columns = ["Month", "WWS", "WWS name", "Country", "Washed kg", "Fresh water (m3)", "Process energy (MWh)", "Process emissions (tCO2e)", "Delivery emissions (tCO2e)", "Data status"]
    W = ren(P["Waste_Circularity"], {"month": "Month", "laundry_id": "WWS", "recycling_kg": "Recycling kg", "reuse_kg": "Reuse kg", "energy_recovery_kg": "Energy recovery kg",
                                     "incineration_kg": "Incineration kg", "textile_waste_total_kg": "Total textile waste kg", "waste_kg_per_washed_kg": "Waste per washed kg", "data_status": "Status"})
    C = ren(P["Service_Cycles"], {"asset_id": "RFID", "cycle_number": "Cycle", "customer_id": "Account", "site_id": "Delivery site", "laundry_id": "Laundry", "product_id": "Product",
                                  "pickup_timestamp": "Pickup", "in_laundry_timestamp": "In laundry", "out_laundry_timestamp": "Out laundry", "delivered_timestamp": "Delivered",
                                  "cycle_hours": "Turnaround hours", "performance_flag": "Delivery performance", "data_status": "Status"})
    B = ren(P["Baselines"], {"baseline_id": "Baseline code", "baseline_name": "Scenario", "water_l_per_kg": "Water l/kg", "energy_kwh_per_kg": "Energy kWh/kg",
                              "process_kgco2e_per_kg": "Process kgCO2e/kg", "delivery_kgco2e_per_kg": "Delivery kgCO2e/kg", "mixed_waste_share": "Mixed waste share", "selection_status": "Selection"})
    Cu = ren(P["Customers"], {"customer_id": "Account Top Level", "customer_name": "Customer name", "industry": "Sector", "hq_country": "HQ country", "data_status": "Status"})
    S = ren(P["Sites"], {"site_id": "Delivery site ID", "customer_id": "Account Top Level", "site_name": "Site name", "primary_laundry_id": "Primary laundry", "data_status": "Status"})
    Pr = ren(P["Products"], {"product_id": "Product Code", "product_name": "Product name", "avg_weight_kg": "Avg weight (kg)", "synthetic_product_footprint_kgco2e": "Product footprint kgCO2e",
                              "synthetic_purchase_cost_eur": "Purchase cost (EUR)"})
    La = ren(P["Laundries"], {"laundry_id": "WWS", "laundry_name": "WWS name"})
    files = [("master_data.xlsx", xlsx({"Account master": Cu, "Site master": S, "Article master": Pr, "WWS list": La, "Control totals": P["Sample_Output"]})),
             ("operations_2025.xlsx", xlsx({"Allocated pieces & washing": A, "Repair report": R, "End to end delivery": C})),
             ("environment_2025.xlsx", xlsx({"WWS resources": Rs, "Textile waste": W, "Comparison factors": B}))]
    r = run(files)
    tabs = {v.table for v in r["mapping"].values() if v.table}
    M = mt.metrics(r["T"], CID)
    keys = ["kg", "repairs", "water_saving", "energy_saving", "co2_service", "waste", "avoided_cost", "requests", "ontime", "utilisation", "recycling_pct"]
    worst = max(abs(M[k].value - BASE_M[k].value) / max(abs(BASE_M[k].value), 1e-9) for k in keys)
    conv = has(r, "unit conversion applied")
    ref = has(r, "control totals reconcile")
    errs = r["issues"][r["issues"].severity == "ERROR"]
    ok = tabs >= {"customers", "sites", "products", "laundries", "service_activity", "repairs", "service_cycles", "resources", "waste", "baselines", "reference_totals"} and worst < 5e-4
    return ok, f"{len(tabs)} tables mapped from 3 files; max deviation vs sample on 11 key metrics {worst:.2e}; {len(conv)} unit-conversion notices; control totals reconcile: {len(ref)}; errors: {_errnames(errs)}"


# ===================================================================== KAM features
import re as _re
import json, re
import portfolio as pf, export_pptx as xp, story as sy, data_loader as dl
from assumptions import Uncertainty

_T = BASE["T"]


def _deck_text(cid):
    M = mt.metrics(_T, cid); St = mt.site_table(_T, cid); Ct = mt.country_rollup(St)
    RI = pf.repair_intensity(_T)
    Ib = pf.issues_for_customer(BASE["issues"], _T, cid)
    opps = pf.opportunities(_T, cid, M, St, RI)
    ind = pf.customers(_T).set_index("customer_id").industry[cid]
    themes = sy.parse_priority("", _T, ind)
    recs = sy.recommendations(M, St, themes, M.baseline_name, Ib, BASE["log"])
    story = sy.narrative(cid, themes, M, recs)
    ctx = dict(mapping_df=dl.mapping_table(BASE["raw"], BASE["mapping"]), issues=Ib, log=BASE["log"], excluded_ids=set(),
               assumptions=_T.get("assumptions"), readiness=pl.readiness(_T, BASE["mapping"], BASE["raw"]), topics=opps[:4],
               actions=[dict(action=c["title"], lindstrom_owner="", customer_owner="", target_date="", status="Proposed") for c in opps[:4]])
    names = pf.customers(_T).set_index("customer_id").customer
    data = xp.build(names[cid], ind, themes, M.baseline_name, "Base", Uncertainty(), M, sy.order_metrics(M, themes), recs, story, St, Ct, ctx)
    from pptx import Presentation
    prs = Presentation(io.BytesIO(data)); out = []
    for sl in prs.slides:
        if sl.has_notes_slide: out.append(sl.notes_slide.notes_text_frame.text)
        for sh in sl.shapes:
            if sh.has_text_frame: out.append(sh.text_frame.text)
            if sh.has_table:
                out += [c.text for r in sh.table.rows for c in r.cells]
    return " \n".join(out), len(prs.slides)


@case("Per-customer deck leaks nothing about other customers", "export for each customer; scan every text box and table for other customers' names, ids, sites")
def _():
    CU = pf.customers(_T); S = _T["sites"]; bad = []; n = 0
    for c in CU.customer_id:
        txt, n = _deck_text(c)
        others = CU[CU.customer_id != c]
        toks = set(others.customer_id) | set(others.customer) | set(S[S.customer_id != c].site_name.dropna()) | set(S[S.customer_id != c].site_id.dropna())
        for t in toks:
            if _re.search(r"(?<![A-Za-z0-9])" + _re.escape(t) + r"(?![A-Za-z0-9])", txt):
                bad.append((c, t))
    return not bad, f"3 decks of {n} slides scanned against {len(S)} site names/ids and 2 other customers each; leaks: {bad[:3] or 'none'}"


@case("Opportunity cards are evidence-backed and never invent money", "every card has evidence, sizing, assumptions, questions; no card claims a revenue figure")
def _():
    M = mt.metrics(_T, CID); St = mt.site_table(_T, CID); RI = pf.repair_intensity(_T)
    cards = pf.opportunities(_T, CID, M, St, RI)
    full = all(c["evidence_customer"] and c["sizing"] and c["assumptions"] and c["confirm"] and c["status"] for c in cards)
    txt = " ".join(c["hypothesis"] + c["sizing"] + " ".join(c["evidence_customer"]) for c in cards)
    nomoney = not _re.search(r"revenue|upsell|sales uplift|contract value", txt, _re.I)
    nopeer = not any("other accounts" in e or "Internal benchmark" in e for c in cards for e in c["evidence_customer"])
    return len(cards) >= 4 and full and nomoney and nopeer, f"{len(cards)} cards for {CID}; complete: {full}; no revenue claims: {nomoney}; customer-safe evidence has no peer data: {nopeer}"


@case("Stale-asset count follows the threshold exactly", "RFID view recomputed independently at 30 and 120 days")
def _():
    C = _T["service_cycles"]; c = C[C.customer_id == CID]
    end = C.delivered_timestamp.max()
    last = c.groupby(["asset_id", "site_id"]).delivered_timestamp.max()
    ok = True; ev = []
    for d in (30, 120):
        exp = int(((end - last).dt.days > d).sum()); got = pf.stale_assets(_T, CID, d)["stale"]
        ok &= exp == got; ev.append(f"{d} d: {got} (expected {exp})")
    return ok, "; ".join(ev)


@case("Flag rule needs real differences", "all sites identical except tiny noise -> nobody flagged; one clear outlier -> flagged")
def _():
    t = pd.DataFrame(dict(site=list("ABCDEF"), utilisation=[85, 85.2, 84.9, 85.1, 85, 85.3], ontime=[98.3, 98.4, 98.3, 98.3, 98.4, 98.3], requests_per_1000=[16, 16.1, 15.9, 16, 16.2, 16]))
    quiet = mt.flag_sites(t).attention.sum()
    t.loc[0, "requests_per_1000"] = 60
    loud = mt.flag_sites(t); 
    return quiet == 0 and bool(loud.loc[0, "attention"]) and loud.attention.sum() == 1, f"noise only: {quiet} flagged; one site at 60 vs 16 requests per 1000: flagged {int(loud.attention.sum())} (site A)"


import analyst as an
from types import SimpleNamespace as _N


class _FakeLLM:
    """Scripted stand-in for the Anthropic client: a list of turns, each a list of (tool, input) or ('text', str)."""
    def __init__(s, turns): s.turns, s.n, s.calls = turns, 0, []
    @property
    def messages(s): return s
    def create(s, **k):
        s.calls.append(k)
        t = s.turns[min(s.n, len(s.turns) - 1)]; s.n += 1
        blocks = [(_N(type="text", text=x[1]) if x[0] == "text" else _N(type="tool_use", id=f"t{s.n}_{i}", name=x[0], input=x[1])) for i, x in enumerate(t)]
        return _N(stop_reason="tool_use" if any(b.type == "tool_use" for b in blocks) else "end_turn", content=blocks)


def _actx():
    return an.Ctx(_T, BASE["issues"])


@case("Analyst: no key -> rule-based; invented numbers rejected (after one retry); faithful answer accepted; badges come from the data",
      "fake models: one invents a number twice, one fixes it on retry, one is faithful but labels an allocated figure; one skips the data")
def _():
    os.environ.pop("ANTHROPIC_API_KEY", None)
    ctx = _actx()
    a = an.answer("Which sites stand out at Mediora?", ctx)
    q = {"measures": ["water_saving_l", "utilisation_pct"], "filters": {"customer": "NorthStar"}}
    real = an.query(ctx, **q)["rows"][0]
    w, ut = real["water_saving_l"], real["utilisation_pct"]
    lie = lambda: ("respond", {"read": f"Water saved is {w * 1.3 / 1e6:.2f} M L.", "key_numbers": [], "follow_ups": []})
    good = ("respond", {"read": f"Water saved is {w / 1e6:.2f} M L and utilisation {ut} %.", "follow_ups": ["x"],
                        "key_numbers": [{"label": "Water saved", "value": f"{w / 1e6:.2f} M L", "result_id": "R?"}, {"label": "Utilisation", "value": f"{ut} %", "result_id": "R?"}]})
    bad = an.answer("water at NorthStar?", ctx, client=_FakeLLM([[("query", q)], [lie()], [lie()]]))
    fixed = an.answer("water at NorthStar?", ctx, client=_FakeLLM([[("query", q)], [lie()], [good]]))
    ok_ = an.answer("water at NorthStar?", ctx, client=_FakeLLM([[("query", q)], [good]]))
    skip = an.answer("x", ctx, client=_FakeLLM([[("text", "Utilisation is 99 %")]]))
    st = {k["label"]: k["status"] for k in ok_.get("key_numbers", [])}
    retry_msg = fixed["source"] == "llm"
    passed = (a["source"] == "rules" and bad["source"] == "rules" and "numbers" in bad.get("note", "") and fixed["source"] == "llm" and ok_["source"] == "llm"
              and st.get("Water saved") == "ALLOCATED" and st.get("Utilisation") == "CALCULATED" and skip["source"] == "rules" and retry_msg)
    return passed, (f"no key: {a['source']}; invents twice: {bad['source']} ({bad.get('note','')[:50]}…); invents then fixes on retry: {fixed['source']}; "
                    f"faithful: {ok_['source']} with badges {st}; no data looked at: {skip['source']}")


@case("Analyst query engine reproduces the headline metrics exactly", "for every customer: kg, garments, utilisation, requests/1000, repairs, on-time, water/CO2 saving and Low/High")
def _():
    ctx = _actx(); worst, n = 0.0, 0
    pairs = [("washed_kg", "kg", "value"), ("garments_allocated", "pieces", "value"), ("utilisation_pct", "utilisation", "value"), ("repairs", "repairs", "value"),
             ("ontime_pct", "ontime", "value"), ("water_saving_l", "water_saving", "value"), ("water_saving_l_low", "water_saving", "low"),
             ("water_saving_l_high", "water_saving", "high"), ("co2_saving_kg", "co2_service", "value"), ("energy_saving_kwh", "energy_saving", "value")]
    for cid in ctx.CU.customer_id:
        M = mt.metrics(_T, cid)
        r = an.query(ctx, ["washed_kg", "garments_allocated", "utilisation_pct", "repairs", "ontime_pct", "water_saving_l", "co2_saving_kg", "energy_saving_kwh",
                           "requests_per_1000_garments"], filters={"customer": cid})["rows"][0]
        for qk, mk, att in pairs:
            ref = getattr(M[mk], att); dev = abs(r[qk] - ref); worst = max(worst, dev); n += 1
        rq = 1000 * M["requests"].value / M["pieces"].value
        worst = max(worst, abs(r["requests_per_1000_garments"] - rq)); n += 1
    return worst <= 0.5, f"{n} comparisons across 3 customers; largest absolute difference {worst:.3f} = display rounding (1 decimal for rates, whole units for kg/L/kWh)"


@case("Analyst what-ifs are exact recalculations", "baseline switch = metrics with that baseline; 50 % repair share halves; utilisation target lifts low sites exactly to target")
def _():
    ctx = _actx()
    r = an.t_what_if(ctx, "Apex", baseline="home")
    ref = mt.metrics(_T, "CUST002", "B_HOME")["water_saving"].value
    w = next(c for c in r["changes"] if c["measure"] == "Water saved")
    r2 = an.t_what_if(ctx, "Apex", repair_share_pct=50)
    p = next(c for c in r2["changes"] if c["measure"] == "Replacements postponed")
    r3 = an.t_what_if(ctx, "Apex", utilisation_target_pct=99)
    u = next(c for c in r3["changes"] if c["measure"] == "Garment utilisation")
    ok = abs(w["after"] - ref) < 1 and abs(p["after"] - p["before"] / 2) <= 1 and abs(u["after"] - 99) < 0.05 and r["default_status"] == "SCENARIO"
    return ok, f"home baseline {w['after']:.0f} L vs metrics {ref:.0f} L; postponed {p['before']} → {p['after']}; utilisation at a 99 % target → {u['after']} %"


@case("Analyst calc only accepts numbers that tools returned", "derived difference accepted; an operand that no tool returned is refused")
def _():
    ctx = _actx()
    rid, r = ctx.put("query", {}, an.query(ctx, ["utilisation_pct"], ["site"], {"customer": "NorthStar"}))
    s = r["summary"]["utilisation_pct"]
    good = an.t_calc(ctx, f"{s['max']} - {s['min']}", "spread")
    bad = an.t_calc(ctx, f"{s['max']} - 61.37", "spread")
    return "value" in good and "error" in bad, f"{s['max']} − {s['min']} = {good.get('value')}; with an invented operand: {bad.get('error','')[:60]}"


@case("Analyst charts and hypotheses cannot carry invented numbers", "chart naming a missing column is dropped; a hypothesis with an invented number fails the check")
def _():
    ctx = _actx()
    rid, r = ctx.put("query", {}, an.query(ctx, ["utilisation_pct"], ["site"], {"customer": "NorthStar"}))
    spec = {"read": "ok", "key_numbers": [], "follow_ups": [], "charts": [{"result_id": rid, "kind": "bar", "x": "site", "y": ["utilisation_pct"], "title": "a"},
                                                                         {"result_id": rid, "kind": "bar", "x": "site", "y": ["profit_eur"], "title": "b"}],
            "hypotheses": ["Staff turnover could explain it."]}
    a, bad = an.finalize(ctx, spec, "", [], "llm")
    spec["hypotheses"] = ["A 12.7 % uplift is likely."]
    _, bad2 = an.finalize(ctx, spec, "", [], "llm")
    return len(a["charts"]) == 1 and not bad and bad2, f"charts kept {len(a['charts'])} of 2; clean hypothesis passes: {not bad}; invented number caught: {bad2}"


@case("Analyst follows a thread and every rule-based answer is traceable", "'which sites stand out' then 'drill into that site'; 20 varied questions: no crash, no untraceable number")
def _():
    ctx = _actx()
    a1 = an.answer("Which sites stand out at NorthStar?", ctx)
    a2 = an.answer("Drill into that site", ctx)
    first = a1["read"].split(": ")[1].split(" (")[0]
    thread = a2["tools"][0]["tool"] == "site_profile" and a2["read"].startswith(first)
    qs = ["How are we doing with NorthStar?", "Compare utilisation by site at NorthStar", "Same by country", "Show the monthly trend of requests at NorthStar",
          "What if NorthStar's own water use is 14 L/kg?", "What if utilisation at Apex reached 90 %?", "How fair is the baseline for Apex?", "What should I propose to Mediora?",
          "How is the water saving calculated for NorthStar?", "Compare customers on on-time delivery", "How good is the data?", "hygiene risk at Mediora over 120 days",
          "repairs by repair type at Apex", "water saving by laundry at NorthStar", "What if we exclude L003 at NorthStar?", "What if only 50 % of repairs prevent a purchase at Apex?",
          "utilisation in H2 by product for NorthStar", "late cycles by site at Mediora", "Drill into Gdańsk", "what if on-time reached 99 % at NorthStar"]
    probs = []
    for q in qs:
        r = an.answer(q, ctx)
        if not r["read"] or "Check:" in r.get("note", "") or re.search(r"\b(KeyError|TypeError|ValueError|IndexError|AttributeError)\b", r["read"]):
            probs.append(q)
    return thread and not probs, f"thread kept: {thread} ({first}); {len(qs)} questions answered, problems: {probs or 'none'}"


@case("Implausible repair rate is caught", "set repairs on one product 10x -> warning")
def _():
    s = pack(); R = s["Repairs"].copy()
    col = [c for c in R.columns if "count" in c.lower()][0]
    pid = [c for c in R.columns if "product" in c.lower()][0]
    R.loc[R[pid] == R[pid].iloc[0], col] *= 40
    s["Repairs"] = R
    r = run(one(s)); m = has(r, "implausible repair rate")
    return len(m) >= 1, f"{len(m)} warning(s): {m.explanation.iloc[0][:90] if len(m) else '-'}"


@case("Prepare: priority order follows CRM, attendees and public info, with reasons; override wins", "rank_themes on crafted inputs; sample public brief always has a source; no key -> labelled sample")
def _():
    import prep as pr, os as _os
    o1, w1 = pr.rank_themes(["service", "water"], "Priority topics (CRM): Cost optimization", [], [])
    o2, w2 = pr.rank_themes(["service", "water"], "", [], ["Procurement", "Finance"])
    o3, w3 = pr.rank_themes(["service", "water"], "", [dict(include=True, theme="emissions", text="x", source="s"), dict(include=False, theme="cost", text="y", source="s")], [])
    o4, _ = pr.rank_themes(["water", "service"], "", [], [])
    saved = _os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        pts, brand, mode = pr.public_brief("NorthStar Foods Group", "Food & Beverage")
    finally:
        if saved: _os.environ["ANTHROPIC_API_KEY"] = saved
    ok = (o1[0] == "cost" and w1["cost"] and o2[0] == "cost" and "emissions" in o3[:2] and "cost" not in o3[:1] and o4[0] == "water"
          and all(p["source"] for p in pts) and mode.startswith("sample") and len(brand) == 2)
    return ok, f"CRM->{o1[0]}; procurement+finance->{o2[0]}; included public point->{o3[0]}; industry lens->{o4[0]}; no key: {mode}, {len(pts)} sourced sample points"


@case("Customer-coloured deck stays readable and leaks nothing", "very light brand colours are darkened; deck builds for every customer with brand colours and passes the leak scan")
def _():
    import export_pptx as xp
    c = xp._readable(xp._rgb("#FFF200"), 0.35); d = xp._readable(xp._rgb("#FFFFFF"), 0.5)
    lum_ok = xp._lum(c) <= 0.35 + 1e-9 and xp._lum(d) <= 0.5 + 1e-9
    before = (xp.NAVY, xp.TEAL)
    orig = xp._build
    seen = {}
    def spy(*a, **k):
        seen["navy"] = xp.NAVY; return orig(*a, **k)
    xp._build = spy
    try:
        CU = pf.customers(_T); S = _T["sites"]; bad = []
        for cid in CU.customer_id:
            _brand = ("#FFF200", "#FFFFFF")
            _old = xp.build
            def b2(*a, **k):
                a[-1]["brand"] = _brand; return _old(*a, **k)
            xp.build = b2
            try:
                txt, n = _deck_text(cid)
            finally:
                xp.build = _old
            others = CU[CU.customer_id != cid]
            toks = set(others.customer) | set(S[S.customer_id != cid].site_name.dropna())
            bad += [(cid, t) for t in toks if _re.search(r"(?<![A-Za-z0-9])" + _re.escape(t) + r"(?![A-Za-z0-9])", txt)]
    finally:
        xp._build = orig
    restored = (xp.NAVY, xp.TEAL) == before
    return lum_ok and not bad and restored and xp._lum(seen["navy"]) <= 0.35 + 1e-9, f"yellow darkened to lum {xp._lum(c):.2f}; white accent to {xp._lum(d):.2f}; palette restored: {restored}; leaks: {bad[:2] or 'none'}"



def _errnames(e):
    return sorted(e.check.unique().tolist()) if len(e) else "none"


if __name__ == "__main__":
    lines = ["# Break-the-pack test report", "", "Each case modifies the sample pack in memory, runs the full pipeline (ingest → mapping → validation → exclusions → metrics) and checks the expected detection.", "",
             f"Baseline (unmodified pack): {BASE['issues'].severity.value_counts().to_dict()} issues; the only ERROR is the genuine L003 laundry-volume inconsistency in the pack itself.", "",
             "| # | Break | Detected? | Evidence |", "|---|---|---|---|"]
    allok = True
    for i, (name, what, fn) in enumerate(cases, 1):
        try:
            ok, ev = fn()
        except Exception as e:   # a crash is a failure
            ok, ev = False, f"EXCEPTION {type(e).__name__}: {e}"
        allok &= bool(ok)
        print(("PASS" if ok else "FAIL"), i, name, "|", ev)
        lines.append(f"| {i} | {name} | {'✅ yes' if ok else '❌ NO'} | {ev} |")
    lines += ["", f"**{sum(1 for _ in cases)} cases, {'all detected' if allok else 'SOME NOT DETECTED'}.**"]
    open(os.path.join(os.path.dirname(__file__), "TEST_REPORT.md"), "w", encoding="utf-8").write("\n".join(lines))
    sys.exit(0 if allok else 1)
