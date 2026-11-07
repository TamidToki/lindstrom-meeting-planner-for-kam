"""Draft deck, anomalies, START_HERE sheet, paste-back parser, and the review loop."""
import os, sys, io, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
import pipeline as pl, deck_draft as dd, portfolio as pf, master_pack as mp, anomalies as an, metrics as mt, measures as ms
from assumptions import Uncertainty
from decisions import Decisions
from pptx import Presentation
res = []
def ok(n, c, d=""):
    res.append(c); print(("PASS " if c else "FAIL ") + n + (" | " + d if d else ""), flush=True)
def text_of(blob):
    p = Presentation(io.BytesIO(blob)); out = []
    for sl in p.slides:
        for sh in sl.shapes:
            if sh.has_text_frame: out.append(sh.text_frame.text)
            if getattr(sh, "has_table", False) and sh.has_table: out += [c.text for r in sh.table.rows for c in r.cells]
        out.append(sl.notes_slide.notes_text_frame.text)
    return p, "\n".join(out)

r = pl.run_all(pl.sample_files()); T, I, log = r["T"], r["issues"], r["log"]
CU = pf.customers(T); names = dict(zip(CU.customer_id, CU.customer))
decks = {c: dd.build(dd.prepare(T, I, log, c)) for c in names}
ok("D1 a deck builds for every customer", len(decks) == 3)
p, t = text_of(decks["CUST001"])
ok("D2 less is more: summary, outcomes, priorities, top finding, the rest, opportunities, decisions, unsure, appendix = 9 slides; DRAFT banner on slide 1", len(p.slides) == 9 and "DRAFT" in t[:600], f"slides={len(p.slides)}")
leak = [n for c, n in names.items() if c != "CUST001" and n in t]
ok("D3 customer deck contains no other customer", not leak, str(leak))
ok("D4 no 'idle' wording in slides or notes", "idle" not in t.lower())
# anomalies
bsel = mt.default_baseline(T); _, SA = pf.portfolio(T, bsel, "Base", Uncertainty()); RI = pf.repair_intensity(T)
A = an.find(SA[SA.customer_id == "CUST001"], RI, "CUST001", 40, 80)
ok("D5 anomalies are ranked largest first by the stated rule", [a["score"] for a in A] == sorted([a["score"] for a in A], reverse=True) and A[0]["rank"] == 1 and len(A) > 3, f"{len(A)} findings, top: {A[0]['short']}")
a0 = A[0]
ok("D6 the top finding's numbers come from the site table", abs(a0["value"] - float(SA[(SA.customer_id == "CUST001") & (SA.site == a0["entity"])].requests_per_1000.iloc[0])) < 1e-9 if a0["kind"] == "requests" else True)
ok("D7 slide 1 start-here line and slide 2 headline are the top finding", a0["short"] in t and a0["headline"] in t)
ok("D8 utilisation above the range is down-weighted (supply question, not a failure)", an.ABOVE_WEIGHT < 1 and all(a["score"] <= a["pieces"] * a["gap"] * (an.ABOVE_WEIGHT + 1e-9) for a in A if a["kind"] == "utilisation" and a["direction"] == "above"))
# paste-back
blk = """**DECK ADDITIONS**
1. **Title:** Delivery windows at {site}
   - Why it matters: Staff say 40% of deliveries arrive late.
   - Ask: Can the window move earlier?
   - Site: {site}
2. Title: Scope 3 timeline
   Ask: Which framework do you report under?""".format(site=a0["entity"])
ad = dd.parse_additions(blk)
ok("D9 paste-back block parses (markdown tolerated, two items)", len(ad) == 2 and ad[0]["ask"] == "Can the window move earlier?" and ad[0]["site"] == a0["entity"], str(ad)[:120])
b = dd.prepare(T, I, log, "CUST001", additions=ad); rs = b["additions"]
ok("D10 typed figures are flagged unverified; the named site gets code-calculated facts", rs[0]["figures"] and not rs[1]["figures"] and len(rs[0]["facts"]) >= 3, str(rs[0]["facts"]))
p2, t2 = text_of(dd.build(b))
ok("D11 added slides are labelled as from Copilot, deck grows by 2", "ADDED FROM COPILOT" in t2 and len(p2.slides) == 11 and "FIGURES IN TEXT NOT VERIFIED" in t2, f"slides={len(p2.slides)}")
ok("D12 empty paste gives no slides and no crash", dd.parse_additions("hello world") == [] and dd.parse_additions("") == [])
# START_HERE and per-customer workbook
src = pl.sample_files()
rep = mp.build([], "/tmp/_c2.xlsx", "CUST002", sources=src)
x = pd.read_excel("/tmp/_c2.xlsx", sheet_name=None)
sh = x["START_HERE"]; txt = " ".join(sh.Text.fillna("").astype(str))
ok("D13 workbook for one customer: START_HERE is the first sheet, with job, rules, anomalies and the DECK ADDITIONS format", list(x)[0] == "START_HERE" and "DECK ADDITIONS" in txt and "Top findings: Apex" in " ".join(sh.Section.fillna("").astype(str)) and "Never put calculated figures" in txt and "Your job" in " ".join(sh.Section.fillna("").astype(str)), str(list(x)[:3]))
others = [n for c, n in names.items() if c != "CUST002"]
alltxt = " ".join(" ".join(df.fillna("").astype(str).values.ravel()) for df in x.values())
ok("D14 that workbook contains only that customer", not any(n in alltxt for n in others), str([n for n in others if n in alltxt]))
ok("D15 START_HERE lists the same top finding the deck shows", an.find(SA[SA.customer_id == "CUST002"], RI, "CUST002", *ms.Bands().for_customer("CUST002", CU.set_index("customer_id").industry["CUST002"])[:2])[0]["headline"] in txt)

