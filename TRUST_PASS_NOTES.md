# Trust pass on v11: how to run, what changed, what is still limited

Status: **draft-only**. The KAM must review every deck before customer use.

## How to run
**Windows (easiest):** unzip the whole folder (right-click, Extract All), then double-click `Start_Meeting_Planner.bat`.
First start: it finds Python 3.10 or newer (it prefers 3.12 and 3.11). If Python is missing it installs Python 3.12 for you with `winget` (Windows 10/11) and asks you to double-click again; if `winget` is not there it opens the Python download page. It then sets up a private environment (a few minutes, needs internet, once only) and opens the browser. Details and a "nothing happens" checklist are in `START_HERE_first.txt`; failures are written to `launch_log.txt`.
**Mac:** double-click `Start_Meeting_Planner.command`.
**By hand (any system):**

    python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
    pip install -r requirements.txt
    python -m streamlit run app.py

Then: press "or try it with sample data" (or drop your own .xlsx files). The decks are built automatically, one per customer; with several customers you get `Meeting_plans.zip` plus one download per customer, in the browser's download folder. If you change a review decision the old downloads are disabled until you press **Rebuild now**. If a deck fails, the page says "X of Y meeting decks built" and the ZIP holds `INCOMPLETE_BUILD.txt` and `<Customer>/DECK_NOT_BUILT.txt`.

**Public demo for judges:** `README_DEPLOY.md`. Host `app_demo.py`: sample data only, uploads off, AI off.

## What changed
1. **Draft and data status.** The "Synthetic demonstration data" label appears only on sample data; a real upload says "Draft: the KAM must review before customer use". Nothing says the DRAFT banner goes away or is removed, and reviewing flagged data is not described as approval.
2. **Copilot paste-back.** The customer named in the pasted block is read and checked. Another customer, or one not in this build: blocked with a plain error. No name: the list is previewed and needs a ticked "I confirm this list is for <customer>". All pasted text is marked TEXT NOT VERIFIED with a footer; it never changes data, calculations or decisions.
3. **Exports.** "Ready" is never shown when a deck failed. Downloads are tied to the files, the review decisions and the sample/real flag; if any changed they are hidden until "Rebuild now". Clearing the uploads clears the old result. A different set of files starts with no old choices. Choosing the default for an issue is not stored as a decision.
4. **Priorities slide.** Topics are matched by their own words only: no match shows "No direct measure available in this data. Ask how they track it."; cost topics show the number with a PROXY · CONFIRM chip; hygiene shows no measure. The service theme is "Service & delivery". A deck with no flagged threshold says that this is not proof that service is healthy.

## Remaining limits
- Draft-only. The KAM must review before customer use. There is no reviewer name, sign-off or approval state.
- **Windows was not tested.** There was no Windows machine here. The tested route is Python plus `python -m streamlit run app.py` (Linux, Python 3.13). The `.bat` launcher, its automatic Python install through `winget`, and the Mac `.command` file were read and edited carefully but never run. It is not a no-install package: Python (or winget) and an internet connection are needed on first start. Do one dry run on a Windows laptop before relying on it.
- The public demo was tested through Streamlit's test runner, not on a live host. The `Dockerfile` (Hugging Face) was not built here. Nobody has deployed it yet: that needs your GitHub and Streamlit/Hugging Face login (`README_DEPLOY.md`).
- Keys/Grok are untouched. No live Copilot API, no chat editing, no deployment.
- Pasted Copilot text is unverified and cannot change data, calculations or decisions.
- The customer name in a pasted block must match a customer exactly after ignoring case and punctuation ("NorthStar" does not match "NorthStar Foods Group"); a short name is blocked as unmatched rather than guessed.
- Slides were rendered with LibreOffice only, not with PowerPoint.

## Also changed in this v13 final build (beyond the four fixes)
- `app_demo.py` (forces demo mode), Advanced mode offers only the sample in demo mode, a "do not use real customer data" sidebar notice, `Dockerfile`, `.gitignore`, `requirements.txt` with compatible version ranges and `requirements-tested.txt` with the exact tested versions, `README_DEPLOY.md`, tidier Streamlit toolbar.
- Speed (no change to any number): the source workbook is parsed once per build instead of once per customer, and the whole-portfolio table is computed once per build. Sample click-to-decks went from about 39 s to about 21 s on the test machine. A shared cloud server will be slower; expect up to a minute on the first click.
- The Windows launcher now prefers Python 3.12/3.11/3.13/3.10 before "any Python".
- New test `tests/test_demo.py` (6 checks).
