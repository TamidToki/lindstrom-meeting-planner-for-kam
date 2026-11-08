import { describe, expect, it } from "vitest";
import { PRESETS, periodRange, presetAvailable } from "@/lib/kam/period";
const months = Array.from({ length: 18 }, (_, i) => new Date(Date.UTC(2025, i, 1)).toISOString().slice(0, 7)); // 2025-01..2026-06
describe("period presets", () => {
  it("only Last 12M is offered as a quick preset", () => expect(PRESETS.map((p) => p.id)).toEqual(["last12"]));
  it("Last 12M crosses the year boundary", () => expect(periodRange("last12", months)).toEqual({ from: "2025-07", to: "2026-06" }));
  it("custom range uses the chosen months, in order", () => expect(periodRange("custom:2026-03:2025-11", months)).toEqual({ from: "2025-11", to: "2026-03" }));
  it("disables Last 12M when data is shorter", () => {
    expect(presetAvailable("last12", months.slice(0, 6))).toBe(false);
    expect(presetAvailable("last12", months)).toBe(true);
  });
});
