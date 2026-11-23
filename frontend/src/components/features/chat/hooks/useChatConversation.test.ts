// @vitest-environment jsdom
import { act, renderHook, waitFor } from "@testing-library/react";
import axios from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { PersonComparisonData, TimelineFrame } from "../types";
import { useChatConversation } from "./useChatConversation";

type PendingSwap = {
  settleAndWait: (answer: string) => Promise<unknown>;
  signal?: AbortSignal;
};

function sseStream(...events: object[]) {
  const body = events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join("");
  return {
    headers: { "content-type": "text/event-stream" },
    data: new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(body));
        controller.close();
      },
    }),
  };
}

function mockApi(streams: Array<ReturnType<typeof sseStream>>) {
  const swaps: PendingSwap[] = [];
  const post = (url: string, _body?: unknown, config?: { signal?: AbortSignal }): Promise<unknown> => {
    if (url.endsWith("/api/chat/stream")) {
      const next = streams.shift();
      if (!next) throw new Error("unexpected stream call");
      return Promise.resolve(next);
    }
    let settle!: (value: { data: { answer: string } }) => void;
    const promise = new Promise<{ data: { answer: string } }>((r) => {
      settle = r;
    });
    swaps.push({
      settleAndWait: (answer) => {
        settle({ data: { answer } });
        return promise;
      },
      signal: config?.signal,
    });
    return promise;
  };
  vi.spyOn(axios, "post").mockImplementation(post as typeof axios.post);
  return swaps;
}

const meta: PersonComparisonData = {
  person: "Tokyo",
  frame_a: { url: "a.jpg", timestamp: "00:00:10", timestamp_seconds: 10 },
  frame_b: { url: "b.jpg", timestamp: "00:00:20", timestamp_seconds: 20 },
};
const frame = (seconds: number): TimelineFrame => ({ url: `${seconds}.jpg`, timestamp: "", timestamp_seconds: seconds });

function renderConversation() {
  return renderHook(() =>
    useChatConversation({
      videoHash: "video-1",
      selectedProvider: "groq",
      selectedModel: "",
      selectedEffort: undefined,
      includeVisuals: false,
      customInstructions: "",
    }),
  );
}

async function askFirstQuestion(result: ReturnType<typeof renderConversation>["result"]) {
  act(() => {
    result.current.sendMessage("Compare Tokyo");
  });
  await waitFor(() => expect(result.current.loading).toBe(false));
  const assistant = result.current.messages.find((m) => m.role === "assistant");
  if (!assistant) throw new Error("no assistant message");
  return assistant.id;
}

describe("useChatConversation swap races", () => {
  afterEach(() => vi.restoreAllMocks());

  it("ignores a superseded swap that resolves late", async () => {
    const swaps = mockApi([sseStream({ type: "token", content: "first answer" }, { type: "done" })]);
    const { result } = renderConversation();
    const messageId = await askFirstQuestion(result);

    act(() => {
      void result.current.swapComparisonFrame(messageId, "Compare Tokyo", meta, frame(30), "b");
    });
    act(() => {
      void result.current.swapComparisonFrame(messageId, "Compare Tokyo", meta, frame(40), "b");
    });
    expect(swaps).toHaveLength(2);
    expect(swaps[0].signal?.aborted).toBe(true);

    await act(() => swaps[1].settleAndWait("answer for 40s"));
    await act(() => swaps[0].settleAndWait("stale answer for 30s"));

    const message = result.current.messages.find((m) => m.id === messageId);
    expect(message?.content).toBe("answer for 40s");
    expect(message?.swap).toEqual({ kind: "idle" });
  });

  it("lands a swap on its own message after a retry appends a new one", async () => {
    const swaps = mockApi([
      sseStream({ type: "token", content: "first answer" }, { type: "done" }),
      sseStream({ type: "token", content: "retried answer" }, { type: "done" }),
    ]);
    const { result } = renderConversation();
    const messageId = await askFirstQuestion(result);

    act(() => {
      void result.current.swapComparisonFrame(messageId, "Compare Tokyo", meta, frame(30), "b");
    });
    act(() => {
      result.current.retryMessage("Compare Tokyo");
    });
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(() => swaps[0].settleAndWait("swapped answer"));

    const assistants = result.current.messages.filter((m) => m.role === "assistant");
    expect(assistants).toHaveLength(2);
    expect(assistants[0]).toMatchObject({ id: messageId, content: "swapped answer", swap: { kind: "idle" } });
    expect(assistants[1]).toMatchObject({ content: "retried answer", status: { kind: "done" } });
    expect(assistants[1].swap).toBeUndefined();
  });
});
