import { createFileRoute, Link } from "@tanstack/react-router";
import { useMemo } from "react";
import { ArrowLeft, ArrowRight, Check, Coins, Droplets, Factory, Leaf, Recycle, ShieldCheck, Sparkles, Wallet, Users } from "lucide-react";
import { ATTENDEES, PRIORITIES, useKam, type Attendee, type Priority } from "@/lib/kam/store";
import { customerRows } from "@/lib/kam/metrics";
import { buildDeck } from "@/lib/kam/story";
import { industryPriorities } from "@/lib/kam/data";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/meeting")({
  head: () => ({
    meta: [
      { title: "Meeting Customizer — Predictable KAM AI Assistant" },
      { name: "description", content: "Tailor the customer review to who is in the room and what they care about." },
      { property: "og:title", content: "Meeting Customizer — Predictable KAM AI Assistant" },
      { property: "og:description", content: "Pick attendees and priorities to shape the customer review deck." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: Meeting,
});

const ATT_ICON: Record<Attendee, typeof Wallet> = { procurement: Wallet, sustainability: Leaf, operations: Factory };
const PRI_ICON: Record<Priority, typeof Coins> = { cost: Coins, co2: Leaf, water: Droplets, recycling: Recycle, hygiene: ShieldCheck };
const TOPIC_MAP: [RegExp, Priority][] = [
  [/cost|allocation/i, "cost"],
  [/scope 3|emission/i, "co2"],
  [/water/i, "water"],
  [/repair|circular/i, "recycling"],
  [/hygiene|compliance/i, "hygiene"],
];

function Meeting() {
  const { customer, attendees, priorities, toggleAttendee, togglePriority, excludedSet, band, data, year } = useKam();
  const suggested = useMemo(() => {
    const text = customer.priority_topics + " " + data.industryPriorities.filter((p) => p.industry === customer.industry).map((p) => p.priority_theme).join(" ");
    return new Set(TOPIC_MAP.filter(([re]) => re.test(text)).map(([, p]) => p));
  }, [customer, data]);
  const deck = useMemo(
    () => buildDeck(customerRows(customer.customer_id, excludedSet, data, year), customer.customer_name, customer.industry, band, attendees, priorities, data),
    [customer, excludedSet, band, attendees, priorities, data, year],
  );

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm font-semibold uppercase tracking-wider text-accent">Step 2 · Meeting Customizer</p>
          <h1 className="text-4xl font-extrabold">Who's in the room with {customer.customer_name}?</h1>
          <p className="text-muted-foreground">Pick attendees and priorities — the deck and talking points adapt instantly.</p>
        </div>
        <div className="flex flex-col items-end gap-2">
          <p className="max-w-md text-right text-sm" aria-live="polite">
            <span className="font-semibold">Selected attendees:</span> {attendees.map((a) => ATTENDEES.find((x) => x.id === a)?.label).join(", ") || "none"}.{" "}
            <span className="font-semibold">Selected priorities:</span> {priorities.map((p) => PRIORITIES.find((x) => x.id === p)?.label).join(", ") || "none"}.
          </p>
          {!attendees.length && <p role="alert" className="text-sm font-medium text-destructive">Choose at least one attendee</p>}
        <div className="flex gap-2">
          <Button variant="outline" asChild>
            <Link to="/">
              <ArrowLeft className="mr-1 h-4 w-4" /> Pulse
            </Link>
          </Button>
          <Button size="lg" asChild disabled={!attendees.length}>
            <Link to="/deck">
              Build the deck <ArrowRight className="ml-1 h-4 w-4" />
            </Link>
          </Button>
        </div>
        </div>
      </div>

      <div>
        <h2 className="mb-3 flex items-center gap-2 text-xl font-bold">
          <Users className="h-5 w-5" /> Attendees
        </h2>
        <div className="grid gap-4 md:grid-cols-3">
          {ATTENDEES.map((a) => {
            const on = attendees.includes(a.id);
            const Icon = ATT_ICON[a.id];
            return (
              <button
                key={a.id}
                onClick={() => toggleAttendee(a.id)}
                aria-pressed={on}
                className={cn(
                  "relative rounded-2xl border-2 bg-card p-5 text-left transition hover:-translate-y-0.5",
                  on ? "border-primary shadow-md" : "border-border opacity-80",
                )}
              >
                {on && (
                  <span className="absolute right-4 top-4 flex items-center gap-1 text-xs font-semibold text-primary">
                    Selected
                    <span className="grid h-6 w-6 place-items-center rounded-full bg-primary text-primary-foreground"><Check className="h-4 w-4" /></span>
                  </span>
                )}
                <span className={cn("grid h-12 w-12 place-items-center rounded-xl", on ? "bg-accent text-accent-foreground" : "bg-muted")}>
                  <Icon className="h-6 w-6" />
                </span>
                <p className="mt-3 font-display text-lg font-bold">{a.label}</p>
                <p className="text-sm text-muted-foreground">{a.hint}</p>
              </button>
            );
          })}
        </div>
      </div>

      <div>
        <h2 className="mb-1 text-xl font-bold">Customer priorities</h2>
        <p className="mb-3 text-sm text-muted-foreground">
          <Sparkles className="mr-1 inline h-4 w-4 text-accent" />
          Marked suggestions come from this account's recorded topics: {customer.priority_topics.split("|").join(", ")}.
        </p>
        <div className="flex flex-wrap gap-3">
          {PRIORITIES.map((p) => {
            const on = priorities.includes(p.id);
            const Icon = PRI_ICON[p.id];
            return (
              <button
                key={p.id}
                onClick={() => togglePriority(p.id)}
                aria-pressed={on}
                className={cn(
                  "flex items-center gap-2 rounded-full border-2 px-4 py-2.5 font-medium transition",
                  on ? "border-primary bg-primary text-primary-foreground" : "bg-card hover:border-primary/40",
                )}
              >
                {on ? <Check className="h-4 w-4" /> : <Icon className="h-4 w-4" />} {p.label}{on && <span className="text-xs font-semibold">Selected</span>}
                {suggested.has(p.id) && <span className={cn("rounded-full px-2 text-xs", on ? "bg-accent text-accent-foreground" : "bg-secondary")}>suggested</span>}
              </button>
            );
          })}
        </div>
      </div>

      <div className="rounded-2xl border bg-card p-5">
        <h2 className="text-xl font-bold">Your deck will cover</h2>
        <ol className="mt-3 grid gap-2 md:grid-cols-2">
          {deck.slides.map((s, i) => (
            <li key={s.id} className="flex items-center gap-3 rounded-xl bg-muted px-3 py-2">
              <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-primary text-sm font-bold text-primary-foreground">{i + 1}</span>
              <span>
                <span className="block text-xs uppercase tracking-wide text-muted-foreground">{s.kicker}</span>
                <span className="font-medium">{s.title}</span>
              </span>
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}
