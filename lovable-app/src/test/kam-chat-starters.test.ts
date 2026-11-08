import { describe, expect, it } from "vitest";
import { suggestedQuestions } from "@/lib/kam/chatStarters";
import type { Attendee, Priority } from "@/lib/kam/context";

describe("three distinct suggested questions", () => {
  const cases: [string, Attendee[], Priority[]][] = [
    ["default choices", ["procurement", "sustainability"], ["cost", "co2"]],
    ["no choices", [], []],
    ["operations only", ["operations"], []],
    ["recycling only", [], ["recycling"]],
  ];
  it.each(cases)("offers exactly three for %s", (_label, attendees, priorities) => {
    const questions = suggestedQuestions(attendees, priorities);
    expect(questions).toHaveLength(3);
    expect(new Set(questions).size).toBe(3);
  });
  it("keeps relevant operations and recycling suggestions ahead of fallbacks", () => {
    expect(suggestedQuestions(["operations"], [])[0]).toContain("late deliveries");
    expect(suggestedQuestions([], ["recycling"])[0]).toContain("textile recycling");
  });
});