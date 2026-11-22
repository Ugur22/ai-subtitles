import type { Message, MessageStatus } from "./types";

const HISTORY_LIMIT = 10;

// randomUUID only exists in secure contexts (HTTPS/localhost); dev over a LAN IP is plain HTTP.
export const newMessageId = (): string =>
  typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;

export function updateMessageById(messages: Message[], id: string, update: (message: Message) => Message): Message[] {
  return messages.map((m) => (m.id === id ? update(m) : m));
}

/**
 * Ends every still-streaming assistant message before a new send, so only the
 * new placeholder animates. A stream that died empty becomes a retryable error.
 * On retry, the previous error for that question is dropped.
 */
export function settleStreamingMessages(messages: Message[], retryQuestion?: string): Message[] {
  return messages.flatMap((m) => {
    if (retryQuestion !== undefined && m.status.kind === "error" && m.status.retryQuestion === retryQuestion) {
      return [];
    }
    if (m.status.kind !== "streaming") return [m];
    if (m.content) return [{ ...m, status: { kind: "done" } }];
    return [{
      ...m,
      status: { kind: "error", errorType: "server", retryQuestion: m.original_question },
      content: "That request didn't finish. Retry?",
    }];
  });
}

type StreamingStatus = Extract<MessageStatus, { kind: "streaming" }>;

export function updateStreamingProgress(
  message: Message,
  update: (status: StreamingStatus) => Partial<Omit<StreamingStatus, "kind">>,
): Message {
  if (message.status.kind !== "streaming") return message;
  return { ...message, status: { ...message.status, ...update(message.status) } };
}

/** The last completed turns sent as context; a retry omits its own earlier question. */
export function buildConversationHistory(messages: Message[], retryQuestion?: string): Array<{ role: string; content: string }> {
  const completed = messages.filter((m) => m.status.kind === "done");
  if (retryQuestion !== undefined) {
    for (let i = completed.length - 1; i >= 0; i--) {
      if (completed[i].role === "user" && completed[i].content === retryQuestion) {
        completed.splice(i, 1);
        break;
      }
    }
  }
  return completed.slice(-HISTORY_LIMIT).map((m) => ({ role: m.role, content: m.content }));
}
