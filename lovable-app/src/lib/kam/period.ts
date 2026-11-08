/** Time-period presets counted back from the latest month present in the account's data. */
export const PRESETS = [
  { id: "last12", label: "Last 12M", months: 12 },
] as const;

const shift = (ym: string, n: number) => {
  const [y, m] = ym.split("-").map(Number) as [number, number];
  const d = new Date(Date.UTC(y, m - 1 - n, 1));
  return d.toISOString().slice(0, 7);
};

/** Returns the inclusive month range for a period, or null for "all". */
export function periodRange(period: string, months: string[]): { from: string; to: string } | null {
  if (period === "all" || months.length === 0) return null;
  const sorted = [...months].sort();
  const last = sorted[sorted.length - 1]!;
  const c = /^custom:(\d{4}-\d{2}):(\d{4}-\d{2})$/.exec(period);
  if (c) return c[1]! <= c[2]! ? { from: c[1]!, to: c[2]! } : { from: c[2]!, to: c[1]! };
  if (/^\d{4}$/.test(period)) return { from: `${period}-01`, to: `${period}-12` };
  const p = PRESETS.find((x) => x.id === period);
  return p ? { from: shift(last, p.months - 1), to: last } : null;
}

/** A preset is available only when the data covers its full length. */
export function presetAvailable(id: string, months: string[]) {
  const p = PRESETS.find((x) => x.id === id);
  if (!p || months.length === 0) return false;
  const r = periodRange(id, months)!;
  return [...months].sort()[0]! <= r.from;
}

export function monthName(ym: string) {
  const [y, m] = ym.split("-").map(Number) as [number, number];
  return new Date(Date.UTC(y, m - 1, 1)).toLocaleDateString("en-GB", { month: "short", year: "numeric", timeZone: "UTC" });
}

export const customPeriod = (from: string, to: string) => `custom:${from}:${to}`;

export function inPeriod(month: string, period: string, months: string[]) {
  const r = periodRange(period, months);
  return !r || (month >= r.from && month <= r.to);
}

export function periodLabel(period: string) {
  if (period === "all") return "All data";
  const c = /^custom:(\d{4}-\d{2}):(\d{4}-\d{2})$/.exec(period);
  if (c) return `${monthName(c[1]!)} – ${monthName(c[2]!)}`;
  return PRESETS.find((p) => p.id === period)?.label ?? period;
}
