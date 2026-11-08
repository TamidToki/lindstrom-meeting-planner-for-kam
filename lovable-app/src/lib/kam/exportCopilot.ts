import type { Dataset, Row } from "./data";
import { siteStats, totals, type Band } from "./metrics";

/** Builds the Copilot master workbook: verified summary, active rows and a plain-language data dictionary. */
export async function exportCopilotWorkbook(customerName: string, industry: string, rows: Row[], band: Band, data: Dataset) {
  const XLSX = await import("xlsx");
  const t = totals(rows, data);
  const sites = siteStats(rows, data);

  const summary = [
    ["Customer Name", customerName],
    ["Industry", industry],
    ["Sites", sites.length],
    ["Garments in circulation (latest month)", t.inCirculation],
    ["Utilisation % (weekly washes / allocated garments)", +t.utilisation.toFixed(1)],
    ["Healthy utilisation band", `${band.low}% to ${band.high}%`],
    ["Washes per wearer per week", +t.washesPerWearerWeek.toFixed(2)],
    ["Repair rate (repairs per 100 washes)", +t.repairRate.toFixed(2)],
    ["Cost avoided (EUR)", Math.round(t.costAvoided)],
    ["CO2 saved (kg)", Math.round(t.co2Saved)],
    ["Water saved (litres)", Math.round(t.waterSaved)],
  ];

  const siteName = (id: string) => data.sites.find((s) => s.site_id === id)?.site_name ?? id;
  const productName = (id: string) => data.products.find((p) => p.product_id === id)?.product_name ?? id;
  const active = rows.map((r) => ({
    Month: r.month,
    Site: siteName(r.site),
    "Garment Product": productName(r.product),
    Washes: r.washed,
    "Allocated Garments": r.allocated,
    Repairs: r.repairs,
    "In Circulation": r.allocated,
  }));

  const dictionary = [
    ["Metric", "Plain-language definition"],
    ["Utilisation %", "Weekly washes divided by allocated garments. Shows how much of the rented stock is actually used."],
    ["Healthy band", `Utilisation between ${band.low}% and ${band.high}% is healthy for this industry. Below it, garments sit unused; above it, stock is tight.`],
    ["Washes per wearer per week", "Total washes divided by wearers and weeks. A hygiene indicator."],
    ["Repair rate", "Repairs per 100 washes. High values can point to heavy work or wrong garment choice."],
    ["Cost avoided", "Estimated purchase cost of garments that did not need replacing because repairs were postponed or avoided."],
    ["CO2 saved", "Kilograms of CO2 emissions avoided compared with buying new garments."],
    ["Water saved", "Litres of water saved through laundry optimisation versus conventional washing."],
    ["In circulation", "Garments allocated to the customer in the latest month."],
    ["Allocated garments", "Garments assigned to a site for a given month."],
  ];

  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(summary), "Customer_Summary");
  XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(active), "Active_Data");
  XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(dictionary), "Data_Dictionary");
  XLSX.writeFile(wb, `${customerName.replace(/\s+/g, "_")}_copilot_pack.xlsx`);
}

/** Executive prompt card the KAM pastes into Microsoft Copilot together with the workbook. */
export function copilotPrompt(customerName: string, industry: string, band: Band) {
  return `# LINDSTRÖM KAM COPILOT INSTRUCTIONS: ${customerName}
You are an executive analyst for Lindström workwear service reviewing ${customerName} (${industry}).
Attached is the verified master workbook.

Rules:
- Use ONLY figures from the attached Excel workbook.
- Utilisation is weekly washes divided by allocated garments (Healthy band: ${band.low}% to ${band.high}%).
- If a metric is missing or unverified, state it plainly. Do not invent numbers.

First task: Summarise the top 3 opportunities for our meeting with ${customerName} based on the attached sheets.`;
}
