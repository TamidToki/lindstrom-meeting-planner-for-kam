# Clearer layout first, save that version, then the hackathon brand

## Phase 1: Layout improvements (keeps the current look and name)
- Top bar: logo, the 3 steps, and the Default/Advanced switch.
- New **Context Bar** under it, shown on every page:
  - Large company picker with chips (industry · sites · wearers).
  - "+ Import Excel" button beside the company picker.
  - Period presets: Last 3M · Last 6M · YTD · Last 12M · a specific year · All. Presets with no data are greyed out, and periods are counted back from the latest month in the data.
  - A highlighted "Ask AI about this account" button.
- The small phone screen works: the bar wraps into rows.

## Phase 2: Save this version (you do this in GitHub)
- GitHub is already connected, so Phase 1 syncs automatically.
- In GitHub, create a tag or branch called `v2-generic` from the latest commit. It keeps the improved, unbranded version for your repo.

## Phase 3: Company-presentable version (Lindström)
- Name: "Lindström KAM Assistant" in the header and page titles.
- Colours: Lindström-style deep blue as the main colour, a bright light-blue accent, a clean white/light-grey background, and a matching dark mode.
- Font: a clean Scandinavian-style sans font (for example Manrope).
- Simple wordmark logo. No official logo files are used unless you provide them.

## Technical details
- `year` state is generalised to `period` (preset id or year). The metrics filter becomes a month range, and deltas compare the first half vs the second half of the range.
- A new `ContextBar` component takes over the selectors from `AppShell`.
- Tests are added for the presets: Last 3M = the latest 3 months in the data, YTD = Jan through the latest month of the latest year, unavailable presets disabled.
- Branding changes only design tokens in `src/styles.css`, the font link in `__root.tsx`, the names and heads, so a rollback means one revert.
- Memory gets the brand, and `AGENTS.md` gets the period rule. `roadmap.md` tracks the 3 phases.
