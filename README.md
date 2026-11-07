**Quick start:** unzip, then double-click `Start_Meeting_Planner.bat` (Windows) or `Start_Meeting_Planner.command` (Mac). It sets itself up the first time. See `START_HERE_first.txt`. Public demo for judges: see `README_DEPLOY.md`. Trust-pass changes and limits: `TRUST_PASS_NOTES.md`.

# Customer Value & Sustainability Review (Lindström x Since AI 2026)

A tool for the Lindström Key Account Manager (KAM), who looks after several customers with several sites each.
It shows the whole portfolio and how customers, countries and laundries relate; opens one customer at a time; prepares the yearly
meeting (evidence-backed topics for new business, and the questions the customer is likely to ask); answers questions in plain language
with every number checked against a calculation; and exports a PowerPoint that contains only that customer. It works on any set of
Lindström Excel files, not only the sample pack, and shows what it understood before it calculates anything.

## Run
    pip install -r requirements.txt
    streamlit run app.py          # sample pack loads as the default demo
    python tests/test_breaks.py   # break-the-pack tests (about 2-3 minutes), writes tests/TEST_REPORT.md
Optional: `export ANTHROPIC_API_KEY=...` lets an LLM phrase the summary, parse free-text priorities and word answers in 'Ask the data'. Without it the app works fully (keyword rules, template text). **No number ever comes from an LLM**; if an LLM rewrite contains a number that was not in the template it is discarded.

## Tabs
| Tab | Purpose |
|---|---|
| ① Data: load & check | first tab: choose the sample or upload files (step 1), confirm how sheets were understood (step 2), review issues and decide (step 3). A status line above every tab says where the data stands and links you back here |
| Portfolio | customers side by side, all sites across customers (filter, attention only), customer → country → laundry flow, garment treemap, shared laundries |
| Customer | standing account summary at the top, value delivered with Low–High ranges, monthly trend, countries and sites, site drill-down, "what if" with the customer's own litres/kg and repair-to-purchase share |
| Meeting brief | meeting focus, story, ranked discussion topics (internal evidence, assumptions, questions to ask), "be ready to be challenged" with break-even, industry lens, **agreed actions** (owner, customer owner, date, status) carried into the deck, per-customer PowerPoint |
| Analyst | a conversational analyst with a standing account summary beside it: drill down, compare, follow a thread, what-ifs, brainstorm. Answers = short read + key numbers with status badges + charts + hypotheses + follow-up questions. See "The Analyst" below |
| Method & data readiness | assumptions, data gaps, methodology |

## Data workflow
1. **① Data, steps 1–2.** Upload several .xlsx files (any sheet names, column names, order, units). Each sheet is classified into the internal model
   (customers, sites, products, laundries, service activity, repairs, service cycles, resources, waste, baselines, assumptions, plus optional pre-calculated impacts and control totals).
   Columns are mapped by name similarity, aliases and value patterns; units are detected from headers (tonnes, m³, MWh, tCO2e, minutes, k€, fractions) and shown as an editable factor.
   You confirm or fix every mapping, set a sheet to "ignore", or untick "use this sheet". Nothing is calculated before you confirm.
2. **① Data, step 3: validation.** A cross-sheet report: severity, sheet, row or site, plain explanation, suggested fix. For issues that point at rows you choose *Exclude rows* or *Keep & flag*; you can also exclude rows by Excel row number.
3. **Apply and calculate.** Metrics use only rows that passed. Excluded rows are listed with the reason (dashboard banner, exclusion table, deck slide).
4. **Dashboard / PowerPoint.** Every number shows its status badge, a Low–High range, and a "How is this calculated?" panel (formula, inputs, input-data status, source tables, what was varied).

