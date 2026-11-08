import { describe, it, expect } from "vitest";
import { buildAiContext } from "@/lib/kam/aiContext";
import { sampleDataset } from "@/lib/kam/data";
import { customerRows, DEFAULT_BAND } from "@/lib/kam/metrics";

describe("AI context", () => {
  const c = sampleDataset.customers[0]!;
  const base = { data: sampleDataset, customerId: c.customer_id, customerName: c.customer_name, industry: c.industry, year: "all", band: DEFAULT_BAND, attendees: [], priorities: [] };
  it("leaves excluded rows out of the figures sent to the AI", () => {
    const rs = customerRows(c.customer_id, new Set(), sampleDataset);
    const full = buildAiContext({ ...base, excluded: new Set() });
    const ex = buildAiContext({ ...base, excluded: new Set([rs[0]!.id]) });
    expect(ex.totals.washes).toBe(full.totals.washes - rs[0]!.washed);
    expect(ex.excludedExceptionLines).toBe(1);
  });
  it("never includes raw rows", () => {
    const ctx = buildAiContext({ ...base, excluded: new Set() }) as Record<string, unknown>;
    expect(ctx).not.toHaveProperty("rows");
  });
});
