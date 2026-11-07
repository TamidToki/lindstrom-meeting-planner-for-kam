"""Trust pass: draft/data status is told truthfully, wrong-customer Copilot text is stopped, exports are honest and current,
priorities are never matched by theme. Run: PYTHONIOENCODING=utf-8 python tests/test_trust_pass.py"""
import os, sys, io, zipfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["LS_ROOT"] = ROOT
os.environ.pop("DEMO_MODE", None)
import pandas as pd
from pptx import Presentation
from streamlit.testing.v1 import AppTest
import pipeline as pl, deck_draft as dd, simple_ui, prep

APP = os.path.join(ROOT, "app.py")
res = []
def ok(n, c, d=""):
    res.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (" | " + str(d)[:230] if d else ""), flush=True)

def slides_text(blob):
    p = Presentation(io.BytesIO(blob)); out = []
    for sl in p.slides:
        t = []
        for sh in sl.shapes:
            if sh.has_text_frame: t.append(sh.text_frame.text)
            if getattr(sh, "has_table", False) and sh.has_table: t += [c.text for r in sh.table.rows for c in r.cells]
        t.append(sl.notes_slide.notes_text_frame.text)
        out.append("\n".join(t))
    return out

def all_text(blob): return "\n".join(slides_text(blob))
def btn(at, key): return [b for b in at.button if b.key == key]
def page_text(at): return " ".join([m.value for m in at.markdown] + [m.value for m in at.caption] + [e.value for e in at.error] + [w.value for w in at.warning] + [i.value for i in at.info] + [s.value for s in at.success])

# ----------------------------------------------------------------------------------------------- shared data (no Streamlit)
r = pl.run_all(pl.sample_files()); T, I, log = r["T"], r["issues"], r["log"]
import portfolio as pf
CU = pf.customers(T); names = dict(zip(CU.customer_id, CU.customer))

# ================================================================== 3 + 4  deck wording: sample vs real, DRAFT never promised away
b_real = dd.prepare(T, I, log, "CUST001")                       # default: a real upload
b_syn = dd.prepare(T, I, log, "CUST001", synthetic=True)
t_real, t_syn = all_text(dd.build(b_real)), all_text(dd.build(b_syn))
ok("3a synthetic=True: the synthetic label is on the cover", b_syn["synthetic"] is True and "Synthetic demonstration data, not audited" in slides_text(dd.build(b_syn))[0])
ok("3b default/real upload: no synthetic label anywhere, cover says the KAM must review", b_real["synthetic"] is False and "Synthetic demonstration" not in t_real and "Draft: the KAM must review before customer use" in slides_text(dd.build(b_real))[0])
decks = {c: all_text(dd.build(dd.prepare(T, I, log, c, synthetic=False))) for c in names}
ok("4a no deck says the banner 'goes away' or 'is removed'; the notes say it stays until the KAM has reviewed the deck",
   all("goes away" not in t and "banner is removed" not in t.lower() and "DRAFT banner stays until the KAM has reviewed this deck" in t and "does not approve it for customer use" in t for t in decks.values()))
b0 = dd.prepare(T, I, log, "CUST001"); b0["issues"] = b0["issues"].iloc[0:0]
t0 = all_text(dd.build(b0))
ok("4b a deck with no flagged data still says the KAM reviews it; no promise that DRAFT disappears", "The KAM still reviews this deck before it goes to the customer" in t0 and "banner is removed" not in t0 and "goes away" not in t0 and "DRAFT" in t0)

