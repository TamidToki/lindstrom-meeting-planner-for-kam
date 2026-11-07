# Round 7 test report

| # | Case | Result | Evidence |
|---|---|---|---|
| 1 | Renamed workbook (Location ID / Plant / SKU, header row 3) runs with no exception and gives identical numbers | ✅ | 19 metrics identical: True |
| 2 | An unmapped join key can never crash validation (dtype guard) | ✅ | 12 issues, no exception |
| 3 | Number guard: a bare small integer is no longer waved through | ✅ | unsupported '2' -> [2.0]; supported '3' -> [] |
| 4 | Master pack: 3 workbooks (one renamed) -> one workbook with every spec sheet; Prompt_Card pasteable | ✅ | ok=True missing sheets=[] card lines=30 files=3 customers=3 |
| 5 | Master pack: source files byte-identical before and after | ✅ | sha256 of 3 inputs unchanged |
| 6 | Master pack from 3 files equals the single-file build (dedup of repeated laundry sheets, renamed file mapped) | ✅ | Analysis, Customer_Summary, Site_Summary numerically identical |
| 7 | Validation_Exceptions lists suspect rows with source file, sheet and Excel row; duplicates across files excluded once | ✅ | L003 rows listed in 2 source sheet(s); 4 duplicate sheet(s) excluded |
| 8 | Measures and Analysis reconcile with the app's own metric engine (11 measures x 3 customers) | ✅ | 36/36 reconcile; mismatches [] |
| 9 | Workbook rules: values only, no merged cells, one header row, no blank rows, IDs as text, ISO dates, every measure has a status | ✅ | 23 sheets clean |
| 10 | Data_Dictionary documents every column of every sheet | ✅ | undocumented: [] |
| 11 | Deterministic: same inputs give the same workbook content | ✅ | 23 sheets equal |
| 12 | Sidecar exclusion: excluded source row leaves the numbers, is listed in Excluded_Rows, source untouched | ✅ | row 2 listed=True; kg 759237.8 -> 758082.7 (row had 1155.1) |
| 13 | Excel row numbers are the rows a person sees (header on row 3, blank rows, two sheets) | ✅ | flagged ['t.xlsx::Activity#6'] |
| 14 | Utilisation band: per-customer override changes 'Why notable', flags and the recorded assumption | ✅ | text changed=True; flags changed=True; recorded: ['85-95 %'] |
| 15 | Industry-aware default is labelled TEAM_ASSUMPTION; default band is 30-70 for other industries | ✅ | food (40.0, 80.0) Industry default (TEAM_ASSUMPTION); industrial (30.0, 70.0) |
| 16 | 'Why notable' never says 'idle' and describes no-scan garments as something to investigate | ✅ | wording ok |
| 17 | Mapping fix in the sidecar: an unrecognised column is mapped once, the build then matches the canonical numbers | ✅ | before fix ok=True (built with the column missing); after fix kg 759237.8 = 759237.8 |
| 18 | Bad input: garbage .xlsx, empty workbook, and a good file next to a bad one -> friendly report, no traceback, good file still built | ✅ | bad only: ok=False 'None of the files could be read as a workbook with data.'; mixed: ok=True, 1 unreadable skipped |
| 19 | CSV and .xlsm-style inputs are discovered; a folder is searched recursively | ✅ | found ['p.xlsx', 'x.csv']; csv read as 1 sheet |
| 20 | Big pack: facts above the threshold go to a separate Detail file; Core stays small | ✅ | core 18 sheets, detail ['Fact_Service_Activity', 'Fact_Repairs', 'Fact_Cycles', 'Fact_Resources', 'Fact_Waste'] |
| 21 | No customer-facing leakage in a single-customer pack: --customer filters facts and dimensions | ✅ | customers in Analysis: {'Mediora Health Network'} |
| 22 | CLI exits 0 on success and non-zero on a hard failure, and always writes a build report | ✅ | exit codes 0/1 |
| 23 | Integrity agent: every check passes on a clean 3-file build (source unchanged, replication, exclusions, consistency, independent engine) | ✅ | {'checks': 211, 'passed': 211, 'failed': 0, 'warnings': 0}; check families ['A', 'B', 'C', 'D', 'E', 'F'] |
| 24 | Integrity agent catches tampering: a corrupted measure fails against the independent engine and the facts | ✅ | 4 FAIL rows in families ['D', 'E'] |
| 25 | Integrity agent: a changed source file is detected (hash before != after) | ✅ | A-check turns FAIL when a hash differs |
| 26 | SQLite working container equals the workbook and is read-only for the model | ✅ | 408 rows, kg 759237.8, write attempt blocked=True |

**26 cases, all pass.**