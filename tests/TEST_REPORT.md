# Break-the-pack test report

Each case modifies the sample pack in memory, runs the full pipeline (ingest → mapping → validation → exclusions → metrics) and checks the expected detection.

Baseline (unmodified pack): {'WARNING': 3, 'INFO': 2, 'ERROR': 1} issues; the only ERROR is the genuine L003 laundry-volume inconsistency in the pack itself.

| # | Break | Detected? | Evidence |
|---|---|---|---|
| 1 | Remove site S005 from Service_Activity only | ✅ yes | WARNING 'site has no rows' + ERROR kg totals differ vs impacts |
| 2 | Remove site S005 from Sites only | ✅ yes | ['impacts', 'repairs', 'service_activity', 'service_cycles']; 594 orphan rows auto-excluded; calculation now sees 23 sites |
| 3 | Change a total: Customer_Impacts washed kg ×1.25 for site S008 | ✅ yes | S008 2025-03: activity 1,618 vs impacts 2,023 kg; S008 2025-03: activity 1,582 vs impacts 1,977 kg; S008 2025- |
| 4 | Change a control total: Sample_Output 'Washed kg 2025' → 450 000 | ✅ yes | Washed kg 2025: sheet says 450,000.0, calculated 502,074.7 (+11.6%) |
| 5 | Delete 400 repair rows (Repairs 2025 control total now wrong) | ✅ yes | Repairs 2025: sheet says 15,233.0, calculated 13,735.0 (-9.8%); Replacements postponed: sheet says 15,233.0, c |
| 6 | Rename column repair_count → 'Repairs completed' | ✅ yes | mapped repair_count ← 'Repairs completed', repairs = 15,233, no new issues |
| 7 | Rename column repair_count → 'qty_xyz' | ✅ yes | ERROR raised; repair metrics reported as not calculable: no repair sheet passed validation |
| 8 | Add 30 exact duplicate rows to Service_Activity | ✅ yes | 30 rows flagged & auto-excluded; washed kg back to 502,074.7 (pristine 502,074.7) |
| 9 | Add conflicting duplicate keys to Repairs | ✅ yes | 5 conflicting rows; first occurrence kept |
| 10 | Negative values (3 repair counts, 2 washed kg) | ✅ yes | 5 rows in ['repairs', 'service_activity'] |
| 11 | Percentage over limit (repair_quotient_pct = 250 on 3 rows) | ✅ yes | 3 value(s) in 'repair_quotient_pct' exceed 100 (max 250). A percentage cannot exceed 100; check whether the column holds |
| 12 | Wrong unit: water per kg in m³ (÷1000) for every laundry row | ✅ yes | ERROR: 48 of 48 rows have litres per kg outside 0.3–60.0 (median 0.00688). Most rows are off, which points to a unit  |
| 13 | Missing months: S003 June removed; laundry L001 September removed from resources | ✅ yes | S003 gap flagged; L001-2025-09 flagged; water coverage 95.7% of washed kg (caveat shown on metrics) |
| 14 | Status labels: blank on 10 rows, 'LOOKS_GOOD', 'measured' mixed into synthetic | ✅ yes | blank / unrecognised / mixed measured+synthetic all raised |
| 15 | Text in a numeric cell ('n/a' in washed kg) | ✅ yes | Service_Activity row 9, column customer_washed_kg |
| 16 | Blank required value (washed kg empty / 'n/a' on 2 rows) | ✅ yes | Service_Activity rows 5, 11; column customer_washed_kg |
| 17 | Cycle timestamps out of order (5 cycles) | ✅ yes | 5 cycles flagged |
| 18 | Remove the Laundry_Resources sheet entirely | ✅ yes | WARNING raised; water/energy/CO2 not calculated, repair metrics still shown (no invented numbers) |
| 19 | Same data, different shape: 3 files, renamed sheets, shuffled/renamed columns, tonnes, m³, MWh, tCO2e, MM/YYYY months | ✅ yes | 11 tables mapped from 3 files; max deviation vs sample on 11 key metrics 9.79e-05; 2 unit-conversion notices; control totals reconcile: 1; errors: ['customer kg exceeds laundry total kg'] |
| 20 | Per-customer deck leaks nothing about other customers | ✅ yes | 3 decks of 13 slides scanned against 34 site names/ids and 2 other customers each; leaks: none |
| 21 | Opportunity cards are evidence-backed and never invent money | ✅ yes | 6 cards for CUST001; complete: True; no revenue claims: True; customer-safe evidence has no peer data: True |
| 22 | Stale-asset count follows the threshold exactly | ✅ yes | 30 d: 1944 (expected 1944); 120 d: 1176 (expected 1176) |
| 23 | Flag rule needs real differences | ✅ yes | noise only: 0 flagged; one site at 60 vs 16 requests per 1000: flagged 1 (site A) |
| 24 | Analyst: no key -> rule-based; invented numbers rejected (after one retry); faithful answer accepted; badges come from the data | ✅ yes | no key: rules; invents twice: rules (The model's answer contained numbers no calculatio…); invents then fixes on retry: llm; faithful: llm with badges {'Water saved': 'ALLOCATED', 'Utilisation': 'CALCULATED'}; no data looked at: rules |
| 25 | Analyst query engine reproduces the headline metrics exactly | ✅ yes | 33 comparisons across 3 customers; largest absolute difference 0.500 = display rounding (1 decimal for rates, whole units for kg/L/kWh) |
| 26 | Analyst what-ifs are exact recalculations | ✅ yes | home baseline 2634436 L vs metrics 2634436 L; postponed 5831 → 2916; utilisation at a 99 % target → 99.0 % |
| 27 | Analyst calc only accepts numbers that tools returned | ✅ yes | 90.5 − 75.6 = 14.9; with an invented operand: operands not found in any tool result: [61.37]. Fetch them w |
| 28 | Analyst charts and hypotheses cannot carry invented numbers | ✅ yes | charts kept 1 of 2; clean hypothesis passes: True; invented number caught: [12.7] |
| 29 | Analyst follows a thread and every rule-based answer is traceable | ✅ yes | thread kept: True (NorthStar Tampere); 20 questions answered, problems: none |
| 30 | Implausible repair rate is caught | ✅ yes | 1 warning(s): 3 customer-product combination(s) show more than 2 repairs per allocated garment per year  |
| 31 | Prepare: priority order follows CRM, attendees and public info, with reasons; override wins | ✅ yes | CRM->cost; procurement+finance->cost; included public point->emissions; industry lens->water; no key: sample: no model configured, 3 sourced sample points |
| 32 | Customer-coloured deck stays readable and leaks nothing | ✅ yes | yellow darkened to lum 0.32; white accent to 0.44; palette restored: True; leaks: none |

**32 cases, all detected.**