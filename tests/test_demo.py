"""Public demo entry (app_demo.py): sample data only, no uploads anywhere, no AI, a judge reaches the decks with one click."""
import os, sys, io, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.pop("DEMO_MODE", None)                       # app_demo.py must switch it on by itself
from streamlit.testing.v1 import AppTest
from pptx import Presentation
res = []
def ok(n, c, d=""):
    res.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (" | " + str(d)[:200] if d else ""), flush=True)

at = AppTest.from_file(os.path.join(ROOT, "app_demo.py"), default_timeout=300).run()
ok("D1 launches with no exception; no file uploader; a 'Use the sample data' button; the demo notice", not at.exception and len(at.get("file_uploader")) == 0 and any(b.key == "use_sample" for b in at.button) and any("Uploading is switched off" in i.value for i in at.info), str([e.value for e in at.exception]))
t0 = time.time()
[b for b in at.button if b.key == "use_sample"][0].click().run()
dt = time.time() - t0
sr = at.session_state["simple_result"] if "simple_result" in at.session_state else None
ok("D2 one click builds a deck for each of the 3 customers", not at.exception and sr is not None and sr["report"]["ok"] and len(sr["customers"]) == 3 and all(c["deck"] for c in sr["customers"].values()), str([e.value for e in at.exception]))
print(f"INFO click-to-result: {dt:.1f} s on this machine", flush=True)
ok("D3 the ZIP and per-customer downloads are offered; the message says draft only", any(d.label.startswith("Download all 3 decks") for d in at.get("download_button")) and any("Draft only" in s.value for s in at.success))
p = Presentation(io.BytesIO(sr["customers"]["CUST001"]["deck"]))
cover = " ".join(sh.text_frame.text for sh in p.slides[0].shapes if sh.has_text_frame)
ok("D4 the demo decks carry the synthetic label and DRAFT", "Synthetic demonstration data, not audited" in cover and "DRAFT" in cover)
ok("D5 the sidebar warns not to use real customer data", any("do not use real customer data" in c.value.lower() for c in at.sidebar.caption), str([c.value for c in at.sidebar.caption]))
at.sidebar.toggle[0].set_value(True).run()
radios = [r for r in at.radio if r.label == "Source"]
ok("D6 Advanced mode in the demo offers the sample pack only (no upload option)", not at.exception and len(radios) == 1 and list(radios[0].options) == ["Sample pack (default demo)"] and len(at.get("file_uploader")) == 0, str([list(r.options) for r in radios]))
print(f"\n{sum(res)}/{len(res)} passed"); sys.exit(0 if all(res) else 1)