# ================================================================== 8  priorities: never the nearest theme
m_h, k_h, why_h = dd._metric_for_topic(b_real, "Hygiene")
ok("8a Hygiene: no measure, and the reason says so", m_h is None and k_h == "" and "Hygiene is not measured" in why_h)
m_o, k_o, _ = dd._metric_for_topic(b_real, "On-time delivery")
ok("8b On-time delivery: the on-time measure, direct", m_o is b_real["M"]["ontime"] and k_o == "direct")
m_c, k_c, _ = dd._metric_for_topic(b_real, "Cost efficiency")
ok("8c Cost efficiency: avoided_cost, flagged as a proxy", m_c is b_real["M"]["avoided_cost"] and k_c == "proxy")
ok("8d no theme fallback: a vague service topic has no measure; food safety and infection control are hygiene", dd._metric_for_topic(b_real, "Service continuity")[0] is None and dd._metric_for_topic(b_real, "Infection control")[0] is None and dd._metric_for_topic(b_real, None)[0] is None)
ok("8e the service theme is labelled 'Service & delivery', not hygiene", prep.THEME_LABEL["service"] == "Service & delivery" and "hygiene" not in prep.THEME_LABEL["service"].lower())
def q2(blob): return [t for t in slides_text(blob) if "Q2" in t and "priorities" in t.lower()][0]
s_ns = q2(dd.build(b_real))
ok("8f NorthStar priorities slide: Hygiene shows 'No direct measure available' and on-time is not on the slide", b_real["topics"][1] == "Hygiene" and "No direct measure available in this data. Ask how they track it." in s_ns and "on-time" not in s_ns.lower() and "on time" not in s_ns.lower(), s_ns[:200].replace("\n", " | "))
b2 = dd.prepare(T, I, log, "CUST002")
s_ap = q2(dd.build(b2))
ok("8g a cost topic shows the number with a PROXY · CONFIRM chip", "Cost optimization" in b2["topics"] and "PROXY · CONFIRM" in s_ap, s_ap[:160].replace("\n", " | "))
b3 = dd.prepare(T, I, log, "CUST001"); b3["anoms"] = []
t3 = slides_text(dd.build(b3)); q3 = [t for t in t3 if "DELIVERY ISSUES AND RISKS" in t][0]
ok("8h no anomalies: 'No threshold was crossed', 'not proof that service is healthy', no 'Nothing stands out' or 'steady service'",
   "No threshold was crossed in this data" in q3 and "That is not proof that service is healthy: the checks only cover the measures and periods in this file. Ask what the customer is seeing." in q3
   and "No threshold was crossed — that is not proof that service is healthy" in t3[0] and "Nothing stands out" not in "\n".join(t3) and "steady service" not in "\n".join(t3))

# ================================================================== 9 + 10  pasted text: unverified, customer parsing
items = dd.resolve_additions([dict(title="Delivery windows", why="Staff say they arrive late", ask="Can the window move earlier?", site=""),
                              dict(title="Cut late deliveries by 40%", why="Forty percent of vans are late", ask="Agree a target?", site="")], b_real["S"])
ok("9a every pasted item is unverified; 'figures' stays a separate flag", all(i["unverified"] is True for i in items) and items[0]["figures"] is False and items[1]["figures"] is True)
bA = dd.prepare(T, I, log, "CUST001", additions=[dict(title="Delivery windows", why="Staff say they arrive late", ask="Can the window move earlier?", site="")])
sl = slides_text(dd.build(bA)); added = [t for t in sl if "ADDED FROM COPILOT" in t]
ok("9b an item with no figures still gets TEXT NOT VERIFIED and the footer; no figures chip", len(added) == 1 and "TEXT NOT VERIFIED" in added[0] and dd.PASTE_FOOTER in added[0] and "FIGURES IN TEXT NOT VERIFIED" not in added[0], added[0][-260:].replace("\n", " | "))
bB = dd.prepare(T, I, log, "CUST001", additions=[dict(title="Cut late deliveries by 40%", why="Forty percent of vans are late", ask="Agree a target?", site="")])
a2 = [t for t in slides_text(dd.build(bB)) if "ADDED FROM COPILOT" in t][0]
ok("9c figures: both chips, the footer, and the notes say all text is unverified incl. numbers as words", "FIGURES IN TEXT NOT VERIFIED" in a2 and "TEXT NOT VERIFIED" in a2 and dd.PASTE_FOOTER in a2 and "unverified, including numbers written as words" in a2 and "only the site facts box is calculated" in a2)
ok("10a parse_customer: case, markdown, bullets and dash/colon tolerated; none -> ''",
   dd.parse_customer("DECK ADDITIONS\nCustomer: NorthStar Foods Group\n1. Title: x") == "NorthStar Foods Group"
   and dd.parse_customer("**Customer:** NorthStar Foods Group") == "NorthStar Foods Group"
   and dd.parse_customer("- customer - northstar foods group") == "northstar foods group"
   and dd.parse_customer("  # CUSTOMER : Apex Industrial Systems  ") == "Apex Industrial Systems"
   and dd.parse_customer("1. Title: a\nAsk: b") == "" and dd.parse_customer("") == "" and dd.parse_customer(None) == "")
