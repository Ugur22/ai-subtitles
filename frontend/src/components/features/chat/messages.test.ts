import { describe, expect, it } from "vitest";
import { buildConversationHistory, settleStreamingMessages } from "./messages";
import type { Message } from "./types";

const user = (content: string): Message => ({ role: "user", content });
const answer = (content: string, extra: Partial<Message> = {}): Message => ({ role: "assistant", content, ...extra });

describe("settleStreamingMessages", () => {
  it("stops a stream that already has text and turns an empty one into a retryable error", () => {
    const settled = settleStreamingMessages([
      answer("partial", { isStreaming: true }),
      answer("", { isStreaming: true, original_question: "why?" }),
    ]);

    expect(settled[0]).toEqual(answer("partial", { isStreaming: false }));
    expect(settled[1]).toMatchObject({ isStreaming: false, isError: true, errorType: "server", retryQuestion: "why?" });
  });

  it("drops the previous error for the question being retried, and only that one", () => {
    const messages = [answer("x", { isError: true, retryQuestion: "a" }), answer("y", { isError: true, retryQuestion: "b" })];

    expect(settleStreamingMessages(messages, "a")).toEqual([messages[1]]);
    expect(settleStreamingMessages(messages)).toEqual(messages);
  });
});

describe("buildConversationHistory", () => {
  it("sends only completed turns, capped at the last ten", () => {
    const messages = [...Array.from({ length: 12 }, (_, i) => user(`q${i}`)), answer("", { isStreaming: true }), answer("boom", { isError: true })];

    const history = buildConversationHistory(messages);

    expect(history).toHaveLength(10);
    expect(history[0]).toEqual({ role: "user", content: "q2" });
    expect(history.at(-1)).toEqual({ role: "user", content: "q11" });
  });

  it("omits the latest copy of the retried question", () => {
    const history = buildConversationHistory([user("same"), answer("first"), user("same")], "same");

    expect(history).toEqual([{ role: "user", content: "same" }, { role: "assistant", content: "first" }]);
  });
});
