import { rowKey, sampleDataset, type Dataset } from "./data";

export type DataGroup = { key: string; customerId: string; company: string; year: string; count: number; source: string };
export const dataGroupKey = (customerId: string, year: string) => JSON.stringify([customerId, year]);
export const emptyDataset = (): Dataset => ({ rows: [], customers: [], sites: [], products: [], laundries: [], repairTypes: [], waste: [], industryPriorities: [] });
const demoKeys = new Set(sampleDataset.rows.map(rowKey));

/** Company × year is the removable dataset unit, including demo and imported rows. */
export function dataGroups(data: Dataset): DataGroup[] {
  const sites = new Map(data.sites.map((s) => [s.site_id, s.customer_id]));
  const names = new Map(data.customers.map((c) => [c.customer_id, c.customer_name]));
  const groups = new Map<string, DataGroup & { demo: number }>();
  for (const row of data.rows) {
    const customerId = sites.get(row.site);
    if (!customerId) continue;
    const year = row.month.slice(0, 4);
    const key = dataGroupKey(customerId, year);
    const group = groups.get(key) ?? { key, customerId, company: names.get(customerId) ?? customerId, year, count: 0, source: "", demo: 0 };
    group.count++;
    if (demoKeys.has(rowKey(row))) group.demo++;
    groups.set(key, group);
  }
  return [...groups.values()].map(({ demo, ...g }) => ({ ...g, source: demo === g.count ? "Demo" : demo === 0 ? "Imported" : "Demo + imported" })).sort((a, b) => a.company.localeCompare(b.company) || b.year.localeCompare(a.year));
}

export function removeDataGroups(data: Dataset, selected: string[]): Dataset {
  const keys = new Set(selected);
  const owners = new Map(data.sites.map((s) => [s.site_id, s.customer_id]));
  const rows = data.rows.filter((r) => !keys.has(dataGroupKey(owners.get(r.site) ?? "", r.month.slice(0, 4))));
  if (!rows.length) return emptyDataset();
  const siteIds = new Set(rows.map((r) => r.site));
  const sites = data.sites.filter((s) => siteIds.has(s.site_id));
  const customerIds = new Set(sites.map((s) => s.customer_id));
  const productIds = new Set(rows.map((r) => r.product));
  const laundryIds = new Set(rows.map((r) => r.laundry));
  return { ...data, rows, sites, customers: data.customers.filter((c) => customerIds.has(c.customer_id)), products: data.products.filter((p) => productIds.has(p.product_id)), laundries: data.laundries.filter((l) => laundryIds.has(l.laundry_id)), waste: data.waste.filter((w) => laundryIds.has(w.laundry_id)) };
}