ok("10b _match_customer ignores case and punctuation", simple_ui._match_customer("northstar  FOODS-group!", names) == "CUST001" and simple_ui._match_customer("Apex Industrial Systems", names) == "CUST002")
ok("10c unknown, partial and empty names are rejected", simple_ui._match_customer("Zeta Corp", names) is None and simple_ui._match_customer("NorthStar", names) is None and simple_ui._match_customer("", names) is None)

# ================================================================== 5  a deck that failed is never silently missing from the zip
fake = dict(customers={
    "C1": dict(name="Alpha Co", deck=b"PPTX-ALPHA", xlsx={"alpha.xlsx": b"x"}, slim={}, prompt="p"),
    "C2": dict(name="Beta Ltd", deck=None, xlsx={"beta.xlsx": b"y"}, slim={}, prompt="")})
try:
    zb = simple_ui._zip(fake); z = zipfile.ZipFile(io.BytesIO(zb)); zn = z.namelist(); crashed = None
except Exception as e:
    zn, crashed = [], repr(e)
ok("5a missing deck: no crash; top-level INCOMPLETE_BUILD.txt names the failed customer", crashed is None and "INCOMPLETE_BUILD.txt" in zn and "Beta Ltd" in z.read("INCOMPLETE_BUILD.txt").decode() and "Alpha Co" not in z.read("INCOMPLETE_BUILD.txt").decode(), crashed or zn)
ok("5b the failed customer gets DECK_NOT_BUILT.txt with a reason and still has its data workbook", "Beta_Ltd/DECK_NOT_BUILT.txt" in zn and "could not be built" in z.read("Beta_Ltd/DECK_NOT_BUILT.txt").decode() and "Beta_Ltd/full_data_pack/beta.xlsx" in zn)
ok("5c the other deck is still in the zip; the failed one is not", "Alpha_Co/Meeting_plan_Alpha_Co_DRAFT.pptx" in zn and not any(n.startswith("Beta_Ltd/") and n.endswith(".pptx") for n in zn))
ok("5d a complete result has no INCOMPLETE_BUILD.txt", "INCOMPLETE_BUILD.txt" not in zipfile.ZipFile(io.BytesIO(simple_ui._zip(dict(customers={"C1": fake["customers"]["C1"]})))).namelist())

# ================================================================== UI flows on the sample (one build, many checks)
at = AppTest.from_file(APP, default_timeout=300).run()
btn(at, "use_sample")[0].click().run()
sr = at.session_state["simple_result"]
ok("3c sample build: the result is marked sample and the decks carry the synthetic label", not at.exception and sr["sample"] is True and sr["built_with"]["sample"] is True
   and all("Synthetic demonstration data" in slides_text(c["deck"])[0] for c in sr["customers"].values()), str([e.value for e in at.exception]))
ok("3d success message says draft only, and never 'all ready' wording without it", any("Draft only: the KAM reviews each deck before customer use." in s.value for s in at.success) and "Marked as a draft until" not in page_text(at))

# --- 1 wrong customer
def paste(at, cid, text):
    at.selectbox(key="add_customer").set_value(cid).run()
    at.text_area(key="add_text").set_value(text).run()
    return at
add_btn = lambda at: btn(at, "add_btn")[0]
deck2_before = at.session_state["simple_result"]["customers"]["CUST002"]["deck"]
paste(at, "CUST002", "DECK ADDITIONS\nCustomer: NorthStar\n1. Title: Delivery windows\n   Ask: Can the window move earlier?\n")
ok("1a 'Customer: NorthStar' while Apex is selected: plain error, Add disabled, nothing added", not at.exception and any("Nothing will be added" in e.value for e in at.error) and add_btn(at).disabled and not at.session_state.get("additions"), page_text(at)[-300:])
paste(at, "CUST002", "DECK ADDITIONS\nCustomer: NorthStar Foods Group\n1. Title: Delivery windows\n   Ask: Can the window move earlier?\n")
ok("1b a full other-customer name: says whose answer it is; Add disabled; no checkbox to override it",
   any("That answer is for NorthStar Foods Group, not Apex Industrial Systems. Nothing will be added." in e.value for e in at.error) and add_btn(at).disabled and not [c for c in at.checkbox if "confirm" in c.label.lower()])
