import * as XLSX from "xlsx";
import { rowKey, type Dataset, type Row } from "./data";

type RecordRow = Record<string, unknown>;
export type ImportPreview = {
  data: Dataset;
  sheets: { name: string; count: number; columns: string[]; preview: RecordRow[] }[];
  errors: string[];
  warnings: string[];
  years: string[];
  duplicates: number;
};

const schema: Record<string, string[]> = {
  Customers: ["customer_id", "customer_name", "industry", "segment", "hq_country", "priority_topics"],
  Sites: ["site_id", "customer_id", "site_name", "country", "city", "site_type", "primary_laundry_id"],
  Products: ["product_id", "product_name", "product_group", "avg_weight_kg", "synthetic_product_footprint_kgco2e", "synthetic_purchase_cost_eur"],
  Service_Activity: ["month", "customer_id", "site_id", "laundry_id", "product_id", "active_wearers", "allocated_pieces", "washed_pieces", "customer_washed_kg", "service_requests"],
  Customer_Impacts: ["month", "customer_id", "site_id", "laundry_id", "product_id", "allocated_water_l", "allocated_energy_kwh", "allocated_process_kgco2e", "allocated_delivery_kgco2e", "allocated_textile_waste_kg", "water_saving_vs_local_l", "energy_saving_vs_local_kwh", "emissions_saving_vs_local_kgco2e"],
  Repairs: ["month", "customer_id", "site_id", "product_id", "laundry_id", "repair_type", "repair_count", "estimated_replacements_postponed", "estimated_avoided_product_kgco2e"],
  Service_Cycles: ["customer_id", "site_id", "product_id", "laundry_id", "pickup_timestamp", "cycle_hours", "performance_flag"],
  Laundries: ["laundry_id", "laundry_name", "country"],
  Waste_Circularity: ["month", "laundry_id", "recycling_kg", "reuse_kg", "energy_recovery_kg", "incineration_kg", "textile_waste_total_kg"],
  Industry_Priorities: ["industry", "priority_rank", "priority_theme", "dashboard_emphasis"],
};
const required = ["Customers", "Sites", "Products", "Service_Activity", "Customer_Impacts", "Repairs"];
const numeric = new Set(["avg_weight_kg", "synthetic_product_footprint_kgco2e", "synthetic_purchase_cost_eur", "active_wearers", "allocated_pieces", "washed_pieces", "customer_washed_kg", "service_requests", "allocated_water_l", "allocated_energy_kwh", "allocated_process_kgco2e", "allocated_delivery_kgco2e", "allocated_textile_waste_kg", "water_saving_vs_local_l", "energy_saving_vs_local_kwh", "emissions_saving_vs_local_kgco2e", "repair_count", "estimated_replacements_postponed", "estimated_avoided_product_kgco2e", "cycle_hours", "recycling_kg", "reuse_kg", "energy_recovery_kg", "incineration_kg", "textile_waste_total_kg", "priority_rank"]);
const text = (v: unknown) => String(v ?? "").trim();
const num = (v: unknown) => Number(v);

export function excelMonth(value: unknown): string | null {
  if (value instanceof Date && Number.isFinite(value.getTime())) return `${value.getUTCFullYear()}-${String(value.getUTCMonth() + 1).padStart(2, "0")}`;
  if (typeof value === "number") {
    const date = XLSX.SSF.parse_date_code(value);
    return date ? `${date.y}-${String(date.m).padStart(2, "0")}` : null;
  }
  const match = text(value).match(/^(\d{4})-(\d{2})(?:$|[-T ])/);
  return match && Number(match[2]) >= 1 && Number(match[2]) <= 12 ? `${match[1]}-${match[2]}` : null;
}

