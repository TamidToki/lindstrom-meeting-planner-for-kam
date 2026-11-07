# Data-readiness note

Mapping of prototype fields to future Lindström source types, and the gaps. The app also builds this table live from the uploaded files (tab 4).

| Internal table | Key fields | Future source | Main gaps |
|---|---|---|---|
| Customers / Sites | customer_id, site_id, site→customer, primary laundry | Customer master data / CRM, account top-level hierarchy | Hierarchy mapping (delivery customer → account top level), unmapped sites, industry codes |
| Products | product_id, purchase cost, footprint, weight | Product master + approved LCA values | Approved footprints and replacement costs (currently illustrative) |
| Laundries | laundry_id, country | WWS master data | none significant |
| Service activity | month, site, product, wearers, allocated, scanned, washed kg, requests | Allocated pieces and Washing % Tableau reports | Wearer definition (shared garments), site/product granularity, kg unit |
| Repairs | month, site, product, repair type, count | Monthly repairs table by account top level, delivery customer, product code, laundry, repair name | Link repair to a real avoided replacement; repair cost |
| Service cycles | asset, cycle, pickup/in/out/delivered, cycle hours, flag | End-to-end delivery report (RFID scans) | Asset-level scans; hygiene-control thresholds by industry; GDPR: aggregate to site/group, never named wearers |
| Laundry resources | washed kg, L/kg, kWh/kg, process and delivery CO2e | WWS laundry resource reports | Measured customer-level allocation instead of washed-kg share |
| Waste & circularity | recycling, reuse, energy recovery, incineration | Textile waste kg report | Customer-level attribution |
| Baselines | water, energy, CO2e per kg | Approved comparison calculator | Approved factors with real low/base/high |
| Control totals | washed kg, repairs, savings … | Approved report / Tableau extract | Not always available; used to reconcile |

**Design for replacement.** Swap the synthetic files for approved exports from Tableau, Power BI, Excel or eLindström: the auto-mapping and validation layer absorbs different sheet names, column names, order and units, and reports what is missing. Larger multi-site customers, more countries and further service lines need no redesign (tables are long format keyed by customer/site/month).

**Gaps that block production use:** enterprise customer hierarchy and master data, measured (not allocated) customer resource use, approved factors and uncertainty, a definition of active wearers, data-status labels on every sheet.
