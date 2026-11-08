import { describe, expect, it } from "vitest";
import * as XLSX from "xlsx";
import fixture from "./fixtures/reference-workbook.json";
import { parseWorkbook } from "@/lib/kam/importWorkbook";
import { mergeDataset, sampleDataset } from "@/lib/kam/data";
import { customerRows, monthlyTrend, totals } from "@/lib/kam/metrics";

function workbook(year = "2026", newCompany = false) {
  const w = XLSX.utils.book_new();
  for (const [name, records] of Object.entries(fixture)) XLSX.utils.book_append_sheet(w, XLSX.utils.json_to_sheet(records), name);
  for (const name of ["Service_Activity", "Customer_Impacts", "Repairs", "Service_Cycles", "Waste_Circularity", "Customers", "Sites"]) {
    const sheet = w.Sheets[name];
    if (!sheet) continue;
    const records = XLSX.utils.sheet_to_json<Record<string, unknown>>(sheet);
    for (const r of records) {
      if (r["month"]) r["month"] = String(r["month"]).replace("2025", year);
      if (r["pickup_timestamp"]) r["pickup_timestamp"] = String(r["pickup_timestamp"]).replace("2025", year);
      if (newCompany) {
        if (r["customer_id"]) r["customer_id"] = `NEW-${r["customer_id"]}`;
        if (r["customer_name"]) r["customer_name"] = `Imported ${r["customer_name"]}`;
        if (r["site_id"]) r["site_id"] = `NEW-${r["site_id"]}`;
      }
    }
    w.Sheets[name] = XLSX.utils.json_to_sheet(records);
  }
  return w;
}
const buffer = (w: XLSX.WorkBook) => XLSX.write(w, { type: "array", bookType: "xlsx" });

function templateWorkbook(year = "2026", secondCompany = false) {
  const w = workbook(year);
  for (const name of w.SheetNames) {
    const sheet = w.Sheets[name];
    if (!sheet) continue;
    const records = XLSX.utils.sheet_to_json<Record<string, unknown>>(sheet);
    for (const r of records) {
      if (r["customer_name"]) r["customer_name"] = "Template Company";
      if (r["site_id"]) r["site_id"] = "S034";
    }
    if (secondCompany && records.some((r) => r["customer_id"])) {
      records.push(...records.map((r) => ({ ...r, customer_id: "MOCK002", ...(r["customer_name"] ? { customer_name: "Second Template Company" } : {}) })));
    }
    w.Sheets[name] = XLSX.utils.json_to_sheet(records);
  }
  return w;
}

