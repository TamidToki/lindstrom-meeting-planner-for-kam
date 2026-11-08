import type { Dataset } from "./data";
import { periodLabel } from "./period";
import type { Attendee, Priority } from "./context";
import { customerRows, totals, siteStats, outliers, monthlyTrend, groupBy, productGroup, type Band } from "./metrics";

/** Compact, aggregated summary of one account sent to the AI. Never contains raw rows. */
export function buildAiContext(opts: {
  data: Dataset;
  customerId: string;
  customerName: string;
  industry: string;
  year: string;
  excluded: Set<number>;
  band: Band;
  attendees: Attendee[];
  priorities: Priority[];
}) {
  const { data, customerId, year, excluded, band } = opts;
  const rs = customerRows(customerId, excluded, data, year);
  const t = totals(rs, data);
  const r1 = (n: number) => Math.round(n * 10) / 10;
  return {
    account: opts.customerName,
    industry: opts.industry,
    period: year === "all" ? "all available months" : periodLabel(year),
    healthyUtilisationBandPct: band,
    excludedExceptionLines: excluded.size,
    meeting: { attendees: opts.attendees, priorities: opts.priorities },
    totals: {
      wearers: t.wearers,
      garmentsInCirculation: t.inCirculation,
      washes: t.washed,
      utilisationPct: r1(t.utilisation),
      washesPerWearerWeek: r1(t.washesPerWearerWeek),
      repairsPer100Washes: r1(t.repairRate),
      repairs: t.repairs,
      onTimeCyclesPct: r1(t.onTimePct),
      co2Kg: Math.round(t.co2),
      co2SavedKg: Math.round(t.co2Saved),
      waterSavedLitres: Math.round(t.waterSaved),
      energySavedKwh: Math.round(t.energySaved),
      textileWasteKg: Math.round(t.textileWaste),
      recycledOrReusedKg: Math.round(t.recycledKg),
      costAvoidedEur: Math.round(t.costAvoided),
      months: t.monthsCount,
    },
    sites: siteStats(rs, data).map((s) => ({
      name: s.name, type: s.type, city: s.city, utilisationPct: r1(s.utilisation),
      garments: s.inCirculation, repairsPer100Washes: r1(s.repairRate), onTimePct: r1(s.onTimePct), co2SavedKg: Math.round(s.co2Saved),
    })),
    garmentTypes: groupBy(rs, (r) => productGroup(r, data), undefined, data).map((g) => ({
      type: g.label, utilisationPct: r1(g.utilisation), garments: g.inCirculation, repairs: g.repairs,
    })),
    outliers: outliers(rs, band, data).map((o) => ({ site: o.name, severity: o.severity, headline: o.headline, why: o.why })),
    monthlyTrend: monthlyTrend(rs, data).map((m) => ({ month: m.label, utilisationPct: m.utilisation, washes: m.washed, repairs: m.repairs, co2SavedKg: m.co2Saved })),
  };
}

export type AiContext = ReturnType<typeof buildAiContext>;