## Modules
| File | Role |
|---|---|
| `schema.py` | internal data model: tables, fields, aliases, units, limits, status vocabulary |
| `data_loader.py` | read workbooks, classify sheets, auto-map columns and units, build canonical tables |
| `validation.py` | all cross-sheet checks, issue records, exclusions (correct and continue) |
| `metrics.py` | deterministic metrics with formula, inputs, status, range (pandas arithmetic only) |
| `assumptions.py` | every assumption/threshold the app itself introduces (sensitivity, tolerances, plausibility) |
| `story.py` | priority parsing, ordering, recommendations, narrative |
| `portfolio.py` | KAM views: portfolio, flows, monthly trend, stale-asset view, opportunities, challenge panel, per-customer issue filter |
| `analyst.py` | the Analyst: exact query engine (any measure × any dimension × filters), what-if, calc, site profile, snapshot and 10 more tools; structured answers; number verification; rule-based analyst with memory |
| `export_pptx.py` | editable PowerPoint (native text, tables, charts) |
| `pipeline.py` | orchestration + data-readiness table |
| `app.py` | Streamlit UI |
| `tests/test_breaks.py` | 30 cases: 19 break-the-pack, deck leakage, opportunities, stale assets, flag rule, repair-rate check, and 6 Analyst checks (number guard with fake models, query = metrics, what-if exactness, calc guard, chart/hypothesis guard, conversation thread) |
| `ARCHITECTURE.md` | one-page architecture diagram |
| `METHODOLOGY.md`, `DATA_READINESS.md` | notes (also shown in the app) |

Data pack: `data/pack.xlsx` (the default demo). Replace by uploading your own files.

## The Analyst
*What it can do.* `query` aggregates any of 21 measures (washed kg, garments, utilisation, requests per 1000, on-time, cycle hours, late cycles, repairs and repair rate,
water/energy/CO2e saved with Low/High, postponed replacements, purchases avoided …) by any of 11 dimensions (customer, country, city, site, site type, product, product group,
month, quarter, laundry, repair type) with filters and period. Around it: `account_snapshot`, `site_profile` (vs the customer's site median, rank, product mix, trend),
`flagged_sites` (with reasons), `what_if` (baseline, customer's own L/kg or kWh/kg, share of repairs that prevent a purchase, utilisation or on-time target, hygiene threshold,
exclude a site or laundry, sensitivity ±%), `compare_baselines`, `stale_garments`, `opportunities`, `challenges`, `industry_context`, `data_issues`, `metric_detail` and `calc`.

*Why it cannot invent a number.* The model only picks tools and words the answer through a structured `respond` call. Code then checks every number in the text,
key numbers and hypotheses against the tool results of the conversation (rounding and k/M allowed). A failing answer is sent back once with the offending numbers;
if it still fails, the rule-based answer is shown with a note. Status badges (Calculated / Estimate · allocated / Estimate · assumption / What-if / Hypothesis) are looked
up in the tool result by code, not taken from the model. Charts are drawn by code from a tool result's rows. Differences and shares go through `calc`, which refuses operands no tool returned.

*Without an API key* a rule-based analyst drives the same tools, keeps the thread ("drill into that site", "same by country") and returns the same answer format.
`ANALYST_MODEL` overrides the model (default `claude-sonnet-5-5`).

## What the validation checks
Missing required sheets/columns (with consequence) · non-numeric, blank and unreadable values · exact and conflicting duplicates · negative values · values above limits (percent > 100, share > 1) ·
implausible units (litres/kg, kWh/kg, kg per piece, cycle hours vs timestamps) · timestamps out of order · waste routes vs total · missing months and calendar gaps ·
site/customer/laundry/product present in one sheet but not another · customer hierarchy conflicts · washed kg between sheets · customer kg vs laundry kg · control totals vs detail rows ·
status labels (missing, blank, unrecognised, inconsistent spelling, measured mixed with synthetic, status not matching content).

## Known finding in the supplied sample pack
Laundry **L003 (Nordic Malmö)** reports ~2 600 kg/month while customers are allocated ~28 000 kg/month there (shares of 960–1 260 %). The validator reports this as an ERROR (kept by default because metrics use per-kg intensities, which do not depend on the absolute volumes). Worth checking with the data owner.

## Limits
All data is synthetic/illustrative; baselines and product footprints are not approved values. Repair assumption: 1 repair = 1 postponed replacement (Low case 0.5).
Sensitivity ranges (baseline ±20 %, allocation ±10 %) are this app's own assumptions, editable in the sidebar. Site flags are relative to the customer's own sites.
Wearers are summed across products (possible double counting). Show data at group/site level, never named people (GDPR).
