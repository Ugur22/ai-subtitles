import { afterEach, describe, expect, it, vi } from "vitest";
import { buildConversationHistory, newMessageId, settleStreamingMessages, updateMessageById } from "./messages";
import type { Message } from "./types";

let nextId = 0;
const user = (content: string): Message => ({ id: `m${nextId++}`, role: "user", content });
const answer = (content: string, extra: Partial<Message> = {}): Message => ({ id: `m${nextId++}`, role: "assistant", content, ...extra });

describe("settleStreamingMessages", () => {
  it("stops a stream that already has text and turns an empty one into a retryable error", () => {
    const partial = answer("partial", { isStreaming: true });
    const empty = answer("", { isStreaming: true, original_question: "why?" });
    const settled = settleStreamingMessages([partial, empty]);

    expect(settled[0]).toEqual({ ...partial, isStreaming: false });
    expect(settled[1]).toMatchObject({ id: empty.id, isStreaming: false, isError: true, errorType: "server", retryQuestion: "why?" });
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
  it("patches the right message after a retry removes an earlier one", () => {
    const failed = answer("boom", { isError: true, retryQuestion: "first?" });
    const comparison = answer("Earlier vs later", { isSwapping: true });
    const after = answer("unrelated");
    const shifted = settleStreamingMessages([failed, comparison, after], "first?");

    const patched = updateMessageById(shifted, comparison.id, (m) => ({ ...m, content: "Swapped", isSwapping: false }));

    expect(patched.map((m) => m.content)).toEqual(["Swapped", "unrelated"]);
  });
});

describe("newMessageId", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("still produces distinct ids where randomUUID is unavailable (plain-HTTP dev)", () => {
    vi.stubGlobal("crypto", {});

    const ids = new Set(Array.from({ length: 50 }, newMessageId));

    expect(ids.size).toBe(50);
  });
});