describe("private Excel import", () => {
  it("requires the reference worksheets and validates columns", () => {
    const w = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(w, XLSX.utils.aoa_to_sheet([["month"], ["2026-01"]]), "Service_Activity");
    const result = parseWorkbook(buffer(w), sampleDataset);
    expect(result.errors).toContain("Missing worksheet: Customers.");
    expect(result.errors).toContain("Service_Activity: missing column allocated_pieces.");
  });
  it("merges a new year and repeated imports without double counting or mutating source", () => {
    const result = parseWorkbook(buffer(workbook()), sampleDataset);
    expect(result.errors).toEqual([]);
    expect(result.years).toEqual(["2026"]);
    const merged = mergeDataset(sampleDataset, result.data);
    expect(merged.rows.length).toBe(sampleDataset.rows.length + result.data.rows.length);
    expect(mergeDataset(merged, result.data).rows.length).toBe(merged.rows.length);
    const rows = customerRows("CUST001", new Set(), merged, "2026");
    expect(totals(rows, merged).washed).toBe(totals(customerRows("CUST001", new Set()).filter((r) => r.site === "S001"), sampleDataset).washed);
    expect(monthlyTrend(rows, merged)[0]?.label).toBe("Jan 2026");
    expect(sampleDataset.rows.every((r) => r["month"].startsWith("2025"))).toBe(true);
  });
  it("imports new companies into the same account metrics", () => {
    const result = parseWorkbook(buffer(workbook("2026", true)), sampleDataset);
    expect(result.errors).toEqual([]);
    const merged = mergeDataset(sampleDataset, result.data);
    expect(merged.customers.length).toBe(4);
    const rows = customerRows("NEW-CUST001", new Set(), merged, "2026");
    expect(rows.length).toBeGreaterThan(0);
    expect(totals(rows, merged).costAvoided).toBeGreaterThan(0);
    expect(totals(rows, merged).recycledKg).toBeGreaterThan(0);
  });
  it("blocks invalid numbers and broken site references", () => {
    const w = workbook();
    const sheet = w.Sheets["Service_Activity"];
    if (!sheet) throw new Error("Missing test worksheet");
    const records = XLSX.utils.sheet_to_json<Record<string, unknown>>(sheet);
    const first = records[0];
    if (!first) throw new Error("Missing test row");
    first["allocated_pieces"] = -1;
    first["site_id"] = "missing";
    w.Sheets["Service_Activity"] = XLSX.utils.json_to_sheet(records);
    const result = parseWorkbook(buffer(w), sampleDataset);
    expect(result.errors).toContain("Service_Activity, row 2: allocated_pieces must be a valid non-negative number.");
    expect(result.errors).toContain("Service_Activity, row 2: site/customer reference does not match.");
  });
  it("aliases CUST001 for a new company and keeps all linked sheet metrics isolated", () => {
    const result = parseWorkbook(buffer(templateWorkbook()), sampleDataset);
    expect(result.errors).toEqual([]);
    const company = result.data.customers[0];
    const site = result.data.sites[0];
    if (!company || !site) throw new Error("Missing template identities");
    expect(company.customer_id).not.toBe("CUST001");
    expect(company.source_customer_id).toBe("CUST001");
    expect(site.site_id).not.toBe("S034");
    expect(site.source_site_id).toBe("S034");
    expect(site.customer_id).toBe(company.customer_id);
    const merged = mergeDataset(sampleDataset, result.data);
    const imported = totals(customerRows(company.customer_id, new Set(), merged, "2026"), merged);
    const reference = parseWorkbook(buffer(workbook()), sampleDataset);
    expect(imported.washed).toBe(totals(reference.data.rows, reference.data).washed);
    expect(imported.repairs).toBe(totals(reference.data.rows, reference.data).repairs);
    expect(imported.co2Saved).toBe(totals(reference.data.rows, reference.data).co2Saved);
    expect(imported.onTimePct).toBe(totals(reference.data.rows, reference.data).onTimePct);
    expect(customerRows("CUST001", new Set(), merged, "2026")).toEqual([]);
  });
  it("allows two customers to use S034 in the same workbook without combining rows", () => {
    const result = parseWorkbook(buffer(templateWorkbook("2026", true)), sampleDataset);
    expect(result.errors).toEqual([]);
    expect(new Set(result.data.sites.map((s) => s.site_id)).size).toBe(2);
    const merged = mergeDataset(sampleDataset, result.data);
    const counts = result.data.customers.map((c) => customerRows(c.customer_id, new Set(), merged, "2026").length);
    expect(counts[0]).toBeGreaterThan(0);
    expect(counts[1]).toBe(counts[0]);
    expect(result.data.rows.length).toBe((counts[0] ?? 0) * 2);
  });
  it("reuses aliases on repeated imports and additional years after local serialization", () => {
    const first = parseWorkbook(buffer(templateWorkbook()), sampleDataset);
    const merged = JSON.parse(JSON.stringify(mergeDataset(sampleDataset, first.data)));
    const repeat = parseWorkbook(buffer(templateWorkbook()), merged);
    expect(repeat.errors).toEqual([]);
    expect(repeat.duplicates).toBe(first.data.rows.length);
    expect(repeat.data.customers[0]?.customer_id).toBe(first.data.customers[0]?.customer_id);
    expect(repeat.data.sites[0]?.site_id).toBe(first.data.sites[0]?.site_id);
    expect(mergeDataset(merged, repeat.data).rows.length).toBe(merged.rows.length);
    const next = parseWorkbook(buffer(templateWorkbook("2027")), merged);
    expect(next.errors).toEqual([]);
    expect(next.duplicates).toBe(0);
    const combined = mergeDataset(merged, next.data);
    expect(combined.customers.length).toBe(4);
    expect(combined.sites.length).toBe(merged.sites.length);
    expect(next.data.sites[0]?.site_id).toBe(first.data.sites[0]?.site_id);
    expect(customerRows(first.data.customers[0]?.customer_id ?? "", new Set(), combined, "2027").length).toBe(next.data.rows.length);
  });
  it("still rejects ambiguous repeated site IDs within one customer", () => {
    const w = templateWorkbook();
    const sheet = w.Sheets["Sites"];
    if (!sheet) throw new Error("Missing Sites");
    const records = XLSX.utils.sheet_to_json<Record<string, unknown>>(sheet);
    const first = records[0];
    if (!first) throw new Error("Missing site");
    w.Sheets["Sites"] = XLSX.utils.json_to_sheet([...records, { ...first }]);
    expect(parseWorkbook(buffer(w), sampleDataset).errors).toContain("Sites, row 3: duplicate site_id S034.");
  });
  it("treats casing and extra spaces as the same existing customer name", () => {
    const w = workbook();
    const sheet = w.Sheets["Customers"];
    if (!sheet) throw new Error("Missing Customers");
    const records = XLSX.utils.sheet_to_json<Record<string, unknown>>(sheet);
    for (const r of records) r["customer_name"] = `  ${String(r["customer_name"]).toUpperCase().replace(/ /g, "  ")}  `;
    w.Sheets["Customers"] = XLSX.utils.json_to_sheet(records);
    const result = parseWorkbook(buffer(w), sampleDataset);
    expect(result.errors).toEqual([]);
    expect(result.data.customers[0]?.customer_id).toBe("CUST001");
  });
});