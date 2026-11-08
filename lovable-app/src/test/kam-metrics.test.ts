import { describe, expect, it } from "vitest";
import { defaultBandFor, utilisation } from "@/lib/kam/metrics";

describe("utilisation band", () => {
  it("defaults to 30–70% for general accounts", () => {
    expect(defaultBandFor("Manufacturing")).toEqual({ low: 30, high: 70 });
  });
  it("sits higher for food and hygiene accounts", () => {
    expect(defaultBandFor("Food & Beverage").low).toBeGreaterThan(30);
    expect(defaultBandFor("Healthcare").high).toBeGreaterThan(70);
  });
  it("compares weekly washes with allocated garments", () => {
    // 100 garments washed once a week for a month = 100%
    expect(utilisation(100 * (52 / 12), 100)).toBeCloseTo(100);
  });
});