ok("1c nothing changed in any deck or in the stored additions", not at.session_state.get("additions") and at.session_state["simple_result"]["customers"]["CUST002"]["deck"] == deck2_before)
paste(at, "CUST002", "DECK ADDITIONS\nCustomer: Zeta Corp\n1. Title: Delivery windows\n   Ask: Can the window move earlier?\n")
ok("10d a customer that is not in this build is rejected with the 'could not match' message", any("We could not match the customer named in the pasted answer (Zeta Corp) to this build. Nothing will be added." in e.value for e in at.error) and add_btn(at).disabled)

# --- 2 missing customer name -> explicit confirmation
loose = "Here are ideas:\n- Delivery windows: staff say they arrive late\n- Should we review the garment pool?\n"
d1_before = at.session_state["simple_result"]["customers"]["CUST001"]["deck"]
paste(at, "CUST002", loose)
cbs = [c for c in at.checkbox if c.label == "I confirm this list is for Apex Industrial Systems"]
ok("2a loose list: Apex's name, the parsed titles and a confirmation checkbox are shown; Add disabled", len(cbs) == 1 and add_btn(at).disabled and "Delivery windows" in page_text(at) and "Apex Industrial Systems" in page_text(at))
cbs[0].check().run()
ok("2b after ticking the checkbox Add is enabled", not add_btn(at).disabled)
add_btn(at).click().run()
ad = at.session_state.get("additions") or {}
sr = at.session_state["simple_result"]
ok("2c the slides go only to the selected customer; other decks untouched; success says unverified and that nothing else changed",
   not at.exception and list(ad) == ["CUST002"] and len(ad["CUST002"]) == 2 and sr["customers"]["CUST001"]["deck"] == d1_before
   and any("Added to Apex Industrial Systems's deck as unverified text. Nothing in the data or decisions changed." in s.value for s in at.success), str([e.value for e in at.exception]))
ok("2d the added slides carry TEXT NOT VERIFIED and the footer even though they hold no figures", all("TEXT NOT VERIFIED" in t and dd.PASTE_FOOTER in t for t in slides_text(sr["customers"]["CUST002"]["deck"]) if "ADDED FROM COPILOT" in t) and "ADDED FROM COPILOT" in all_text(sr["customers"]["CUST002"]["deck"]))
# editing the text must not keep an old confirmation alive
at.text_area(key="add_text").set_value(loose + "- A third topic to raise with them\n").run()
ok("2e new text needs a new confirmation: the checkbox is unticked and Add is disabled again", not at.exception and add_btn(at).disabled and all(not c.value for c in at.checkbox if c.label.startswith("I confirm")))

# --- 5d  UI: incomplete result is never called ready
import copy
cust2 = at.session_state["simple_result"]["customers"]["CUST002"]
keep = cust2["deck"]; cust2["deck"] = None; cust2["deck_error"] = simple_ui.DECK_FAILED
at.run()
body = page_text(at)
ok("5e UI with one deck failed: '2 of 3 meeting decks built', names the failure, 'incomplete — rebuild before the meeting', no 'ready'",
   "2 of 3 meeting decks built. Not built: Apex Industrial Systems." in body and "this result is incomplete — rebuild before the meeting." in body and not any("ready" in s.value for s in at.success) and not at.exception, body[:300])
ok("5f the zip label says 'the 2 of 3 decks that were built (zip, marked incomplete)'", any(d.label == "Download the 2 of 3 decks that were built (zip, marked incomplete)" for d in at.get("download_button")), str([d.label for d in at.get("download_button")][:2]))
cust2["deck"] = keep; cust2.pop("deck_error", None); at.run()

# --- 6 changed decisions disable the old downloads
I_ = at.session_state["simple_result"]["work"]["issues"]; I_ = I_[I_.severity.isin(["ERROR", "WARNING"]) & (I_.n_rows > 0)]
row = I_.iloc[0]; key = f"act_{row.check}|{row.table}"
other = "Keep and report as exception" if row.default_action == "exclude" else "Exclude these rows"
dl_count = lambda at: len(at.get("download_button"))
ok("6a before any change: downloads are present, there is no 'Rebuild now' and no outdated warning", dl_count(at) > 0 and not btn(at, "rebuild_btn") and "earlier build" not in page_text(at))
at.radio(key=key).set_value(other).run()
ok("6b changing a radio makes the build outdated: warning, primary 'Rebuild now', every download and the paste-back controls hidden",
   not at.exception and "These downloads are from an earlier build. Your files or decisions changed after it was made, so they are disabled until you rebuild." in page_text(at)
   and len(btn(at, "rebuild_btn")) == 1 and btn(at, "rebuild_btn")[0].label == "Rebuild now" and dl_count(at) == 0 and not at.text_area, f"downloads={dl_count(at)}")
