# Astryx KAM app (UI demo)

A web front-end for the Lindström Customer Value & Sustainability Review,
built with [Astryx](https://github.com/meta/astryx) (Meta's open-source
design system, MIT licence, React 19). It lives on the `astryx-ui` branch
only; the Streamlit meeting planner (repo root) and the Lovable app
(`lovable-app/`) are untouched and remain the reference prototypes.

It re-presents the numbers computed by this repo's own headless pipeline
(`pipeline.run_all` on the synthetic sample pack) and its deterministic
metric engine - the same figures, statuses, formulas, opportunities and
recommendations the Streamlit app shows. It changes nothing about the data
or the calculations. This is a demo, not a production tool.

## Run

```bash
cd astryx-app
npm install
npm run dev        # http://localhost:5173
```

`npm run build` + `npm run preview` serves the production build. The build is
static (base `./`), so `dist/` can be hosted on any static host.

## Data

The app reads `public/data/demo-data.json`, committed so the demo runs
without Python. Regenerate it from the repo root:

```bash
python astryx-app/scripts/export_data.py
```

The exporter drives the real pipeline on `data/pack.xlsx` (synthetic sample
data) with default headless decisions - no uploads, no row exclusions, no
LLM rewrites.

## What it covers (and what it does not)

- Portfolio: customer cards with key figures and attention badges, share of
  portfolio, full site table.
- Customer: headline figures, monthly trend, the full metric set with status
  and formula, site drill-down table.
- Meeting brief: account story, ranked discussion topics with evidence and
  questions to ask, recommendations.
- Data & method: validation issues and method notes.

Not ported from the Streamlit app: Excel upload + mapping confirmation, the
row-exclusion workflow, the Analyst chat, what-if scenarios, and PowerPoint
export. Those remain in the Streamlit prototype.

## Honesty notes

- All data is the **synthetic sample pack**: fictional customers and sites.
- Water/energy/CO2 savings are versus the pack's illustrative baselines and
  carry Low-High ranges; statuses CALCULATED / ALLOCATED / ESTIMATED say how
  each number was produced.
- Charts use recharts; everything else is Astryx components and the neutral
  theme.
