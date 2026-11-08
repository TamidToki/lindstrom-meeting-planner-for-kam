import { useChat } from "@ai-sdk/react";
import { useMemo, useState } from "react";
import { Download, MessageCircleQuestion, ShieldCheck, Trash2, Waves } from "lucide-react";
import { Conversation, ConversationContent, ConversationEmptyState, ConversationScrollButton } from "@/components/ai-elements/conversation";
import { Message, MessageContent, MessageResponse } from "@/components/ai-elements/message";
import { PromptInput, PromptInputFooter, PromptInputSubmit, PromptInputTextarea, PromptInputTools } from "@/components/ai-elements/prompt-input";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { useKam } from "@/lib/kam/store";
import { buildAiContext } from "@/lib/kam/aiContext";
import { downloadText, getChatSession, messageText, sessionTranscript } from "@/lib/kam/chatSession";
import { suggestedQuestions } from "@/lib/kam/chatStarters";

function useStarters() {
  const { attendees, priorities } = useKam();
  return useMemo(() => suggestedQuestions(attendees, priorities), [attendees, priorities]);
}

export function AskDataChat({ className = "" }: { className?: string }) {
  const kam = useKam();
  const { messages, sendMessage, status, setMessages, error } = useChat({ chat: getChatSession() });
  const [text, setText] = useState("");
  const starters = useStarters();

  const ask = (q: string) => {
    if (!q.trim() || status === "streaming" || status === "submitted") return;
    const context = buildAiContext({
      data: kam.data, customerId: kam.customer.customer_id, customerName: kam.customer.customer_name,
      industry: kam.customer.industry, year: kam.year, excluded: kam.excludedSet, band: kam.band,
      attendees: kam.attendees, priorities: kam.priorities,
    });
    sendMessage({ text: q }, { body: { context } });
    setText("");
  };

  return (
    <div className={`flex min-h-0 flex-col gap-3 ${className}`}>
      <p className="flex items-start gap-2 rounded-lg bg-secondary px-3 py-2 text-xs text-secondary-foreground">
        <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" />
        Only summary figures for {kam.customer.customer_name} are shared with the AI. Raw files stay on this computer.
      </p>
      <Conversation className="min-h-0 flex-1 rounded-xl border bg-card">
        <ConversationContent>
          {messages.length === 0 ? (
            <ConversationEmptyState title="Ask about this account" description="Pick a question or type your own.">
              <div className="flex flex-col items-center gap-3 text-center">
                <Waves className="h-8 w-8 text-primary" />
                <p className="font-display font-semibold">Ask about {kam.customer.customer_name}</p>
                <div className="flex flex-wrap justify-center gap-2">
                  {starters.map((s) => (
                    <button key={s} onClick={() => ask(s)} className="rounded-full border bg-background px-3 py-1.5 text-xs hover:border-primary">
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            </ConversationEmptyState>
          ) : (
            messages.map((m) => (
              <Message from={m.role} key={m.id}>
                <MessageContent className={m.role === "user" ? "bg-primary text-primary-foreground" : ""}>
                  {m.role === "user" ? messageText(m) : <MessageResponse>{messageText(m)}</MessageResponse>}
                </MessageContent>
              </Message>
            ))
          )}
          {status === "submitted" && <p className="animate-pulse text-sm text-muted-foreground">Reading the figures…</p>}
          {error && <p className="text-sm text-destructive">{error.message || "The AI could not answer right now."}</p>}
        </ConversationContent>
        <ConversationScrollButton />
      </Conversation>
      <PromptInput onSubmit={(msg) => ask(msg.text ?? text)}>
        <PromptInputTextarea value={text} onChange={(e) => setText(e.target.value)} placeholder="e.g. Why is utilisation low at the bakery site?" />
        <PromptInputFooter>
          <PromptInputTools>
            <Button type="button" variant="ghost" size="sm" disabled={!messages.length}
              onClick={() => downloadText(sessionTranscript(messages, kam.customer.customer_name), `${kam.customer.customer_name.replace(/\s+/g, "_")}_ai_session.txt`)}>
              <Download className="mr-1 h-4 w-4" /> Session .txt
            </Button>
            <Button type="button" variant="ghost" size="sm" disabled={!messages.length} onClick={() => setMessages([])}>
              <Trash2 className="mr-1 h-4 w-4" /> Clear
            </Button>
          </PromptInputTools>
          <PromptInputSubmit status={status} disabled={!text.trim() && status === "ready"} />
        </PromptInputFooter>
      </PromptInput>
      <p className="text-xs text-muted-foreground">Answers use a summary of the selected account's figures. Review before sharing.</p>
    </div>
  );
}

export function AskDataButton({ floating = false }: { floating?: boolean }) {
  return (
    <Sheet>
      <SheetTrigger asChild>
        {floating ? (
          <Button aria-label="Ask AI about this account" className="no-print fixed bottom-4 right-4 z-40 h-12 rounded-full bg-accent px-5 text-accent-foreground shadow-lg hover:bg-accent/90">
            <MessageCircleQuestion className="mr-1 h-5 w-5" /> Ask AI
          </Button>
        ) : (
        <Button className="bg-accent text-accent-foreground shadow-md hover:bg-accent/90">
          <MessageCircleQuestion className="mr-1 h-4 w-4" /> Ask AI about this account
        </Button>
        )}
      </SheetTrigger>
      <SheetContent className="flex w-full flex-col sm:max-w-lg">
        <SheetHeader>
          <SheetTitle className="font-display">Ask the data</SheetTitle>
        </SheetHeader>
        <AskDataChat className="flex-1" />
      </SheetContent>
    </Sheet>
  );
}
