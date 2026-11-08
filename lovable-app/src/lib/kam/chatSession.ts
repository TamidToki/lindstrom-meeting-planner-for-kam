import { Chat } from "@ai-sdk/react";
import { DefaultChatTransport, type UIMessage } from "ai";

let chat: Chat<UIMessage> | null = null;

/** One in-memory chat session shared by the side panel and the Advanced tab. Not persisted. */
export function getChatSession() {
  chat ??= new Chat<UIMessage>({ transport: new DefaultChatTransport({ api: "/api/chat" }) });
  return chat;
}

export function messageText(m: UIMessage) {
  return m.parts.map((p) => (p.type === "text" ? p.text : "")).join("");
}

export function sessionTranscript(messages: UIMessage[], account: string) {
  const lines = [`KAM data assistant session — ${account}`, `Saved ${new Date().toLocaleString()}`, ""];
  for (const m of messages) {
    lines.push(m.role === "user" ? "Q:" : "A:", messageText(m).trim(), "");
  }
  return lines.join("\n");
}

export function downloadText(text: string, fileName: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = fileName;
  a.click();
  URL.revokeObjectURL(url);
}
