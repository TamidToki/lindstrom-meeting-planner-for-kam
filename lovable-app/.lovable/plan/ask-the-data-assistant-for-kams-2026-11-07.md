# "Ask the data" assistant for KAMs

## What the KAM gets
- An **Ask** button on every step opens a side panel, and Advanced mode gets the same assistant as a tab of its own.
- The KAM types a question in plain language, e.g. "Which site wastes the most garments?", "How do I explain the CO2 drop to a sustainability lead?" or "What should I raise with procurement?". The answer comes back as short points with real numbers.
- Starter question chips change with the selected account, attendees and priorities, so a busy KAM can just click one.
- A small note in the panel says: "Only summary figures for this account are shared with the AI. Raw files stay on this computer."
- Chats are not saved. Instead there is a **Download session (.txt)** button, and the same text can be added to the deck export, next to the talking points.

## How it answers
- Before each question, the app builds a compact summary of the selected account and year: totals, utilisation and band, per-site stats, outliers, trends, repairs, recycling, and the chosen attendees and priorities. It uses the metric functions the app already has. Rows the KAM excluded stay out.
- That summary is sent with the question to an OpenAI model through the built-in AI service. No OpenAI account or key is needed, and it can be switched to a direct OpenAI key later if needed.
- The assistant is told to use only the provided figures and to say plainly when the data can't answer something.
- Clear messages appear when credits run out or the service is busy.

## Technical details
- Server streaming route `src/routes/api/chat.ts` using AI SDK `streamText` on `/v1/responses`, model `openai/gpt-6-astra`, with reasoning effort low and `store:false`. It uses `LOVABLE_API_KEY`, which is provisioned if missing. No database and no Cloud tables are involved.
- Gateway helpers live in server-only modules under `src/lib/ai/`.
- `src/lib/kam/aiContext.ts` builds the summary as a pure function, with a small test that checks excluded rows are left out.
- The chat UI is built from AI Elements components (`Conversation`, `Message`, `MessageResponse`, `PromptInput`) inside a `Sheet` in `AppShell`, and the Advanced tab reuses the same component. It is one session in memory only.
- Session export turns the messages into plain text: download as .txt, and add it optionally to the PPTX notes or the print view.
- Update the `AGENTS.md` and privacy memory rules: aggregated summaries may be sent to the AI service, but raw rows never are.
