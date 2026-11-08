import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useKam } from "@/lib/kam/store";
import { customerRows, fmt, fmtK, groupBy, laundryName, monthlyTrend, productGroup, siteStats, type SiteStat } from "@/lib/kam/metrics";
import { repairTypes, siteById, waste } from "@/lib/kam/data";
import { AskDataChat } from "@/components/kam/AskData";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Section } from "@/components/kam/bits";

export const Route = createFileRoute("/advanced")({
  head: () => ({
    meta: [
      { title: "Advanced Analytics — Predictable KAM AI Assistant" },
      { name: "description", content: "Deep-dive by site, month, garment type, repairs and laundry circularity." },
      { property: "og:title", content: "Advanced Analytics — Predictable KAM AI Assistant" },
      { property: "og:description", content: "Deep-dive analytics for workwear rental accounts." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: Advanced,
});

const tip = { contentStyle: { background: "var(--popover)", borderRadius: 12, border: "1px solid var(--border)" } };
const ax = { fontSize: 11, stroke: "var(--muted-foreground)" };

type Col = { k: keyof SiteStat; label: string; f: (v: number) => string };
const COLS: Col[] = [
  { k: "inCirculation", label: "Garments", f: (v) => fmt(v) },
  { k: "wearers", label: "Wearers", f: (v) => fmt(v) },
  { k: "utilisation", label: "Utilisation %", f: (v) => v.toFixed(1) },
  { k: "washesPerWearerWeek", label: "Washes/wearer/wk", f: (v) => v.toFixed(2) },
  { k: "repairRate", label: "Repairs/100 washes", f: (v) => v.toFixed(2) },
  { k: "onTimePct", label: "On time %", f: (v) => v.toFixed(0) },
  { k: "costAvoided", label: "Cost avoided €", f: (v) => fmtK(v) },
  { k: "co2Saved", label: "CO₂e saved kg", f: (v) => fmtK(v) },
  { k: "waterSaved", label: "Water saved L", f: (v) => fmtK(v) },
];

function Advanced() {
  const { customer, excludedSet, band, data, year } = useKam();
  const rs = useMemo(() => customerRows(customer.customer_id, excludedSet, data, year), [customer, excludedSet, data, year]);
  const [sort, setSort] = useState<{ k: keyof SiteStat; asc: boolean }>({ k: "utilisation", asc: true });
  const sites = siteStats(rs, data).sort((a, b) => ((a[sort.k] as number) - (b[sort.k] as number)) * (sort.asc ? 1 : -1));
  const trend = monthlyTrend(rs, data);
  const groups = groupBy(rs, (r) => productGroup(r, data), undefined, data);
  const repairTypes = data.repairTypes;
  const waste = data.waste;
  const siteById = Object.fromEntries(data.sites.map((s) => [s.site_id, s]));
  const siteIds = new Set(rs.map((r) => r.site));
  const rtype = Object.entries(
    rs.some((r) => r.repairBreakdown) ? rs.reduce<Record<string, number>>((m, r) => { for (const [type, count] of Object.entries(r.repairBreakdown ?? {})) m[type] = (m[type] ?? 0) + count; return m; }, {}) : repairTypes.filter(([s]) => siteIds.has(s) && siteById[s]?.customer_id === customer.customer_id).reduce<Record<string, number>>((m, [, t, n]) => ((m[t] = (m[t] ?? 0) + n), m), {}),
  )
    .map(([t, n]) => ({ t, n }))
    .sort((a, b) => b.n - a.n);
  const laundries = new Set(rs.map((r) => r.laundry));
  const wasteData = waste
    .filter((w) => laundries.has(w.laundry_id))
    .map((w) => ({ n: laundryName(w.laundry_id), Recycling: w.recycling_kg, Reuse: w.reuse_kg, "Energy recovery": w.energy_recovery_kg, Incineration: w.incineration_kg }));

  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm font-semibold uppercase tracking-wider text-accent">Advanced mode</p>
        <h1 className="text-4xl font-extrabold">{customer.customer_name} — deep dive</h1>
        <p className="text-muted-foreground">Same data and exclusions as the meeting steps. Healthy band {band.low}–{band.high}%.</p>
      </div>
      <Tabs defaultValue="sites">
        <TabsList>
          <TabsTrigger value="sites">Sites</TabsTrigger>
          <TabsTrigger value="trend">Monthly trend</TabsTrigger>
          <TabsTrigger value="products">Garment types</TabsTrigger>
          <TabsTrigger value="repairs">Repairs</TabsTrigger>
          <TabsTrigger value="circular">Circularity</TabsTrigger>
          <TabsTrigger value="ask">Ask the data</TabsTrigger>
        </TabsList>

        <TabsContent value="ask">
          <AskDataChat className="h-[70vh]" />
        </TabsContent>

        <TabsContent value="sites">
          <Section title="All sites" desc="Click a column to sort.">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-muted-foreground">
                    <th className="py-2 pr-3">Site</th>
                    <th className="pr-3">Type</th>
                    {COLS.map((c) => (
                      <th key={c.k} className="cursor-pointer pr-3 text-right hover:text-foreground" onClick={() => setSort({ k: c.k, asc: sort.k === c.k ? !sort.asc : false })}>
                        {c.label}
                        {sort.k === c.k ? (sort.asc ? " ↑" : " ↓") : ""}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {sites.map((s) => {
                    const out = s.utilisation < band.low || s.utilisation > band.high;
                    return (
                      <tr key={s.siteId} className="border-t">
                        <td className="py-2 pr-3 font-medium">{s.name}</td>
                        <td className="pr-3 text-muted-foreground">{s.type}</td>
                        {COLS.map((c) => (
                          <td key={c.k} className={`pr-3 text-right tabular-nums ${c.k === "utilisation" && out ? "font-bold text-accent" : ""}`}>
                            {c.f(s[c.k] as number)}
                          </td>
                        ))}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Section>
        </TabsContent>

        <TabsContent value="trend">
          <div className="grid gap-6 lg:grid-cols-2">
            <Section title="Utilisation %">
              <div className="h-72">
                <ResponsiveContainer>
                  <LineChart data={trend}>
                    <CartesianGrid stroke="var(--border)" />
                    <XAxis dataKey="label" {...ax} />
                    <YAxis {...ax} />
                    <Tooltip {...tip} />
                    <Line dataKey="utilisation" stroke="var(--chart-1)" strokeWidth={3} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </Section>
            <Section title="Washes & repairs">
              <div className="h-72">
                <ResponsiveContainer>
                  <LineChart data={trend}>
                    <CartesianGrid stroke="var(--border)" />
                    <XAxis dataKey="label" {...ax} />
                    <YAxis yAxisId="a" {...ax} />
                    <YAxis yAxisId="b" orientation="right" {...ax} />
                    <Tooltip {...tip} />
                    <Legend />
                    <Line yAxisId="a" dataKey="washed" name="Washes" stroke="var(--chart-1)" strokeWidth={2} />
                    <Line yAxisId="b" dataKey="repairs" name="Repairs" stroke="var(--chart-2)" strokeWidth={2} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </Section>
            <Section title="CO₂e saved (kg) & water saved (m³)">
              <div className="h-72">
                <ResponsiveContainer>
                  <BarChart data={trend}>
                    <CartesianGrid stroke="var(--border)" />
                    <XAxis dataKey="label" {...ax} />
                    <YAxis {...ax} />
                    <Tooltip {...tip} />
                    <Legend />
                    <Bar dataKey="co2Saved" name="CO₂e kg" fill="var(--chart-3)" />
                    <Bar dataKey="waterSaved" name="Water m³" fill="var(--chart-4)" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Section>
          </div>
        </TabsContent>

        <TabsContent value="products">
          <Section title="By garment type">
            <div className="h-80">
              <ResponsiveContainer>
                <BarChart data={groups.map((g) => ({ n: g.label, Utilisation: +g.utilisation.toFixed(1), "Repairs/100": +(g.repairRate * 10).toFixed(1) }))}>
                  <CartesianGrid stroke="var(--border)" />
                  <XAxis dataKey="n" {...ax} />
                  <YAxis {...ax} />
                  <Tooltip {...tip} />
                  <Legend />
                  <Bar dataKey="Utilisation" fill="var(--chart-1)" />
                  <Bar dataKey="Repairs/100" name="Repairs per 1000 washes" fill="var(--chart-2)" />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <table className="mt-4 w-full text-sm">
              <thead className="text-left text-muted-foreground">
                <tr>
                  <th className="py-1">Group</th>
                  <th className="text-right">Garments (latest)</th>
                  <th className="text-right">Washes</th>
                  <th className="text-right">Repairs</th>
                  <th className="text-right">Cost avoided €</th>
                </tr>
              </thead>
              <tbody>
                {groups.map((g) => (
                  <tr key={g.key} className="border-t">
                    <td className="py-1">{g.label}</td>
                    <td className="text-right">{fmt(g.inCirculation)}</td>
                    <td className="text-right">{fmt(g.washed)}</td>
                    <td className="text-right">{fmt(g.repairs)}</td>
                    <td className="text-right">{fmtK(g.costAvoided)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Section>
        </TabsContent>

        <TabsContent value="repairs">
          <Section title="Repairs by type" desc="All months, sites of this account.">
            <div className="h-80">
              <ResponsiveContainer>
                <BarChart data={rtype} layout="vertical" margin={{ left: 80 }}>
                  <XAxis type="number" {...ax} />
                  <YAxis type="category" dataKey="t" {...ax} width={140} />
                  <Tooltip {...tip} />
                  <Bar dataKey="n" name="Repairs" fill="var(--chart-2)" radius={[0, 6, 6, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Section>
        </TabsContent>

        <TabsContent value="circular">
          <Section title="End-of-life textile routes by laundry (kg, laundry total)" desc="Customer share is allocated by washed kg.">
            <div className="h-80">
              <ResponsiveContainer>
                <BarChart data={wasteData}>
                  <CartesianGrid stroke="var(--border)" />
                  <XAxis dataKey="n" {...ax} />
                  <YAxis {...ax} />
                  <Tooltip {...tip} />
                  <Legend />
                  <Bar dataKey="Recycling" stackId="a" fill="var(--chart-3)" />
                  <Bar dataKey="Reuse" stackId="a" fill="var(--chart-1)" />
                  <Bar dataKey="Energy recovery" stackId="a" fill="var(--chart-2)" />
                  <Bar dataKey="Incineration" stackId="a" fill="var(--chart-5)" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Section>
        </TabsContent>
      </Tabs>
    </div>
  );
}
