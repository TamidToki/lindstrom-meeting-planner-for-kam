import { Bar, BarChart, Cell, Line, LineChart, Pie, PieChart, ResponsiveContainer, XAxis, YAxis, ReferenceArea } from "recharts";
import { sampleDataset, type Dataset, type Row } from "@/lib/kam/data";
import { monthlyTrend, siteStats, totals, type Band } from "@/lib/kam/metrics";
import type { Slide } from "@/lib/kam/story";

const axis = { fontSize: 10, stroke: "var(--slide-foreground)", strokeOpacity: 0.6 };

export function SlideChart({ slide, rows, band, data = sampleDataset, staticChart = false }: { slide: Slide; rows: Row[]; band: Band; data?: Dataset; staticChart?: boolean }) {
  if (slide.chart === "trend") {
    const key = slide.id === "water" ? "waterSaved" : "utilisation";
    return (
      <ResponsiveContainer>
        <LineChart data={monthlyTrend(rows, data)}>
          <XAxis dataKey="label" {...axis} />
          <YAxis {...axis} width={34} />
          <Line type="monotone" dataKey={key} stroke="var(--accent)" strokeWidth={3} dot={false} isAnimationActive={!staticChart} />
        </LineChart>
      </ResponsiveContainer>
    );
  }
  if (slide.chart === "sites") {
    const s = siteStats(rows, data).sort((a, b) => a.utilisation - b.utilisation);
    return (
      <ResponsiveContainer>
        <BarChart data={s.map((x) => ({ n: x.city, u: +x.utilisation.toFixed(0) }))}>
          <ReferenceArea y1={band.low} y2={band.high} fill="var(--success)" fillOpacity={0.25} />
          <XAxis dataKey="n" {...axis} hide />
          <YAxis {...axis} width={30} />
          <Bar dataKey="u" radius={[3, 3, 0, 0]} isAnimationActive={!staticChart}>
            {s.map((x) => (
              <Cell key={x.siteId} fill={x.utilisation < band.low || x.utilisation > band.high ? "var(--accent)" : "var(--slide-foreground)"} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    );
  }
  if (slide.chart === "impact") {
    return (
      <ResponsiveContainer>
        <BarChart data={monthlyTrend(rows, data)}>
          <XAxis dataKey="label" {...axis} />
          <YAxis {...axis} width={40} />
          <Bar dataKey="co2Saved" fill="var(--success)" radius={[3, 3, 0, 0]} isAnimationActive={!staticChart} />
        </BarChart>
      </ResponsiveContainer>
    );
  }
  if (slide.chart === "circular") {
    const t = totals(rows, data);
    const pieData = [
      { n: "Recycled / reused", v: t.recycledKg },
      { n: "Other recovery", v: t.textileWaste - t.recycledKg },
    ];
    return (
      <ResponsiveContainer>
        <PieChart>
          <Pie data={pieData} dataKey="v" innerRadius="55%" outerRadius="85%" stroke="none" isAnimationActive={!staticChart}>
            <Cell fill="var(--success)" />
            <Cell fill="var(--slide-foreground)" fillOpacity={0.3} />
          </Pie>
        </PieChart>
      </ResponsiveContainer>
    );
  }
  return null;
}

export function SlideView({ slide, index, rows, band, customerName, data = sampleDataset, isSample = false, staticChart = false }: { slide: Slide; index: number; rows: Row[]; band: Band; customerName: string; data?: Dataset; isSample?: boolean; staticChart?: boolean }) {
  return (
    <div className="print-slide relative flex aspect-video w-full flex-col overflow-hidden rounded-2xl bg-slide p-[4%] text-slide-foreground shadow-lg">
      <div className="text-[clamp(7px,0.9vw,11px)] font-bold uppercase tracking-widest text-accent">
        {isSample ? "Synthetic demo data · Not audited" : "Draft · KAM must review before customer use"}
      </div>
      <div className="flex items-center justify-between text-[clamp(8px,1.1vw,13px)] uppercase tracking-widest opacity-70">
        <span className="text-accent">{slide.kicker}</span>
        <span>
          {customerName} · {index + 1}
        </span>
      </div>
      <h3 className="mt-[2%] font-display text-[clamp(14px,2.4vw,32px)] font-bold leading-tight">{slide.title}</h3>
      <div className="mt-[3%] grid flex-1 grid-cols-5 gap-[3%] min-h-0">
        <div className="col-span-2 flex flex-col gap-[6%]">
          {slide.big.map((b) => (
            <div key={b.label}>
              <div className="font-display text-[clamp(14px,2.6vw,36px)] font-extrabold text-accent leading-none">{b.value}</div>
              <div className="text-[clamp(8px,1vw,13px)] opacity-80">{b.label}</div>
            </div>
          ))}
          {!slide.big.length && (
            <ul className="space-y-[4%] text-[clamp(9px,1.25vw,16px)]">
              {slide.bullets.map((b) => (
                <li key={b} className="flex gap-2">
                  <span className="mt-[0.4em] h-2 w-2 shrink-0 rounded-full bg-accent" />
                  {b}
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="col-span-3 flex min-h-0 flex-col">
          {slide.chart ? (
            <div className="min-h-0 flex-1" data-chart-slide={staticChart ? slide.id : undefined}>
              <SlideChart slide={slide} rows={rows} band={band} data={data} staticChart={staticChart} />
            </div>
          ) : null}
          {slide.big.length > 0 && (
            <ul className="mt-2 space-y-1 text-[clamp(8px,1.05vw,14px)] opacity-90">
              {slide.bullets.map((b) => (
                <li key={b} className="flex gap-2">
                  <span className="mt-[0.45em] h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />
                  {b}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
