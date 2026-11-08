import { Link, useLocation, useNavigate } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { Activity, BarChart3, Presentation, Users, Shirt } from "lucide-react";
import { ContextBar } from "./ContextBar";
import { AskDataButton } from "./AskData";
import { cn } from "@/lib/utils";
import { useKam } from "@/lib/kam/store";
import { Building2, FileSpreadsheet } from "lucide-react";
import { periodLabel } from "@/lib/kam/period";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { ExcelImport } from "./ExcelImport";

function BlankStart({ onSample }: { onSample: () => void }) {
  return (
    <div className="mx-auto max-w-xl py-16 text-center">
      <FileSpreadsheet className="mx-auto mb-4 h-12 w-12 text-primary" />
      <h1 className="font-display text-2xl font-bold sm:text-3xl">Upload your Excel workbook to see the account story</h1>
      <p className="mt-2 text-muted-foreground">Your file stays on this device.</p>
      <div className="mt-6 flex flex-wrap justify-center gap-3">
        <ExcelImport />
        <Button size="lg" onClick={onSample}>Try with sample data</Button>
      </div>
    </div>
  );
}

const STEPS = [
  { to: "/" as const, n: 1, label: "Account Pulse", icon: Activity },
  { to: "/meeting" as const, n: 2, label: "Meeting Customizer", icon: Users },
  { to: "/deck" as const, n: 3, label: "Deck & Talking Points", icon: Presentation },
];

export function AppShell({ children }: { children: ReactNode }) {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const advanced = pathname.startsWith("/advanced");
  const { data, dataReady, customer, year, started, startSample } = useKam();

  return (
    <div className="min-h-screen">
      <header className="no-print relative z-30 md:sticky md:top-0 border-b border-border/40 bg-background/80 backdrop-blur-md">
        <div className="mx-auto flex max-w-7xl items-center gap-3 px-4 py-2 sm:py-3">
          <Link to="/" className="flex items-center gap-2">
            <span className="brand-badge grid h-10 w-10 place-items-center rounded-lg shadow-sm">
              <Shirt className="h-5 w-5" />
            </span>
            <span className="leading-none">
              <span className="block font-display text-lg font-extrabold text-foreground">Predictable</span>
              <span className="mt-1 block text-[10px] font-semibold uppercase text-muted-foreground">KAM AI Assistant</span>
            </span>
          </Link>

          <div className="ml-auto flex shrink-0 items-center gap-3">
            {started && (
              <label className="flex items-center gap-2 rounded-full border bg-card px-3 py-1.5 text-sm font-medium">
                <BarChart3 className="h-3.5 w-3.5 text-muted-foreground" /> Advanced
                <Switch checked={advanced} onCheckedChange={(on) => navigate({ to: on ? "/advanced" : "/" })} aria-label="Advanced" />
              </label>
            )}
          </div>
        </div>

        {started && !advanced && (
          <nav className="mx-auto flex max-w-7xl gap-1 overflow-x-auto px-4 pb-2 pt-1 sm:pb-4" aria-label="Meeting steps">
            {STEPS.map((s, i) => {
              const active = pathname === s.to;
              const Icon = s.icon;
              return (
                <div key={s.to} className="flex items-center gap-2">
                  <Button asChild variant="ghost" className={cn("step-link group h-10 rounded-full border px-3 text-xs sm:px-4 sm:text-sm", active ? "step-current border-primary/30 bg-secondary text-primary hover:bg-secondary" : "border-transparent text-muted-foreground hover:bg-muted hover:text-foreground")}>
                  <Link
                    to={s.to}
                    aria-current={active ? "step" : undefined}
                  >
                    <span className={cn("grid h-6 w-6 shrink-0 place-items-center rounded-full text-xs font-bold", active ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground")}>
                      {s.n}
                    </span>
                    <Icon className="h-4 w-4 transition-transform duration-200 group-hover:-translate-y-0.5" />
                    {s.label}
                  </Link>
                  </Button>
                  {i < STEPS.length - 1 && <span className={cn("h-px w-4 shrink-0 sm:w-8", STEPS.findIndex((step) => step.to === pathname) > i ? "bg-primary/50" : "bg-border")} />}
                </div>
              );
            })}
          </nav>
        )}
        {started && <ContextBar />}
      </header>
      {started && data.customers.length > 0 && (
        <div className="no-print sticky top-0 z-30 flex items-center gap-2 border-b border-border/40 bg-background/90 px-4 py-2 text-sm backdrop-blur-md md:hidden">
          <Building2 className="h-4 w-4 shrink-0 text-primary" />
          <span className="min-w-0 truncate font-display font-bold">{customer.customer_name}</span>
          <span className="ml-auto shrink-0 rounded-full bg-secondary px-2 py-0.5 text-xs font-medium text-secondary-foreground">{periodLabel(year)}</span>
        </div>
      )}
      <main className="mx-auto max-w-7xl px-4 py-6">{!started ? <BlankStart onSample={() => { startSample(); void navigate({ to: "/" }); }} /> : dataReady && data.customers.length === 0 ? <div className="py-12 text-center"><FileSpreadsheet className="mx-auto mb-4 h-10 w-10 text-primary" /><h1 className="font-display text-2xl font-bold">No company data</h1><p className="mt-2 text-muted-foreground">Import an Excel workbook to start a meeting.</p></div> : children}</main>
      {started && data.customers.length > 0 && <div className="sm:hidden"><AskDataButton floating /></div>}
    </div>
  );
}
