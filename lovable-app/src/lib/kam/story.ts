import { sampleDataset, type Dataset, type Row } from "./data";
import { fmt, fmtK, outliers, siteStats, totals, type Band } from "./metrics";
import type { Attendee, Priority } from "./store";

export type Slide = {
  id: string;
  title: string;
  kicker: string;
  big: { value: string; label: string }[];
  bullets: string[];
  talking: Partial<Record<Attendee, string[]>>;
  tags: (Priority | Attendee)[];
  chart?: "trend" | "sites" | "impact" | "circular";
};

export function buildDeck(
  rs: Row[],
  customerName: string,
  industry: string,
  band: Band,
  attendees: Attendee[],
  priorities: Priority[],
  data: Dataset = sampleDataset,
) {
  const t = totals(rs, data);
  const sites = siteStats(rs, data);
  const out = outliers(rs, band, data);
  const low = sites.filter((s) => s.utilisation < band.low);
  const high = sites.filter((s) => s.utilisation > band.high);
  const releasable = low.reduce((n, s) => n + Math.round(s.inCirculation * (1 - s.utilisation / band.low)), 0);
  const recyclePct = t.textileWaste ? (t.recycledKg / t.textileWaste) * 100 : 0;
  const period = [...new Set(rs.map((r) => r.month.slice(0, 4)))].sort().join(", ");
  const hasCycles = t.cycles > 0;
  const hasRecycling = rs.some((r) => r.recycledKg !== undefined || r.id < sampleDataset.rows.length);
  const hygiene = ["Food & Beverage", "Healthcare"].includes(industry);

  const slides: Slide[] = [
    {
      id: "overview",
      title: `${customerName} — your ${period} workwear service at a glance`,
      kicker: "Account overview",
      big: [
        { value: fmt(t.inCirculation), label: "garments in circulation" },
        { value: fmt(t.wearers), label: "active wearers (latest month)" },
        { value: String(sites.length), label: "sites served" },
      ],
      bullets: [
        `${fmtK(t.washed)} garment washes over ${t.monthsCount} months`,
        `${t.washesPerWearerWeek.toFixed(1)} washes per wearer per week`,
        hasCycles ? `${t.onTimePct.toFixed(0)}% of laundry cycles delivered on time` : "Service timing data not supplied",
      ],
      talking: {
        procurement: [`Scale: ${fmt(t.inCirculation)} garments supporting ${fmt(t.wearers)} wearers across ${sites.length} sites.`],
        sustainability: ["Every wash happens in an industrial laundry with measured water and energy use — the basis for today's impact numbers."],
        operations: hasCycles ? [`${t.onTimePct.toFixed(0)}% on-time cycles — ask which sites feel this least.`] : [],
      },
      tags: ["procurement", "sustainability", "operations"],
      chart: "trend",
    },
    {
      id: "utilisation",
      title: `Garment utilisation: ${t.utilisation.toFixed(0)}% washed each week`,
      kicker: "Right-sizing",
      big: [
        { value: `${t.utilisation.toFixed(0)}%`, label: `utilisation (healthy ${band.low}–${band.high}%)` },
        { value: String(low.length), label: "sites under-using garments" },
        { value: String(high.length), label: "sites with tight stock" },
      ],
      bullets: [
        low.length
          ? `${low.map((s) => s.name).slice(0, 3).join(", ")} sit below the configured band — about ${fmt(releasable)} pieces to review with the customer (indicator, not proof of idle stock)`
          : "Utilisation is within the configured band. Confirm stock needs with the customer.",
        high.length ? `${high.map((s) => s.name).slice(0, 3).join(", ")} may need extra pieces to protect availability` : "No site is running short of garments",
      ],
      talking: {
        procurement: [
          low.length ? `${low.length} sites sit below the configured band (~${fmt(releasable)} garments, estimate). Review allocation with the customer before changing the contract.` : "Utilisation is within the configured band. Confirm stock needs with the customer.",
        ],
        operations: [
          high.length ? `${high[0]?.name} washes garments very often — are wearers ever short?` : "Ask whether lockers feel over-stocked at any site.",
        ],
      },
      tags: ["cost", "hygiene", "procurement", "operations"],
      chart: "sites",
    },
    {
      id: "repairs",
      title: `Repairs kept ${fmt(t.postponed)} garments in use`,
      kicker: "Repair & lifetime",
      big: [
        { value: fmt(t.repairs), label: "repairs completed" },
        { value: `€${fmtK(t.costAvoided)}`, label: "replacement cost avoided (est.)" },
        { value: `${t.repairRate.toFixed(2)}`, label: "repairs per 100 washes" },
      ],
      bullets: [
        "Each repair postpones one new garment purchase (prototype assumption; low case 50%)",
        `${fmtK(t.avoidedCo2)} kg CO₂e of new-garment production avoided`,
      ],
      talking: {
        procurement: [`Repairs avoided an estimated €${fmtK(t.costAvoided)} in replacement garments (low case €${fmtK(t.costAvoided / 2)}).`],
        sustainability: [`Repair is circularity in practice: ${fmtK(t.avoidedCo2)} kg CO₂e of production avoided.`],
        operations: ["Which sites see the most damage? Fit or product choice may reduce repairs further."],
      },
      tags: ["cost", "recycling", "co2", "procurement", "sustainability"],
    },
    {
      id: "climate",
      title: `${fmt(t.co2Saved / 1000, 1)} t CO₂e saved vs local laundry`,
      kicker: "Climate impact",
      big: [
        { value: `${fmt(t.co2Saved / 1000, 1)} t`, label: "CO₂e saved vs local laundry" },
        { value: `${fmtK(t.energySaved)} kWh`, label: "energy saved" },
        { value: `${fmt(t.co2 / 1000, 1)} t`, label: "service footprint (allocated)" },
      ],
      bullets: [
        "Compared with an outsourced local laundry (default baseline)",
        "Range: ±20% baseline sensitivity — allocated estimate, not an audited claim",
      ],
      talking: {
        sustainability: [`${fmt(t.co2Saved / 1000, 1)} t CO₂e saved can support Scope 3 reporting (allocated estimate).`],
        procurement: ["Lower emissions come at no extra cost — part of the service value."],
      },
      tags: ["co2", "sustainability"],
      chart: "impact",
    },
    {
      id: "water",
      title: `${fmt(t.waterSaved / 1000)} m³ of water saved`,
      kicker: "Water",
      big: [
        { value: `${fmt(t.waterSaved / 1000)} m³`, label: "fresh water saved vs local laundry" },
        { value: `${t.kg ? (t.water / t.kg).toFixed(1) : "–"} L/kg`, label: "water per kg washed" },
      ],
      bullets: [
        `Equal to about ${fmt(t.waterSaved / 1000 / 2500, 1)} Olympic swimming pools`,
        "Compared with an outsourced local laundry (allocated estimate)",
      ],
      talking: {
        sustainability: ["Industrial washing reuses process water — a measurable water-stewardship result."],
        operations: [`${hygiene ? "High wash frequency is needed for hygiene; efficient washing keeps that sustainable." : "Water savings grow with every wash we do instead of local laundry."}`],
      },
      tags: ["water", "sustainability"],
      chart: "trend",
    },
    {
      id: "circular",
      title: `${recyclePct.toFixed(0)}% of end-of-life textiles recycled or reused`,
      kicker: "Textile recycling",
      big: [
        { value: `${fmt(t.recycledKg)} kg`, label: "textiles recycled / reused" },
        { value: `${fmt(t.textileWaste)} kg`, label: "end-of-life textiles (allocated)" },
      ],
      bullets: [
        "Laundry-level waste routes allocated by your share of washed kg",
        "Baseline assumes 100% mixed-waste treatment without the service",
      ],
      talking: {
        sustainability: [`${recyclePct.toFixed(0)}% of retired garments go to recycling or reuse instead of incineration.`],
        procurement: ["No disposal cost or effort on your side — included in the service."],
      },
      tags: ["recycling", "sustainability"],
      chart: "circular",
    },
    {
      id: "hygiene",
      title: "Hygiene & service continuity",
      kicker: "Hygiene standards",
      big: [
        { value: `${t.onTimePct.toFixed(0)}%`, label: "cycles on time" },
        { value: `${(t.cycleHours / Math.max(t.cycles, 1)).toFixed(0)} h`, label: "average laundry cycle" },
        { value: `${t.washesPerWearerWeek.toFixed(1)}`, label: "washes per wearer / week" },
      ],
      bullets: [
        hygiene ? "Industrial process washing supports food/healthcare hygiene requirements" : "Controlled industrial washing keeps garments safe and compliant",
        `${fmt(t.requests)} service requests logged in this period`,
      ],
      talking: {
        operations: [`Average cycle ${(t.cycleHours / Math.max(t.cycles, 1)).toFixed(0)} h — is that fast enough for shift patterns?`],
        sustainability: ["Traceable garment flow supports audit-ready hygiene evidence."],
      },
      tags: ["hygiene", "operations"],
    },
    {
      id: "actions",
      title: "Proposed next steps",
      kicker: "Agree together",
      big: [],
      bullets: [
        ...out.slice(0, 3).map((o) => o.headline),
        priorities.includes("cost") ? "Joint right-sizing review of garment allocation" : "",
        priorities.includes("co2") || priorities.includes("water") ? "Annual impact report for sustainability reporting" : "",
        priorities.includes("recycling") ? "Pilot: take-back of customer-owned garments for recycling" : "",
      ].filter(Boolean),
      talking: {
        procurement: ["Agree an owner and date for the right-sizing review."],
        sustainability: ["Agree what impact evidence they need, and when."],
        operations: ["Agree which site to start with."],
      },
      tags: ["procurement", "sustainability", "operations"],
    },
  ];

  const score = (s: Slide) =>
    s.id === "overview" ? 100 : s.id === "actions" ? -100 : s.tags.filter((x) => priorities.includes(x as Priority)).length * 3 + s.tags.filter((x) => attendees.includes(x as Attendee)).length;
  const ordered = [...slides]
    .filter((s) => (s.id !== "hygiene" || hasCycles) && (s.id !== "circular" || hasRecycling))
    .filter((s) => s.id === "overview" || s.id === "actions" || score(s) > 0)
    .sort((a, b) => score(b) - score(a));

  const summary = [
    `In ${period} we served ${fmt(t.wearers)} wearers at ${sites.length} ${customerName} sites with ${fmt(t.inCirculation)} garments in circulation.`,
    priorities.includes("cost") || attendees.includes("procurement")
      ? `Repairs avoided an estimated €${fmtK(t.costAvoided)} in replacement purchases${low.length ? `, and ${low.length} sites below the configured band (~${fmt(releasable)} garments, estimate) are worth reviewing` : ""}.`
      : "",
    priorities.includes("co2") || attendees.includes("sustainability")
      ? `Compared with local laundry, the service saved ${fmt(t.co2Saved / 1000, 1)} t CO₂e and ${fmt(t.waterSaved / 1000)} m³ of water.`
      : "",
    priorities.includes("recycling") && hasRecycling ? `${recyclePct.toFixed(0)}% of end-of-life textiles were recycled or reused.` : "",
    `Utilisation is ${t.utilisation.toFixed(0)}% (configured band ${band.low}–${band.high}%)${t.utilisation >= band.low && t.utilisation <= band.high ? " — within the configured band; confirm stock needs with the customer" : ""}. ${hasCycles ? `Service indicator to review: ${t.onTimePct.toFixed(0)}% of cycles on time.` : "Service timing data was not supplied."}`,
  ]
    .filter(Boolean)
    .join(" ");

  return { slides: ordered, summary, totals: t };
}