ok("6c the decision is stored (a non-default choice) and the version changed", (at.session_state["decisions"].issue_actions or {}).get(f"{row.check}|{row.table}") == ("keep" if row.default_action == "exclude" else "exclude"))
at.radio(key=key).set_value("Exclude these rows" if row.default_action == "exclude" else "Keep and report as exception").run()
ok("6d going back to the default is not a decision: the stored key is removed and the old build is current again", not at.exception and f"{row.check}|{row.table}" not in at.session_state["decisions"].issue_actions and dl_count(at) > 0 and not btn(at, "rebuild_btn"))
at.radio(key=key).set_value(other).run()
btn(at, "rebuild_btn")[0].click().run()
bw = at.session_state["simple_result"]["built_with"]
ok("6e 'Rebuild now' rebuilds with the decision; downloads return and the build is current", not at.exception and dl_count(at) > 0 and not btn(at, "rebuild_btn") and bool(bw["decisions"]) and bw["sample"] is True, str(bw))

# --- 7 clearing the files clears the result
at.session_state["simple_pick"] = None
at.run()
ok("7a clearing the files clears simple_result, additions, simple_sig and had_sources", not at.exception and all(k not in at.session_state for k in ("simple_result", "additions", "simple_sig", "had_sources")), str([k for k in ("simple_result", "additions", "simple_sig", "had_sources") if k in at.session_state]))
ok("7b no download buttons or paste box remain; the empty state shows; old decisions and radio keys are gone", dl_count(at) == 0 and not at.text_area and "never changed" in page_text(at) and not at.session_state["decisions"].issue_actions and not [k for k in list(at.session_state) if str(k).startswith("act_")])

# ================================================================== a 'real' upload through a patched uploader (sample flag False) and unrelated files
def harness():
    import os, sys
    sys.path.insert(0, os.environ["LS_ROOT"])
    import streamlit as st
    S = st.session_state
    class F:
        def __init__(s, n, b): s.name, s._b = n, b
        def getvalue(s): return s._b
    files = S.get("_fake_up")
    st.file_uploader = lambda *a, **k: [F(n, b) for n, b in files] if files else []
    import simple_ui
    simple_ui.render_simple()

name0, blob0 = pl.sample_files()[0]
a2_ = AppTest.from_function(harness, default_timeout=300)
a2_.session_state["_fake_up"] = [(name0, blob0)]
a2_.run()
sr2 = a2_.session_state["simple_result"]
ok("3e a real upload (the same bytes, but uploaded): marked not-sample, no synthetic label in any deck, cover says the KAM must review",
   not a2_.exception and sr2["sample"] is False and all("Synthetic demonstration" not in all_text(c["deck"]) and "Draft: the KAM must review before customer use" in slides_text(c["deck"])[0] for c in sr2["customers"].values()), str([e.value for e in a2_.exception]))
k2 = [k for k in list(a2_.session_state) if str(k).startswith("act_")][0]
row2 = [r_ for r_ in I_.itertuples() if f"act_{r_.check}|{r_.table}" == k2][0]
a2_.radio(key=k2).set_value("Exclude these rows" if row2.default_action != "exclude" else "Keep and report as exception").run()
a2_.session_state["additions"] = {"CUST001": [dict(title="Old topic", why="", ask="", site="")]}
ok("7c precondition: a non-default review choice and an old pasted addition exist", bool(a2_.session_state["decisions"].issue_actions) and bool(a2_.session_state["additions"]))
a2_.session_state["_fake_up"] = [("different_customer_file.xlsx", blob0)]
a2_.run()
ok("7d different files: old review choices, widget keys and pasted additions do not carry over; the new build is current", not a2_.exception and not a2_.session_state["decisions"].issue_actions and not a2_.session_state.get("additions")
   and a2_.session_state["simple_sig"] == a2_.session_state["simple_result"]["sig"] and not btn(a2_, "rebuild_btn"))
a2_.session_state["simple_pick"] = "sample"; a2_.session_state["_fake_up"] = []
a2_.run()
ok("3f same bytes now picked as the sample: re-marked as sample (synthetic label returns) because the sample flag is part of the build version",
   not a2_.exception and a2_.session_state["simple_result"]["sample"] is True)

print(f"\n{sum(res)}/{len(res)} passed"); sys.exit(0 if all(res) else 1)
