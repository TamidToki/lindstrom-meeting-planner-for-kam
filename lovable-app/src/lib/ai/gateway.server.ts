import { createOpenAI } from "@ai-sdk/openai";
import { streamText, type ModelMessage } from "ai";

const RUN = "X-Lovable-AIG-Run-ID";

function runIdFetch(initial?: string) {
  let runId = initial?.trim() || undefined;
  return {
    getRunId: () => runId,
    fetch: async (input: RequestInfo | URL, init?: RequestInit) => {
      const headers = new Headers(init?.headers);
      if (runId && !headers.has(RUN)) headers.set(RUN, runId);
      const res = await fetch(input, { ...init, headers });
      runId ??= res.headers.get(RUN)?.trim() || undefined;
      return res;
    },
  };
}

export function streamResponses(request: Request, apiKey: string, model: string, system: string, messages: ModelMessage[]) {
  const rf = runIdFetch(request.headers.get(RUN) ?? undefined);
  const provider = createOpenAI({
    baseURL: "https://ai.gateway.lovable.dev/v1",
    apiKey,
    headers: { "Lovable-API-Key": apiKey, "X-Lovable-AIG-SDK": "vercel-ai-sdk" },
    fetch: rf.fetch,
  });
  return streamText({
    model: provider.responses(model),
    system,
    messages,
    abortSignal: request.signal,
    maxRetries: 1,
    providerOptions: {
      openai: {
        forceReasoning: true,
        reasoningEffort: "low",
        reasoningSummary: "auto",
        store: false,
        include: ["reasoning.encrypted_content"],
      },
    },
  });
}
