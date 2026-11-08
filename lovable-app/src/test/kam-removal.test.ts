import { describe, expect, it } from "vitest";
import { mergeDataset, sampleDataset } from "@/lib/kam/data";
import { dataGroups, emptyDataset, removeDataGroups } from "@/lib/kam/dataRemoval";
import { findCustomer } from "@/lib/kam/metrics";

describe("saved company-year removal", () => {
  it("lists demo company-year datasets as removable", () => {
    const group = dataGroups(sampleDataset).find((g) => g.customerId === "CUST001" && g.year === "2025");
    expect(group?.source).toBe("Demo");
    expect(group?.count).toBeGreaterThan(0);
  });
  it("removes only the selected company and year while keeping other years and companies", () => {
    const first = dataGroups(sampleDataset)[0];
    if (!first) throw new Error("Missing demo group");
    const sites = new Set(sampleDataset.sites.filter((s) => s.customer_id === first.customerId).map((s) => s.site_id));
    const historical = sampleDataset.rows.filter((r) => sites.has(r.site)).map((r, i) => ({ ...r, id: 100000 + i, month: r.month.replace("2025", "2024") }));
    const data = mergeDataset(sampleDataset, { ...emptyDataset(), rows: historical });
    const result = removeDataGroups(data, [first.key]);
    expect(result.rows.filter((r) => sites.has(r.site) && r.month.startsWith("2025"))).toHaveLength(0);
    expect(result.rows.filter((r) => sites.has(r.site) && r.month.startsWith("2024"))).toHaveLength(historical.length);
    expect(result.rows.filter((r) => !sites.has(r.site))).toEqual(data.rows.filter((r) => !sites.has(r.site)));
    expect(sampleDataset.rows.filter((r) => sites.has(r.site)).length).toBeGreaterThan(0);
  });
  it("removes all data including demos and leaves no account references", () => {
    const result = removeDataGroups(sampleDataset, dataGroups(sampleDataset).map((g) => g.key));
    expect(result).toEqual(emptyDataset());
    expect(findCustomer("CUST001", result).customer_id).toBe("");
  });
  it("allows deleted data to be imported again", () => {
    const restored = mergeDataset(emptyDataset(), sampleDataset);
    expect(restored.rows).toHaveLength(sampleDataset.rows.length);
    expect(restored.customers).toEqual(sampleDataset.customers);
  });
});