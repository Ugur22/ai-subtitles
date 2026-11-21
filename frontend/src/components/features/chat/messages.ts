import type { Message } from "./types";

const HISTORY_LIMIT = 10;

export const newMessageId = (): string => crypto.randomUUID();

export function updateMessageById(messages: Message[], id: string, update: (message: Message) => Message): Message[] {
  return messages.map((m) => (m.id === id ? update(m) : m));
}

/** The question a comparison answer responds to: its own, or the user turn just before it. */
export function findSwapQuestion(messages: Message[], id: string): string {
  const index = messages.findIndex((m) => m.id === id);
  if (index < 0) return "";
  const previous = messages[index - 1];
  return messages[index].original_question || (previous?.role === "user" ? previous.content : "");
}

/**
 * Ends every still-streaming assistant message before a new send, so only the
 * new placeholder animates. A stream that died empty becomes a retryable error.
 * On retry, the previous error for that question is dropped.
 */
export function settleStreamingMessages(messages: Message[], retryQuestion?: string): Message[] {
  return messages.flatMap((m) => {
    if (retryQuestion !== undefined && m.role === "assistant" && m.isError && m.retryQuestion === retryQuestion) {
      return [];
    }
    if (m.role !== "assistant" || !m.isStreaming) return [m];
    if (m.content) return [{ ...m, isStreaming: false }];
    return [{
      ...m,
      isStreaming: false,
      isError: true,
      errorType: "server" as const,
      content: "That request didn't finish. Retry?",
      retryQuestion: m.original_question,
    }];
  });
}

/** The last completed turns sent as context; a retry omits its own earlier question. */
export function buildConversationHistory(messages: Message[], retryQuestion?: string): Array<{ role: string; content: string }> {
  const completed = messages.filter((m) => !m.isError && !m.isStreaming);
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
