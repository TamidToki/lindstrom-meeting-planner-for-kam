import { createFileRoute, Link } from "@tanstack/react-router";
import { useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { ArrowLeft, ChevronLeft, ChevronRight, ClipboardCopy, Download, Eye, EyeOff, FileSpreadsheet, MessageSquareQuote, Printer } from "lucide-react";
import { ATTENDEES, useKam } from "@/lib/kam/store";
import { customerRows } from "@/lib/kam/metrics";
import { sampleDataset } from "@/lib/kam/data";
import { buildDeck } from "@/lib/kam/story";
import { exportPptx } from "@/lib/kam/exportPptx";
import { captureDeckCharts, readyDeckCharts } from "@/lib/kam/captureCharts";
import { copilotPrompt, exportCopilotWorkbook } from "@/lib/kam/exportCopilot";
import { getChatSession, sessionTranscript } from "@/lib/kam/chatSession";
import { SlideView } from "@/components/kam/SlideView";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/deck")({
  head: () => ({
    meta: [
      { title: "Client Deck & Talking Points — Predictable KAM AI Assistant" },
      { name: "description", content: "Client-ready slides, executive summary and talking points matched to meeting attendees." },
      { property: "og:title", content: "Client Deck & Talking Points — Predictable KAM AI Assistant" },
      { property: "og:description", content: "Preview, tailor and export the customer review deck." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: Deck,
});

function Deck() {
  const { customer, attendees, priorities, excludedSet, band, hiddenSlides, toggleSlide, data, year } = useKam();
  const rows = useMemo(() => customerRows(customer.customer_id, excludedSet, data, year), [customer, excludedSet, data, year]);
  const deck = useMemo(
    () => buildDeck(rows, customer.customer_name, customer.industry, band, attendees, priorities, data),
    [rows, customer, band, attendees, priorities, data],
  );
  const visible = deck.slides.filter((s) => !hiddenSlides.includes(s.id));
  const isSample = useMemo(() => sampleDataset.customers.some((c) => c.customer_id === customer.customer_id), [customer]);
  const [cur, setCur] = useState(0);
  const idx = Math.min(cur, Math.max(visible.length - 1, 0));
  const slide = visible[idx];
  const [busy, setBusy] = useState(false);
  const exportDeck = useRef<HTMLDivElement>(null);

  const notesText = () =>
    [
      `${customer.customer_name} — executive summary`,
      deck.summary,
      "",
      ...visible.flatMap((s, i) => [
        `${i + 1}. ${s.title}`,
        ...attendees.flatMap((a) => (s.talking[a] ?? []).map((t) => `  • [${ATTENDEES.find((x) => x.id === a)?.label}] ${t}`)),
        "",
      ]),
    ].join("\n");

  return (
    <div className="space-y-6">
      <div className="no-print flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm font-semibold uppercase tracking-wider text-accent">Step 3 · Draft deck for review</p>
          <h1 className="text-4xl font-extrabold">{customer.customer_name} review</h1>
          <p className="text-sm font-medium text-warning">Review the figures, assumptions and wording before customer use.</p>
          <p className="text-muted-foreground">
            For {attendees.map((a) => ATTENDEES.find((x) => x.id === a)?.label).join(", ") || "no attendees selected"}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" asChild>
            <Link to="/meeting">
              <ArrowLeft className="mr-1 h-4 w-4" /> Customize
            </Link>
          </Button>
          <Button
            variant="outline"
            onClick={() => {
              navigator.clipboard.writeText(notesText());
              toast.success("Summary and talking points copied");
            }}
          >
            <ClipboardCopy className="mr-1 h-4 w-4" /> Copy notes
          </Button>
          <Button variant="outline" disabled={busy || !visible.length} onClick={async () => {
            if (!exportDeck.current) return;
            setBusy(true);
            try {
              await readyDeckCharts(exportDeck.current, visible);
              window.print();
            } catch {
              toast.error("Could not prepare the graphs. Please try again.");
            } finally {
              setBusy(false);
            }
          }}>
            <Printer className="mr-1 h-4 w-4" /> Print / PDF
          </Button>
          <Button
            disabled={busy || !visible.length}
            onClick={async () => {
              setBusy(true);
              try {
                if (!exportDeck.current) throw new Error("Slides are not ready");
                const chartImages = await captureDeckCharts(exportDeck.current, visible);
                const msgs = getChatSession().messages;
                await exportPptx(customer.customer_name, deck.summary, visible, attendees, msgs.length ? sessionTranscript(msgs, customer.customer_name) : undefined, isSample, chartImages);
                toast.success("PowerPoint downloaded");
              } catch {
                toast.error("Could not create the PowerPoint");
              } finally {
                setBusy(false);
              }
            }}
          >
            <Download className="mr-1 h-4 w-4" /> {busy ? "Preparing…" : "PowerPoint DRAFT"}
          </Button>
          <Button
            variant="outline"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await exportCopilotWorkbook(customer.customer_name, customer.industry, rows, band, data);
                toast.success("Copilot Excel downloaded");
              } catch {
                toast.error("Could not create the Copilot Excel");
              } finally {
                setBusy(false);
              }
            }}
          >
            <FileSpreadsheet className="mr-1 h-4 w-4" /> Copilot Excel
          </Button>
          <Button
            variant="outline"
            onClick={() => {
              navigator.clipboard.writeText(copilotPrompt(customer.customer_name, customer.industry, band));
              toast.success("Copilot prompt copied");
            }}
          >
            <ClipboardCopy className="mr-1 h-4 w-4" /> Copy Copilot prompt
          </Button>
        </div>
      </div>

      <section className="no-print rounded-2xl border-l-4 border-accent bg-card p-5 shadow-sm">
        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Executive summary</p>
        <p className="mt-2 text-lg leading-relaxed">{deck.summary}</p>
      </section>

      <div className="no-print grid gap-6 lg:grid-cols-[200px_1fr_340px]">
        <div className="flex gap-2 overflow-x-auto lg:flex-col">
          {deck.slides.map((s) => {
            const hidden = hiddenSlides.includes(s.id);
            const vi = visible.indexOf(s);
            return (
              <div
                key={s.id}
                className={cn(
                  "flex min-w-[180px] items-center gap-2 rounded-xl border bg-card p-2 text-left text-sm",
                  vi === idx && !hidden && "border-primary ring-2 ring-primary/20",
                  hidden && "opacity-50",
                )}
              >
                <button className="flex-1 text-left" disabled={hidden} onClick={() => setCur(vi)}>
                  <span className="block text-xs text-muted-foreground">{s.kicker}</span>
                  <span className="line-clamp-2 font-medium">{s.title}</span>
                </button>
                <button onClick={() => toggleSlide(s.id)} aria-label={hidden ? "Show slide" : "Hide slide"} className="text-muted-foreground hover:text-foreground">
                  {hidden ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            );
          })}
        </div>

        <div>
          {slide ? (
            <>
              <SlideView slide={slide} index={idx} rows={rows} data={data} band={band} customerName={customer.customer_name} isSample={isSample} />
              <div className="mt-3 flex items-center justify-center gap-4">
                <Button variant="outline" size="icon" onClick={() => setCur(Math.max(0, idx - 1))} disabled={idx === 0} aria-label="Previous slide">
                  <ChevronLeft className="h-4 w-4" />
                </Button>
                <span className="text-sm text-muted-foreground">
                  {idx + 1} / {visible.length}
                </span>
                <Button variant="outline" size="icon" onClick={() => setCur(Math.min(visible.length - 1, idx + 1))} disabled={idx >= visible.length - 1} aria-label="Next slide">
                  <ChevronRight className="h-4 w-4" />
                </Button>
              </div>
            </>
          ) : (
            <p className="text-muted-foreground">All slides are hidden.</p>
          )}
        </div>

        <aside className="rounded-2xl border bg-card p-4">
          <h2 className="flex items-center gap-2 text-lg font-bold">
            <MessageSquareQuote className="h-5 w-5 text-accent" /> Talking points
          </h2>
          {slide &&
            attendees.map((a) => {
              const pts = slide.talking[a];
              if (!pts?.length) return null;
              return (
                <div key={a} className="mt-4">
                  <p className="text-xs font-semibold uppercase tracking-wider text-primary">{ATTENDEES.find((x) => x.id === a)?.label}</p>
                  <ul className="mt-1 space-y-2 text-sm">
                    {pts.map((p) => (
                      <li key={p} className="flex gap-2">
                        <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />
                        {p}
                      </li>
                    ))}
                  </ul>
                </div>
              );
            })}
          {slide && !attendees.some((a) => slide.talking[a]?.length) && (
            <p className="mt-3 text-sm text-muted-foreground">No specific points for the selected attendees on this slide.</p>
          )}
        </aside>
      </div>

      <div ref={exportDeck} className="export-deck" aria-hidden="true">
        {visible.map((s, i) => (
          <SlideView key={s.id} slide={s} index={i} rows={rows} data={data} band={band} customerName={customer.customer_name} isSample={isSample} staticChart />
        ))}
      </div>
    </div>
  );
}
