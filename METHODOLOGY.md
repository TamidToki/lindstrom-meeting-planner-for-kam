# Methodology note

**Purpose.** Support an annual customer review: what value did the customer receive, how does the circular service compare with a selected alternative, what to improve next. Prototype, not an audited sustainability report.

## 1. Data handling
1. *Ingest.* All sheets of all uploaded workbooks are read. The header row is detected; every row keeps its source file, sheet and Excel row number.
2. *Classification and mapping.* Each sheet is scored against every internal table (column coverage 45 %, required-field match 35 %, sheet-name similarity 20 %). Sheets below 0.50 are treated as documentation. Columns are matched by normalised name, alias list and value pattern (ID-like, text, numeric, month, timestamp, status). Approximate matches that share no meaningful word are not trusted. The user confirms or edits the result.
3. *Units.* Detected from the header and applied as an editable factor to the internal unit (kg, L, kWh, kgCO2e, EUR, hours, percent). Fractions in a percent column are detected and ×100.
4. *Validation.* See README; every issue carries severity, location, explanation and fix. ERROR = result probably wrong or impossible; WARNING = result may mislead; INFO = context.
5. *Correct and continue.* Row-level defects (duplicates, negatives, non-numeric, orphans, impossible timestamps) default to *exclude*; dataset-level inconsistencies (totals disagree, volumes inconsistent) default to *keep & flag* because the data alone cannot show which side is wrong. Rows left without a site after exclusions are removed too. Every exclusion is logged with the reason.
6. *Calculation.* Only the cleaned tables are used. Missing data disables the affected metrics, which are listed with the reason; the app never substitutes invented defaults.

## 2. Calculations (all deterministic, in `metrics.py`)
- **Allocated laundry use.** For each customer row: kg × laundry intensity (L/kg, kWh/kg, kgCO2e/kg, waste/kg) of the same laundry and month. Intensities come from the per-kg columns, or total ÷ washed kg when only totals exist. Rows without a matching laundry-month are excluded from allocated metrics and the coverage is shown.
- **Saved vs baseline.** Σ kg × baseline intensity − Σ kg × allocated intensity, for water, energy and emissions (process + delivery). Baseline selectable (local laundry default, home, in-house).
- **Repairs.** Repairs = Σ repair_count; postponed replacements = repairs × factor; purchases avoided (EUR) = Σ repair_count × product purchase cost × factor (direct avoided purchase only); avoided product emissions = stated avoided kgCO2e, or repairs × product footprint, × factor.
- **Waste.** kg × laundry waste per washed kg; recycled/reused share from treatment routes.
- **Service.** On-time % from performance_flag; cycle hours; service requests; garment utilisation = scanned ÷ allocated garments (last month).
- **Reconciliation.** Totals recomputed from detail rows reproduce the pack's control totals within 1 % (10 of 10 for the sample pack). The pre-calculated impacts sheet is used only as a cross-check.

## 3. Ranges (Low / Base / High)
Base = values as supplied. Low = conservative, High = favourable: baseline intensities ∓ 20 %, allocated use ± 10 %, repair factor 0.5 / 1.0. These sensitivities are this app's assumptions (the pack gives no uncertainty) and are editable. Metrics that involve no assumption are labelled *exact*. The ranges show, for example, that the water saving versus the local-laundry baseline is highly sensitive to the baseline choice.

## 4. Status labels
Each number carries (a) how it was produced (calculated, allocated, estimated) and (b) the data_status of its input sheets (e.g. SYNTHETIC; unlabelled inputs are named). Synthetic or estimated values are never presented as audited or verified.

## 5. Footprint vs handprint
Footprint: allocated resource use and emissions of the service. Handprint: savings versus the baseline and avoided purchases through repair. Handprint figures are estimates driven by the baseline and the 1:1 repair assumption (pack A002).

## 6. Personalisation and AI
Priority text is parsed by keyword rules (optionally an LLM) into themes that reorder metrics and the story; industry defaults come from the Industry_Priorities sheet. Recommendations are rules over calculated facts and cite their basis. An LLM, if configured, may only rephrase the template text; any rewrite containing a number not in the template is rejected.

## 7. KAM views, opportunities and Ask
- **Portfolio**: each customer's figures come from `metrics.py`; the customer → country → laundry flow sums washed kg. Laundries shared between customers are named because their resource figures are allocated by washed kg.
- **Site attention flag**: robust outlier against the customer's own other sites (median and MAD, z ≥ 1.5) with a minimum effect size (utilisation ≥ 3 pp, on-time ≥ 1 pp, requests ≥ 25 % above median) on at least two indicators, or z ≥ 3 on one. Needs at least four sites. A signal to ask about, not a diagnosis.
- **Repair rate** = repairs ÷ mean monthly allocated garments of that product (per year). A warning is raised above 2 repairs per garment per year. In the pack the rates are 0.26 to 0.83, similar across products, so the repair topic is a prompt for discussion, not a finding.
- **Opportunity cards** are hypotheses: evidence from the customer's own data, sizing in units (garments, requests, litres), assumptions, and questions to confirm. No revenue or sales figure is produced. Peer comparisons appear only in the internal view, never in the customer deck.
- **Garment-control view** counts garments whose last delivery is more than N days before the end of the data; N is an editable, illustrative threshold. RFID is shown per site, never per named wearer.
- **Challenge panel**: the break-even water intensity (the saving holds for any alternative above Lindström's allocated L/kg), the saving under each pack baseline, purchases avoided at 25/50/100 % of repairs, allocation sensitivity, wearer double-counting and data-quality caveats.
- **Ask the data**: seven deterministic tools. The model chooses tools and words the result; any answer containing a number that no tool returned (beyond display rounding) is rejected and replaced by the rule-based answer. Without an API key the rule-based answer is always used.
- **Customer deck**: built from that customer's metrics only; validation notes that name another customer, site or id are removed; no cross-customer benchmark.

## 8. Limitations
Synthetic data; illustrative baselines and footprints; allocation by washed kg is a simplification; site flags are relative; auto-mapping can mis-map unusual headers (hence the confirmation step); validation cannot know which side of a mismatch is right; the sample pack has a laundry-volume inconsistency (L003).
