"""AppTest: Simple mode is drop-and-go. Fresh launch, auto-build, zip for several customers, review loop, paste-back, toggle, no traceback."""
import os, sys, io, zipfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from streamlit.testing.v1 import AppTest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "app.py")
res = []
def ok(n, c, d=""):
    res.append(c); print(("PASS " if c else "FAIL ") + n + (" | " + d if d else ""), flush=True)
def texts(at): return " ".join([m.value for m in at.markdown] + [m.value for m in at.caption] + [b.label for b in at.button] + [h.value for h in at.subheader] + [s.value for s in at.success])

os.environ.pop("DEMO_MODE", None)
at = AppTest.from_file(APP, default_timeout=300).run()
ok("14a fresh launch: no exception", not at.exception, str([e.value for e in at.exception]))
ok("14b only the drop zone: no tabs, no Analyse button, no folder box, no settings expander", len(at.tabs) == 0 and len(at.get("file_uploader")) == 1 and not any("Analyse" in b.label for b in at.button) and len(at.text_input) == 0 and len(at.expander) == 0)
[b for b in at.button if b.key == "use_sample"][0].click().run()
ok("15a sample: the deck is built with no further click", not at.exception and "simple_result" in at.session_state and at.session_state["simple_result"]["report"]["ok"], str([e.value for e in at.exception]))
sr = at.session_state["simple_result"]
ok("15b decks and per-customer workbooks exist for every customer", len(sr["customers"]) == 3 and all(c["deck"] and c["xlsx"] for c in sr["customers"].values()), str({k: bool(c["deck"]) for k, c in sr["customers"].items()}))
ok("15c several customers -> one zip download", any(d.label.startswith("Download all 3 decks") for d in at.get("download_button")), str([d.label for d in at.get("download_button")][:3]))
import simple_ui
zn = zipfile.ZipFile(io.BytesIO(simple_ui._zip(sr))).namelist()
ok("15d zip: one folder per customer with deck, workbook and prompt", sum(n.endswith("_DRAFT.pptx") for n in zn) == 3 and sum(n.endswith(".xlsx") for n in zn) >= 3 and sum(n.endswith("Copilot_Prompt.md") for n in zn) == 3, str(zn[:4]))

# review loop
rk = "act_customer kg exceeds laundry total kg|service_activity vs resources"
at.radio(key=rk).set_value("Exclude these rows").run()
[b for b in at.button if b.key == "rebuild_btn"][0].click().run()
ok("15e decision + rebuild: no exception, rows excluded", not at.exception and at.session_state["simple_result"]["report"].get("rows_excluded", 0) > 0, str([e.value for e in at.exception]))

# paste-back
blk = "DECK ADDITIONS\n1. Title: Delivery windows\n   Why it matters: Staff say they arrive late\n   Ask: Can the window move earlier?\n"
from pptx import Presentation
n_before = len(Presentation(io.BytesIO(at.session_state["simple_result"]["customers"]["CUST001"]["deck"])).slides); other_before = at.session_state["simple_result"]["customers"]["CUST002"]["deck"]
at.selectbox(key="add_customer").set_value("CUST001").run()
at.text_area(key="add_text").set_value(blk).run()
cb = [c for c in at.checkbox if c.label.startswith("I confirm this list is for")]
ok("15f0 list with no customer name: preview + confirmation checkbox, Add disabled until it is ticked", len(cb) == 1 and [b for b in at.button if b.key == "add_btn"][0].disabled, str([c.label for c in at.checkbox]))
cb[0].check().run()
[b for b in at.button if b.key == "add_btn"][0].click().run()
ok("15f paste-back adds a slide to that customer's deck", not at.exception and bool(at.session_state["additions"]["CUST001"]), str([e.value for e in at.exception]))
n_a = len(Presentation(io.BytesIO(at.session_state["simple_result"]["customers"]["CUST001"]["deck"])).slides)
ok("15g that customer's deck gained one slide; another customer's deck is untouched", n_a == n_before + 1 and at.session_state["simple_result"]["customers"]["CUST002"]["deck"] == other_before, f"{n_before} -> {n_a}")

# toggle to advanced and back
at.sidebar.toggle[0].set_value(True).run()
ok("16a Advanced shows tabs", not at.exception and len(at.tabs) >= 5, f"tabs={len(at.tabs)} exc={[e.value for e in at.exception]}")
at.sidebar.toggle[0].set_value(False).run()
ok("16b back to Simple: earlier build still there", not at.exception and "simple_result" in at.session_state and len(at.tabs) == 0)

at2 = AppTest.from_file(APP, default_timeout=120).run()
at2.session_state["simple_result"] = dict(report=dict(ok=False, errors=["ValueError: boom"], warnings=[]), sig=None); at2.run()
body = texts(at2) + " ".join(e.value for e in at2.error)
ok("16c failed build is explained in plain words, no traceback", not at2.exception and "Traceback" not in body and "ValueError" not in body and "could not build" in body.lower())
at3 = AppTest.from_file(APP, default_timeout=120); at3.query_params["advanced"] = "1"; at3.run()
ok("16d ?advanced=1 opens Advanced", not at3.exception and len(at3.tabs) >= 5)
os.environ["DEMO_MODE"] = "1"
at4 = AppTest.from_file(APP, default_timeout=120).run()
ok("17 DEMO_MODE: no uploader, sample button", not at4.exception and len(at4.get("file_uploader")) == 0 and any(b.key == "use_sample" for b in at4.button))
os.environ.pop("DEMO_MODE")
print(f"\n{sum(res)}/{len(res)} passed"); sys.exit(0 if all(res) else 1)