/** Pure local parsing: no fetch, uploads or remote services. */
export function parseWorkbook(buffer: ArrayBuffer, existing: Dataset): ImportPreview {
  const workbook = XLSX.read(buffer, { type: "array", cellDates: true });
  const errors: string[] = [];
  const warnings: string[] = [];
  const tables: Record<string, RecordRow[]> = {};
  const sheets: ImportPreview["sheets"] = [];
  for (const name of required) if (!workbook.Sheets[name]) errors.push(`Missing worksheet: ${name}.`);
  for (const name of workbook.SheetNames) {
    const sheet = workbook.Sheets[name];
    if (!sheet) continue;
    const matrix = XLSX.utils.sheet_to_json<unknown[]>(sheet, { header: 1, defval: "" });
    const columns = (matrix[0] ?? []).map(text);
    const records = XLSX.utils.sheet_to_json<RecordRow>(sheet, { defval: "" });
    tables[name] = records;
    sheets.push({ name, count: records.length, columns, preview: records.slice(0, 25) });
    const fields = schema[name];
    if (!fields) continue;
    if (new Set(columns).size !== columns.length) errors.push(`${name}: duplicate column headings.`);
    for (const field of fields) if (!columns.includes(field)) errors.push(`${name}: missing column ${field}.`);
    records.forEach((record, i) => {
      for (const field of fields) {
        const v = record[field];
        if (text(v) === "" && !["priority_topics", "segment", "hq_country", "country", "city", "dashboard_emphasis"].includes(field)) errors.push(`${name}, row ${i + 2}: ${field} is empty.`);
        else if (numeric.has(field) && (!Number.isFinite(num(v)) || (num(v) < 0 && !field.includes("saving")))) errors.push(`${name}, row ${i + 2}: ${field} must be a valid ${field.includes("saving") ? "number" : "non-negative number"}.`);
      }
      const date = name === "Service_Cycles" ? "pickup_timestamp" : "month";
      if (fields.includes(date)) {
        const month = excelMonth(record[date]);
        if (!month) errors.push(`${name}, row ${i + 2}: invalid ${date}; use an Excel date or YYYY-MM.`);
        else record["month"] = month;
      }
    });
  }
  const get = (name: string) => tables[name] ?? [];
  const unique = (name: string, field: string, key = (r: RecordRow) => text(r[field])) => {
    const seen = new Set<string>();
    get(name).forEach((r, i) => { const id = key(r); if (seen.has(id)) errors.push(`${name}, row ${i + 2}: duplicate ${field} ${text(r[field])}.`); seen.add(id); });
  };
  const siteKey = (customer: string, site: string) => JSON.stringify([customer, site]);
  unique("Customers", "customer_id"); unique("Sites", "site_id", (r) => siteKey(text(r["customer_id"]), text(r["site_id"]))); unique("Products", "product_id");

  // Resolve identities before validating references or aggregating any sheet.
  // Source IDs survive local persistence so later years and repeat imports reuse aliases.
  const identityName = (v: unknown) => text(v).replace(/\s+/g, " ").toLowerCase();
  const customerAliases = new Map<string, string>();
  const customerIdsUsed = new Set([...existing.customers.map((c) => c.customer_id), ...get("Customers").map((r) => text(r["customer_id"]))]);
  const reserve = (candidate: string, used: Set<string>) => {
    let id = candidate;
    let suffix = 2;
    while (used.has(id)) id = `${candidate}::${suffix++}`;
    used.add(id);
    return id;
  };
  for (const r of get("Customers")) {
    const source = text(r["customer_id"]);
    const name = identityName(r["customer_name"]);
    const match = existing.customers.find((c) =>
      (c.customer_id === source || c.source_customer_id === source) && identityName(c.customer_name) === name);
    const collision = existing.customers.some((c) => c.customer_id === source);
    const resolved = match?.customer_id ?? (collision ? reserve(`${encodeURIComponent(source)}::${encodeURIComponent(name)}`, customerIdsUsed) : source);
    customerAliases.set(source, resolved);
    r["source_customer_id"] = source;
    if (resolved !== source) warnings.push(`Company ${text(r["customer_name"])}: reused customer ID ${source} is linked as ${resolved}. Existing company data is kept.`);
  }
  const siteAliases = new Map<string, string>();
  const siteIdsUsed = new Set([...existing.sites.map((s) => s.site_id), ...get("Sites").map((r) => text(r["site_id"]))]);
  const siteOwners = new Map(existing.sites.map((s) => [s.site_id, s.customer_id]));
  for (const r of get("Sites")) {
    const sourceCustomer = text(r["customer_id"]);
    const customer = customerAliases.get(sourceCustomer) ?? sourceCustomer;
    const source = text(r["site_id"]);
    const match = existing.sites.find((s) => s.customer_id === customer && (s.site_id === source || s.source_site_id === source));
    const owner = siteOwners.get(source);
    const resolved = match?.site_id ?? (owner !== undefined && owner !== customer
      ? reserve(`${encodeURIComponent(customer)}::${encodeURIComponent(source)}`, siteIdsUsed) : source);
    siteAliases.set(siteKey(sourceCustomer, source), resolved);
    siteOwners.set(resolved, customer);
    r["source_site_id"] = source;
    if (resolved !== source) warnings.push(`Site ${text(r["site_name"])}: reused site ID ${source} is linked as ${resolved} for this company.`);
  }
  for (const records of Object.values(tables)) for (const r of records) {
    const customer = text(r["customer_id"]);
    const site = text(r["site_id"]);
    if ("site_id" in r && "customer_id" in r) {
      // Allow sheets to reference an already imported site even when Sites only lists new sites.
      const resolvedCustomer = customerAliases.get(customer) ?? customer;
      const existingSite = existing.sites.find((s) => s.customer_id === resolvedCustomer && (s.site_id === site || s.source_site_id === site));
      r["site_id"] = siteAliases.get(siteKey(customer, site)) ?? existingSite?.site_id ?? site;
    }
    if ("customer_id" in r) r["customer_id"] = customerAliases.get(customer) ?? customer;
  }
  const customers = get("Customers").map((r) => ({ customer_id: text(r["customer_id"]), source_customer_id: text(r["source_customer_id"]), customer_name: text(r["customer_name"]), industry: text(r["industry"]), segment: text(r["segment"]), hq_country: text(r["hq_country"]), priority_topics: text(r["priority_topics"]) }));
  const sites = get("Sites").map((r) => ({ site_id: text(r["site_id"]), source_site_id: text(r["source_site_id"]), customer_id: text(r["customer_id"]), site_name: text(r["site_name"]), country: text(r["country"]), city: text(r["city"]), site_type: text(r["site_type"]), primary_laundry_id: text(r["primary_laundry_id"]) }));
  const products = get("Products").map((r) => ({ product_id: text(r["product_id"]), product_name: text(r["product_name"]), product_group: text(r["product_group"]), avg_weight_kg: num(r["avg_weight_kg"]), synthetic_product_footprint_kgco2e: num(r["synthetic_product_footprint_kgco2e"]), synthetic_purchase_cost_eur: num(r["synthetic_purchase_cost_eur"]) }));
  const customerIds = new Set([...existing.customers, ...customers].map((r) => r["customer_id"]));
  const siteMap = new Map([...existing.sites, ...sites].map((r) => [r["site_id"], r]));
  const productIds = new Set([...existing.products, ...products].map((r) => r["product_id"]));
  sites.forEach((s) => { if (!customerIds.has(s.customer_id)) errors.push(`Sites: ${s.site_id} references unknown customer ${s.customer_id}.`); const old = existing.sites.find((v) => v.site_id === s.site_id); if (old && old.customer_id !== s.customer_id) errors.push(`Site ID ${s.site_id} already belongs to another company. Use unique IDs for new companies.`); });
  products.forEach((p) => { const old = existing.products.find((v) => v.product_id === p.product_id); if (old && Object.keys(p).some((k) => old[k as keyof typeof old] !== p[k as keyof typeof p])) warnings.push(`Product ${p.product_id} already exists; existing product details and cost will be kept.`); });
  for (const name of ["Service_Activity", "Customer_Impacts", "Repairs", "Service_Cycles"]) get(name).forEach((r, i) => {
    const site = siteMap.get(text(r["site_id"]));
    if (!site || site.customer_id !== text(r["customer_id"])) errors.push(`${name}, row ${i + 2}: site/customer reference does not match.`);
    if (!productIds.has(text(r["product_id"]))) errors.push(`${name}, row ${i + 2}: unknown product ${text(r["product_id"])}.`);
  });
  const empty = (r: RecordRow): Row => ({ id: 0, month: text(r["month"]), site: text(r["site_id"]), product: text(r["product_id"]), laundry: text(r["laundry_id"]), wearers: 0, allocated: 0, washed: 0, kg: 0, requests: 0, water: 0, energy: 0, co2: 0, deliveryCo2: 0, textileWaste: 0, waterSaved: 0, energySaved: 0, co2Saved: 0, repairs: 0, postponed: 0, avoidedCo2: 0, cycles: 0, cycleHours: 0, onTime: 0 });
  const map = new Map<string, Row>();
  const activityKeys = new Set<string>();
  get("Service_Activity").forEach((r, i) => {
    const row = empty(r); const key = rowKey(row);
    if (activityKeys.has(key)) { errors.push(`Service_Activity, row ${i + 2}: duplicate month/site/product line.`); return; }
    activityKeys.add(key);
    Object.assign(row, { wearers: num(r["active_wearers"]), allocated: num(r["allocated_pieces"]), washed: num(r["washed_pieces"]), kg: num(r["customer_washed_kg"]), requests: num(r["service_requests"]) });
    if (!row.allocated || row.washed / Math.max(row.allocated, 1) / (52 / 12) > 1) warnings.push(`Service_Activity, row ${i + 2}: ${!row.allocated ? "no garments allocated" : "weekly utilisation exceeds 100%"}. Review in Account Pulse.`);
    map.set(key, row);
  });
  const impactKeys = new Set<string>();
  const apply = (name: string, fields: Record<string, keyof Row>) => get(name).forEach((r, i) => {
    const key = rowKey(empty(r)); const row = map.get(key);
    if (!row || row.laundry !== text(r["laundry_id"])) { errors.push(`${name}, row ${i + 2}: no matching service activity line.`); return; }
    if (name === "Customer_Impacts") { if (impactKeys.has(key)) errors.push(`${name}, row ${i + 2}: duplicate impact line.`); impactKeys.add(key); }
    for (const [from, to] of Object.entries(fields)) (row[to] as number) += num(r[from]);
  });
  apply("Customer_Impacts", { allocated_water_l: "water", allocated_energy_kwh: "energy", allocated_process_kgco2e: "co2", allocated_delivery_kgco2e: "deliveryCo2", allocated_textile_waste_kg: "textileWaste", water_saving_vs_local_l: "waterSaved", energy_saving_vs_local_kwh: "energySaved", emissions_saving_vs_local_kgco2e: "co2Saved" });
  apply("Repairs", { repair_count: "repairs", estimated_replacements_postponed: "postponed", estimated_avoided_product_kgco2e: "avoidedCo2" });
  get("Repairs").forEach((r) => { const row = map.get(rowKey(empty(r))); if (!row) return; const type = text(r["repair_type"]); row.repairBreakdown ??= {}; row.repairBreakdown[type] = (row.repairBreakdown[type] ?? 0) + num(r["repair_count"]); });
  for (const key of activityKeys) if (!impactKeys.has(key)) errors.push(`Customer_Impacts: missing impact data for ${key}.`);
  get("Service_Cycles").forEach((r, i) => { const row = map.get(rowKey(empty(r))); if (!row) { errors.push(`Service_Cycles, row ${i + 2}: no matching activity month/site/product.`); return; } row.cycles++; row.cycleHours += num(r["cycle_hours"]); if (text(r["performance_flag"]) === "ON_TIME") row.onTime++; });
  if (!workbook.Sheets["Service_Cycles"]) warnings.push("No Service_Cycles worksheet: on-time service and turnaround slides will be omitted.");
  const wasteMap = new Map<string, Dataset["waste"][number]>();
  get("Waste_Circularity").forEach((r) => { const id = text(r["laundry_id"]); const w = wasteMap.get(id) ?? { laundry_id: id, recycling_kg: 0, reuse_kg: 0, energy_recovery_kg: 0, incineration_kg: 0, textile_waste_total_kg: 0 }; for (const k of ["recycling_kg", "reuse_kg", "energy_recovery_kg", "incineration_kg", "textile_waste_total_kg"] as const) w[k] += num(r[k]); wasteMap.set(id, w); });
  if (!workbook.Sheets["Waste_Circularity"]) warnings.push("No Waste_Circularity worksheet: recycling claims will be omitted for imported rows.");
  const resultRows = [...map.values()].map((r, id) => {
    const w = get("Waste_Circularity").find((w) => text(w["month"]) === r["month"] && text(w["laundry_id"]) === r["laundry"]);
    return { ...r, id, recycledKg: w && num(w["textile_waste_total_kg"]) > 0 ? r.textileWaste * (num(w["recycling_kg"]) + num(w["reuse_kg"])) / num(w["textile_waste_total_kg"]) : undefined };
  });
  if (!resultRows.length) errors.push("Service_Activity contains no data rows.");
  const oldKeys = new Set(existing.rows.map(rowKey));
  return {
    data: { rows: resultRows, customers, sites, products, laundries: get("Laundries").map((r) => ({ laundry_id: text(r["laundry_id"]), laundry_name: text(r["laundry_name"]), country: text(r["country"]) })), repairTypes: [], waste: [...wasteMap.values()], industryPriorities: get("Industry_Priorities").map((r) => ({ industry: text(r["industry"]), priority_rank: num(r["priority_rank"]), priority_theme: text(r["priority_theme"]), dashboard_emphasis: text(r["dashboard_emphasis"]) })) },
    sheets, errors: [...new Set(errors)], warnings: [...new Set(warnings)], years: [...new Set(resultRows.map((r) => r["month"].slice(0, 4)))].sort(), duplicates: resultRows.filter((r) => oldKeys.has(rowKey(r))).length,
  };
}