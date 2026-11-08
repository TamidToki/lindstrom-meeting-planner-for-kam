import type { ReactNode } from "react";
import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

export function Kpi({
  icon,
  label,
  value,
  sub,
  delta,
  goodWhenUp = true,
  provenance,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  sub?: string;
  delta?: number;
  goodWhenUp?: boolean;
  provenance?: "Measured" | "Calculated" | "Estimated";
}) {
  const flat = delta === undefined || Math.abs(delta) < 1;
  const good = !flat && delta !== undefined && (delta > 0) === goodWhenUp;
  return (
    <div className="metric-tile min-w-0 rounded-lg border border-border/60 bg-card p-4 transition-all duration-300 hover:-translate-y-1 hover:border-primary/50 hover:shadow-lg">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-secondary text-secondary-foreground">{icon}</span>
        {provenance && <span className="rounded-full border border-border/60 bg-muted/50 px-1.5 py-1 text-[9px] font-semibold uppercase text-muted-foreground">{provenance}</span>}
      </div>
      <p className="mt-3 min-h-10 text-sm font-medium leading-5 text-muted-foreground">{label}</p>
      <div className="mt-1 break-words font-display text-3xl font-bold tabular-nums">{value}</div>
      <div className="mt-3 flex flex-wrap items-start gap-2 text-xs text-muted-foreground">
        {delta !== undefined && (
          <span
            className={cn(
              "inline-flex shrink-0 items-center gap-0.5 rounded-full px-2 py-1 font-semibold tabular-nums",
              flat ? "bg-muted" : good ? "bg-success/15 text-success" : "bg-destructive/10 text-destructive",
            )}
          >
            {flat ? <Minus className="h-3 w-3" /> : delta > 0 ? <ArrowUpRight className="h-3 w-3" /> : <ArrowDownRight className="h-3 w-3" />}
            {Math.abs(delta).toFixed(0)}%
          </span>
        )}
        <span className="leading-5">{sub}</span>
      </div>
    </div>
  );
}

export function Section({ title, desc, children, action }: { title: string; desc?: string; children: ReactNode; action?: ReactNode }) {
  return (
    <section className="border-t border-border/60 py-5">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 className="text-xl font-bold">{title}</h2>
          {desc && <p className="text-sm text-muted-foreground">{desc}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

export function BandBar({ value, low, high, max = 100 }: { value: number; low: number; high: number; max?: number }) {
  const pct = (v: number) => `${Math.min(100, Math.max(0, (v / max) * 100))}%`;
  return (
    <div className="pt-9">
    <div className="relative h-3 w-full" role="img" aria-label={`Utilisation ${value.toFixed(0)}%. Healthy band ${low} to ${high}%.`}>
      <div className="absolute inset-0 overflow-hidden rounded-full bg-muted">
        <div className="gauge-healthy absolute inset-y-0 border-x-2 border-card" style={{ left: pct(low), width: `calc(${pct(high)} - ${pct(low)})` }} />
        <div className="absolute inset-y-0 border-l-2 border-card bg-warning/35" style={{ left: pct(high), right: 0 }} />
      </div>
      <TooltipProvider delayDuration={150}>
        <Tooltip><TooltipTrigger asChild>
          <Button variant="ghost" size="sm" aria-label={`Utilisation ${value.toFixed(0)}%`} className="absolute -top-9 h-7 -translate-x-1/2 rounded-md bg-primary px-2 text-xs font-bold tabular-nums text-primary-foreground hover:bg-primary hover:text-primary-foreground" style={{ left: `${Math.min(94, Math.max(6, (value / max) * 100))}%` }}>
            {value.toFixed(0)}%
          </Button>
        </TooltipTrigger><TooltipContent>Weekly washes ÷ allocated garments. Target {low}–{high}%.</TooltipContent></Tooltip>
      </TooltipProvider>
      <span className="absolute -top-1 h-5 w-0.5 -translate-x-1/2 bg-primary" style={{ left: pct(value) }} />
    </div>
    <div className="mt-3 grid grid-cols-3 gap-2 text-[11px] text-muted-foreground">
      <span>Under-used</span><span className="text-center">Healthy target</span><span className="text-right">Stock tight</span>
    </div>
    </div>
  );
}
