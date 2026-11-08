import { createFileRoute } from "@tanstack/react-router";
import { convertToModelMessages, type UIMessage } from "ai";

const SYSTEM = `You are the data assistant for a Key Account Manager (KAM) at a workwear rental and laundry service.
The KAM is busy and non-technical. Answer in plain language: short bullet points, concrete numbers from the ACCOUNT DATA, and one practical suggestion for the meeting when useful.
Utilisation = weekly washes divided by allocated garments; the healthy band is given in the data.
Use ONLY the ACCOUNT DATA provided. If the data cannot answer the question, say so plainly and suggest what data would help. Never invent figures.
Tailor the framing to the meeting attendees (procurement = cost, sustainability = CO2/water/circularity, operations = service and sites).`;

export const Route = createFileRoute("/api/chat")({
  server: {
    handlers: {
      POST: async ({ request }) => {
        const apiKey = process.env["LOVABLE_API_KEY"];
        if (!apiKey) return Response.json({ error: "The AI service is not configured." }, { status: 500 });
        let body: { messages?: UIMessage[]; context?: unknown };
        try {
          body = await request.json();
        } catch {
          return Response.json({ error: "Invalid request." }, { status: 400 });
        }
        const messages = Array.isArray(body.messages) ? body.messages.slice(-30) : [];
        if (!messages.length) return Response.json({ error: "No question." }, { status: 400 });
        const ctx = JSON.stringify(body.context ?? {}).slice(0, 60000);
        const { streamResponses } = await import("@/lib/ai/gateway.server");
        const result = streamResponses(request, apiKey, "openai/gpt-6-astra", `${SYSTEM}\n\nACCOUNT DATA (JSON):\n${ctx}`, await convertToModelMessages(messages));
        return result.toUIMessageStreamResponse({
          sendReasoning: false,
          onError: (e) => {
            const s = (e as { statusCode?: number })?.statusCode;
            console.error("chat error", e);
            if (s === 402) return "AI credits have run out. Add credits in Settings → Plans & credits.";
            if (s === 429) return "The AI service is busy. Please try again in a moment.";
            if (s === 403) return "The AI service refused this request.";
            return "The AI could not answer right now.";
          },
        });
      },
    },
  },
});
