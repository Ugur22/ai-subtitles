import { describe, expect, it } from "vitest";
import { buildConversationHistory, findSwapQuestion, settleStreamingMessages, updateMessageById } from "./messages";
import type { Message } from "./types";

let nextId = 0;
const user = (content: string): Message => ({ id: `m${nextId++}`, role: "user", content });
const answer = (content: string, extra: Partial<Message> = {}): Message => ({ id: `m${nextId++}`, role: "assistant", content, ...extra });

describe("settleStreamingMessages", () => {
  it("stops a stream that already has text and turns an empty one into a retryable error", () => {
    const partial = answer("partial", { isStreaming: true });
    const settled = settleStreamingMessages([
      partial,
      answer("", { isStreaming: true, original_question: "why?" }),
    ]);

    expect(settled[0]).toEqual({ ...partial, isStreaming: false });
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

describe("message ids", () => {
  it("keeps ids when settling streams, so in-flight updates still find their message", () => {
    const streaming = answer("", { isStreaming: true });

    expect(settleStreamingMessages([streaming])[0].id).toBe(streaming.id);
  });

  it("patches the right message after a retry removes an earlier one", () => {
    const failed = answer("boom", { isError: true, retryQuestion: "first?" });
    const comparison = answer("Earlier vs later", { isSwapping: true });
    const after = answer("unrelated");
    // A retry drops the failed answer, shifting every later message down one index.
    const shifted = settleStreamingMessages([failed, comparison, after], "first?");

    const patched = updateMessageById(shifted, comparison.id, (m) => ({ ...m, content: "Swapped", isSwapping: false }));

    expect(patched.map((m) => m.content)).toEqual(["Swapped", "unrelated"]);
  });

  it("resolves a comparison's question from itself, else the user turn before it", () => {
    const question = user("Compare her outfits");
    const withOwn = answer("a", { original_question: "Own question" });
    const withoutOwn = answer("b");

    expect(findSwapQuestion([question, withOwn], withOwn.id)).toBe("Own question");
    expect(findSwapQuestion([question, withoutOwn], withoutOwn.id)).toBe("Compare her outfits");
    expect(findSwapQuestion([withoutOwn], withoutOwn.id)).toBe("");
    expect(findSwapQuestion([question], "missing")).toBe("");
  });
});
