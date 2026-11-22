import { afterEach, describe, expect, it, vi } from "vitest";
import { buildConversationHistory, newMessageId, settleStreamingMessages, updateMessageById, updateStreamingProgress } from "./messages";
import type { Message, MessageStatus } from "./types";

let nextId = 0;
const streaming: MessageStatus = { kind: "streaming", phases: [], screenshotCount: 0 };
const failedWith = (retryQuestion?: string): MessageStatus => ({ kind: "error", errorType: "server", retryQuestion });
const user = (content: string): Message => ({ id: `m${nextId++}`, role: "user", content, status: { kind: "done" } });
const answer = (content: string, extra: Partial<Message> = {}): Message => ({
  id: `m${nextId++}`,
  role: "assistant",
  content,
  status: { kind: "done" },
  ...extra,
});

describe("settleStreamingMessages", () => {
  it("stops a stream that already has text and turns an empty one into a retryable error", () => {
    const partial = answer("partial", { status: streaming });
    const empty = answer("", { status: streaming, original_question: "why?" });
    const settled = settleStreamingMessages([partial, empty]);

    expect(settled[0]).toEqual({ ...partial, status: { kind: "done" } });
    expect(settled[1]).toMatchObject({ id: empty.id, status: { kind: "error", errorType: "server", retryQuestion: "why?" } });
  });

  it("drops the previous error for the question being retried, and only that one", () => {
    const messages = [answer("x", { status: failedWith("a") }), answer("y", { status: failedWith("b") })];

    expect(settleStreamingMessages(messages, "a")).toEqual([messages[1]]);
    expect(settleStreamingMessages(messages)).toEqual(messages);
  });

  it("keeps a failed swap on a settled answer", () => {
    const comparison = answer("Earlier vs later", { status: streaming, swap: { kind: "failed", error: "Swap failed" } });

    expect(settleStreamingMessages([comparison])[0]).toMatchObject({
      status: { kind: "done" },
      swap: { kind: "failed", error: "Swap failed" },
    });
  });
});

describe("updateStreamingProgress", () => {
  it("updates the progress of a streaming answer", () => {
    const live = answer("", { status: streaming });

    expect(updateStreamingProgress(live, () => ({ screenshotCount: 3 })).status).toEqual({ ...streaming, screenshotCount: 3 });
  });

  it("leaves a settled answer untouched", () => {
    const settled = answer("done");

    expect(updateStreamingProgress(settled, () => ({ screenshotCount: 3 }))).toBe(settled);
  });
});

describe("buildConversationHistory", () => {
  it("sends only completed turns, capped at the last ten", () => {
    const messages = [
      ...Array.from({ length: 12 }, (_, i) => user(`q${i}`)),
      answer("", { status: streaming }),
      answer("boom", { status: failedWith() }),
    ];

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
    const failed = answer("boom", { status: failedWith("first?") });
    const comparison = answer("Earlier vs later", { swap: { kind: "pending", bSeconds: 12, target: "b" } });
    const after = answer("unrelated");
    const shifted = settleStreamingMessages([failed, comparison, after], "first?");

    const patched = updateMessageById(shifted, comparison.id, (m) => ({ ...m, content: "Swapped", swap: { kind: "idle" } }));

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
