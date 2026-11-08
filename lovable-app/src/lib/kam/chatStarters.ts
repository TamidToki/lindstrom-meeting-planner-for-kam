import type { Attendee, Priority } from "./context";

/** Relevant questions first, with distinct general fallbacks for every selection. */
export function suggestedQuestions(attendees: Attendee[], priorities: Priority[]): string[] {
  const questions: string[] = [];
  if (attendees.includes("procurement") || priorities.includes("cost")) questions.push("Which sites sit outside the utilisation band, and what should I confirm?");
  if (attendees.includes("sustainability") || priorities.includes("co2") || priorities.includes("water")) questions.push("How do I explain our CO₂ and water savings to a sustainability lead?");
  if (priorities.includes("recycling")) questions.push("What does the data say about textile recycling?");
  if (attendees.includes("operations") || priorities.includes("hygiene")) questions.push("Which sites have late deliveries or high repairs?");
  questions.push(
    "Which site needs attention first, and why?",
    "Give me three talking points for this meeting.",
    "What should I confirm with the customer before sharing these figures?",
  );
  return [...new Set(questions)].slice(0, 3);
}