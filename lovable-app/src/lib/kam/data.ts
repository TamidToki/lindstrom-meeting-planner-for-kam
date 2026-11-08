import pack from "@/data/pack.json";

export type Customer = {
  customer_id: string;
  source_customer_id?: string;
  customer_name: string;
  industry: string;
  segment: string;
  hq_country: string;
  priority_topics: string;
};
export type Site = {
  site_id: string;
  source_site_id?: string;
  customer_id: string;
  site_name: string;
  country: string;
  city: string;
  site_type: string;
  primary_laundry_id: string;
};
export type Product = {
  product_id: string;
  product_name: string;
  product_group: string;
  avg_weight_kg: number;
  synthetic_product_footprint_kgco2e: number;
  synthetic_purchase_cost_eur: number;
};

/** One month × site × product line, aggregated from Service_Activity, Customer_Impacts, Repairs, Service_Cycles. */
export type Row = {
  id: number;
  month: string;
  site: string;
  product: string;
  laundry: string;
  wearers: number;
  allocated: number;
  washed: number;
  kg: number;
  requests: number;
  water: number;
  energy: number;
  co2: number;
  deliveryCo2: number;
  textileWaste: number;
  waterSaved: number;
  energySaved: number;
  co2Saved: number;
  repairs: number;
  postponed: number;
  avoidedCo2: number;
  cycles: number;
  cycleHours: number;
  onTime: number;
  recycledKg?: number | undefined;
  repairBreakdown?: Record<string, number>;
};

const cols = pack.cols as string[];
export const rows: Row[] = (pack.rows as (string | number)[][]).map((r, id) => {
  const o: Record<string, string | number> = { id };
  cols.forEach((c, i) => (o[c] = r[i] ?? 0));
  return o as unknown as Row;
});

export const customers = pack.customers as Customer[];
export const sites = pack.sites as Site[];
export const products = pack.products as Product[];
export const laundries = pack.laundries as { laundry_id: string; laundry_name: string; country: string }[];
export const repairTypes = pack.repairTypes as [string, string, number][];
export const waste = pack.waste as {
  laundry_id: string;
  recycling_kg: number;
  reuse_kg: number;
  energy_recovery_kg: number;
  incineration_kg: number;
  textile_waste_total_kg: number;
}[];
export const industryPriorities = pack.industryPriorities as {
  industry: string;
  priority_rank: number;
  priority_theme: string;
  dashboard_emphasis: string;
}[];

export const siteById = Object.fromEntries(sites.map((s) => [s.site_id, s]));
export const productById = Object.fromEntries(products.map((p) => [p.product_id, p]));
export const laundryById = Object.fromEntries(laundries.map((l) => [l.laundry_id, l]));
export const months = Array.from(new Set(rows.map((r) => r.month))).sort();

export type Dataset = {
  rows: Row[];
  customers: Customer[];
  sites: Site[];
  products: Product[];
  laundries: typeof laundries;
  repairTypes: typeof repairTypes;
  waste: typeof waste;
  industryPriorities: typeof industryPriorities;
};

export const sampleDataset: Dataset = { rows, customers, sites, products, laundries, repairTypes, waste, industryPriorities };

export const rowKey = (r: Pick<Row, "month" | "site" | "product">) => `${r.month}|${r.site}|${r.product}`;

/** Existing month/site/product lines win, so re-importing cannot double count. */
export function mergeDataset(base: Dataset, incoming: Dataset): Dataset {
  const merge = <T,>(a: T[], b: T[], key: (v: T) => string) => {
    const map = new Map(a.map((v) => [key(v), v]));
    b.forEach((v) => { if (!map.has(key(v))) map.set(key(v), v); });
    return [...map.values()];
  };
  const keys = new Set(base.rows.map(rowKey));
  let id = base.rows.reduce((n, r) => Math.max(n, r.id), -1) + 1;
  const added = incoming.rows.filter((r) => !keys.has(rowKey(r))).map((r) => ({ ...r, id: id++ }));
  return {
    rows: [...base.rows, ...added],
    customers: merge(base.customers, incoming.customers, (v) => v.customer_id),
    sites: merge(base.sites, incoming.sites, (v) => v.site_id),
    products: merge(base.products, incoming.products, (v) => v.product_id),
    laundries: merge(base.laundries, incoming.laundries, (v) => v.laundry_id),
    repairTypes: added.length ? [...base.repairTypes, ...incoming.repairTypes] : base.repairTypes,
    waste: merge(base.waste, incoming.waste, (v) => v.laundry_id),
    industryPriorities: merge(base.industryPriorities, incoming.industryPriorities, (v) => `${v.industry}|${v.priority_rank}`),
  };
}