# the five steering-committee questions
ok("D23 every question has its slide, tagged Q1 to Q5", all(f"Q{i} ·" in t.replace("\u00b7", "·") or f"Q{i} " in t for i in range(1, 6)) and all(k in t for k in ("Q1", "Q2", "Q3", "Q4", "Q5")))
bP = dd.prepare(T, I, log, "CUST001")
ok("D24 priorities come from the customer's stated topics and map to calculated measures", bP["topics"][:2] == ["Water efficiency", "Hygiene"] and dd._metric_for(bP, "water") is bP["M"]["water_saving"] and dd._metric_for(bP, None) is None, str(bP["topics"]))
ok("D25 decisions table: pre-filled actions, owners and dates left blank", "Decision or action" in t and "Lindström owner" in t and "Customer owner" in t)
ok("D26 placeholders are honest: no 'since last meeting' claim and commitments say none recorded", "none recorded yet" in t and "add your last meeting date" in t)
# slim workbook for chat models
os.makedirs("/tmp/_s2", exist_ok=True)
rs_ = mp.build([], "/tmp/_s2/Apex.xlsx", "CUST002", sources=src)
sl = pd.read_excel(rs_["slim"], sheet_name=None)
ok("D18 slim Copilot workbook: 7 sheets, START_HERE first and 20 rows or fewer, a fraction of the full size", list(sl)[0] == "START_HERE" and len(sl) == 7 and len(sl["START_HERE"]) <= 20 and os.path.getsize(rs_["slim"]) < os.path.getsize("/tmp/_s2/Apex.xlsx") / 4, f"{list(sl)} rows={len(sl['START_HERE'])}")
sh2 = " ".join(" ".join(df.fillna("").astype(str).values.ravel()) for df in sl.values())
ok("D19 slim workbook holds only that customer, keeps the rules and the anomalies", not any(n in sh2 for n in others) and "Never put calculated figures" in sh2 and "Top findings: Apex" in " ".join(sl["START_HERE"].Section.fillna("").astype(str)))
md = open("/tmp/_s2/Copilot_Prompt.md", encoding="utf-8").read()
ok("D20 prompt file tells the KAM the one-line message and names the slim file", "Follow the instructions in the START_HERE sheet" in md and "_for_Copilot.xlsx" in md)
lo_ = dd.parse_additions("Sure! Ideas:\n- Delivery windows: they arrive after shift start\n- Should we review the garment pool at Stockholm?\n1. Scope 3 reporting")
ok("D21 paste-back accepts a plain bulleted list (no special format needed)", len(lo_) == 3 and lo_[0]["title"] == "Delivery windows" and lo_[1]["ask"].endswith("?") and all(i.get("loose") for i in lo_))
ok("D22 the structured block still wins over loose reading", not dd.parse_additions("1. Title: A topic\n   Ask: A question?")[0].get("loose"))
# review loop
excl = Decisions(); excl.set_issue_action("customer kg exceeds laundry total kg", "service_activity vs resources", "exclude")
rk = mp.build([], "/tmp/_k.xlsx", "all", decisions=Decisions(), sources=src, keep_working=True); rx = mp.build([], "/tmp/_x.xlsx", "all", decisions=excl, sources=src, keep_working=True)
wk, wx = rk.pop("_working"), rx.pop("_working")
bk = dd.prepare(wk["T"], wk["issues"], wk["log"], "CUST001"); bx = dd.prepare(wx["T"], wx["issues"], wx["log"], "CUST001")
diff = [k for k in bk["M"] if abs(bk["M"][k].value - bx["M"][k].value) > 1e-9]
ok("D16 excluding flagged rows changes the numbers but the issue stays visible", len(diff) > 0 and len(dd._open_issues(bk)) == len(dd._open_issues(bx)), str(diff[:3]))
bx["changes"] = [f"{bx['M'][k].label}: {bk['M'][k].fmt()} to {bx['M'][k].fmt()}" for k in diff]
ok("D17 rebuilt deck states what changed", "Since the last version" in text_of(dd.build(bx))[1])
print(f"\n{sum(res)}/{len(res)} passed"); sys.exit(0 if all(res) else 1)
