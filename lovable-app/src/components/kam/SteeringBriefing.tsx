import { useState } from "react";
import { Gavel, Leaf, PiggyBank, ShieldCheck, Shirt, ChevronDown } from "lucide-react";
import type { Band, Outlier, SiteStat, Totals } from "@/lib/kam/metrics";
import { fmt, fmtK } from "@/lib/kam/metrics";
import { Button } from "@/components/ui/button";

type Q = { icon: React.ReactNode; q: string; answer: string; detail: string; tone: "good" | "watch" | "act" };

export function buildSteeringQuestions(t: Totals, band: Band, sites: SiteStat[], outs: Outlier[]): Q[] {
  const low = sites.filter((s) => s.utilisation < band.low);
  const high = sites.filter((s) => s.utilisation > band.high);
  const inBand = t.utilisation >= band.low && t.utilisation <= band.high;
  const idle = Math.round(low.reduce((n, s) => n + s.inCirculation * (1 - s.utilisation / band.low), 0));
  const worstRepair = [...sites].sort((a, b) => b.repairRate - a.repairRate)[0];
  const recycledPct = t.textileWaste > 0 ? (t.recycledKg / t.textileWaste) * 100 : 0;
  const acts = outs.filter((o) => o.severity === "act");

  const decisions: string[] = [];
  if (low[0]) decisions.push(`right-size garment allocation at ${low.slice(0, 2).map((s) => s.name).join(" & ")}`);
  if (high[0]) decisions.push(`add stock at ${high[0].name} so wearers don't run short`);
  if (recycledPct < 60 && t.textileWaste > 0) decisions.push("commit to a textile recycling target");
  if (!decisions.length) decisions.push("confirm current service levels for the next period");

  return [
    {
      icon: <Shirt className="h-4 w-4" />,
      q: "Are we paying for garments our people actually use?",
      answer: inBand
        ? `${t.utilisation.toFixed(0)}% utilisation. Utilisation is within the configured band. Confirm stock needs with the customer.`
        : `${t.utilisation.toFixed(0)}% utilisation, ${t.utilisation < band.low ? "below" : "above"} the configured ${band.low}–${band.high}% band. Review with the customer.`,
      detail: `${fmt(t.inCirculation)} garments for ${fmt(t.wearers)} wearers. ${low.length} site(s) under-used, ${high.length} running tight.`,
      tone: inBand ? "good" : "watch",
    },
    {
      icon: <PiggyBank className="h-4 w-4" />,
      q: "Where can we save money?",
      answer: idle > 0 ? `~${fmt(idle)} garments (estimate) at sites below the band — review with the customer.` : "Utilisation is within the configured band. Confirm stock needs with the customer.",
      detail: `Renting instead of buying already avoided an estimated €${fmtK(t.costAvoided)}.${low[0] ? ` Biggest opportunity: ${low[0].name}.` : ""}`,
      tone: idle > 0 ? "watch" : "good",
    },
    {
      icon: <ShieldCheck className="h-4 w-4" />,
      q: "Is the service reliable and hygienic?",
      answer: `Indicators to review: ${t.onTimePct.toFixed(0)}% of wash cycles on time; ${t.repairRate.toFixed(2)} repairs per 100 washes.`,
      detail: worstRepair ? `Highest repair rate: ${worstRepair.name} (${worstRepair.repairRate.toFixed(2)}). ${acts.length} issue(s) need action.` : "",
      tone: t.onTimePct >= 95 && acts.length === 0 ? "good" : acts.length ? "act" : "watch",
    },
    {
      icon: <Leaf className="h-4 w-4" />,
      q: "What sustainability results can we report to our board?",
      answer: `Estimated savings: ${fmt(t.co2Saved / 1000, 1)} t CO₂e and ${fmt(t.waterSaved / 1000)} m³ water versus the local laundry baseline.`,
      detail: t.textileWaste > 0 ? `${recycledPct.toFixed(0)}% of textile waste recycled or reused.` : "No textile recycling data in this period.",
      tone: "good",
    },
    {
      icon: <Gavel className="h-4 w-4" />,
      q: "What do we need the committee to decide today?",
      answer: (decisions[0] ?? "").charAt(0).toUpperCase() + (decisions[0] ?? "").slice(1) + ".",
      detail: decisions.length > 1 ? `Also: ${decisions.slice(1).join("; ")}.` : "",
      tone: "act",
    },
  ];
}

const toneCls = { good: "border-l-success", watch: "border-l-warning", act: "border-l-accent" } as const;
const categories = ["Cost & allocation", "Savings opportunity", "Service & hygiene", "Sustainability", "Committee decisions"];

export function SteeringBriefing(props: { t: Totals; band: Band; sites: SiteStat[]; outs: Outlier[] }) {
  const qs = buildSteeringQuestions(props.t, props.band, props.sites, props.outs);
  const [open, setOpen] = useState<number | null>(null);
  return (
    <section className="py-2">
      <h2 className="text-xl font-bold">Steering committee briefing</h2>
      <p className="mb-4 mt-1 text-sm text-muted-foreground">The 5 questions executives ask — answered from this account's data.</p>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
        {qs.map((x, i) => (
          <div key={x.q} className={`self-start overflow-hidden rounded-lg border border-l-4 border-border/60 bg-card shadow-sm ${toneCls[x.tone]}`}>
          <Button variant="ghost"
            key={x.q}
            type="button"
            onClick={() => setOpen(open === i ? null : i)}
            aria-expanded={open === i}
            aria-controls={`briefing-evidence-${i}`}
            className="block h-auto w-full whitespace-normal rounded-none p-4 text-left hover:bg-muted/50 hover:text-foreground"
          >
            <div className="flex items-start gap-2 text-[10px] font-semibold uppercase text-muted-foreground">
              <span className="shrink-0 text-primary">{x.icon}</span><span className="leading-4">Q{i + 1} · {categories[i]}</span>
              <ChevronDown className={`briefing-chevron ml-auto h-3.5 w-3.5 shrink-0 transition-transform duration-200 ${open === i ? "rotate-180" : ""}`} />
            </div>
            <p className="mt-3 text-xs leading-5 text-muted-foreground">{x.q}</p>
            <p className="mt-2 text-sm font-bold leading-6">{x.answer}</p>
          </Button>
          {open === i && x.detail && <p id={`briefing-evidence-${i}`} className="border-t border-border/60 bg-muted/40 px-4 py-3 text-xs leading-5 text-muted-foreground">{x.detail}</p>}
          </div>
        ))}
      </div>
    </section>
  );
}
