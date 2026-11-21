import { useRef, useState } from "react";
import axios from "axios";
import { API_BASE_URL } from "../../../../config";
import { getFriendlyErrorMessage } from "../chatErrors";
import { advancePhases, parseStreamSources, takeSseDataLines } from "../chatStream";
import { buildConversationHistory, newMessageId, settleStreamingMessages, updateMessageById } from "../messages";
import { PHASE_LABELS, isPhaseId } from "../phases";
import { useStableCallback } from "../../../../hooks/useStableCallback";
import type { Message, PersonComparisonData, PhaseEntry, ReasoningEffort, TimelineFrame } from "../types";

interface ChatConversationOptions {
  videoHash: string | null;
  selectedProvider: string;
  selectedModel: string;
  selectedEffort: ReasoningEffort | undefined;
  includeVisuals: boolean;
  customInstructions: string;
}

export function useChatConversation({
  videoHash,
  selectedProvider,
  selectedModel,
  selectedEffort,
  includeVisuals,
  customInstructions,
}: ChatConversationOptions) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);
  const [phases, setPhases] = useState<PhaseEntry[]>([]);
  const [screenshotCount, setScreenshotCount] = useState(0);

  const updateMessage = (messageId: string, update: (message: Message) => Message) => {
    setMessages((previous) => updateMessageById(previous, messageId, update));
  };

  const sendViaStream = async (
    textToSend: string,
    history: Array<{ role: string; content: string }>,
    assistantId: string,
  ) => {
    const updateAssistant = (update: (message: Message) => Message) => updateMessage(assistantId, update);
    try {
      const response = await axios.post<ReadableStream<Uint8Array>>(
        `${API_BASE_URL}/api/chat/stream`,
        {
          question: textToSend,
          video_hash: videoHash,
          provider: selectedProvider,
          model: selectedModel || undefined,
          reasoning_effort: selectedEffort,
          n_results: 8,
          include_visuals: includeVisuals,
          n_images: includeVisuals ? 6 : undefined,
          custom_instructions: customInstructions || undefined,
          conversation_history: history.length > 0 ? history : undefined,
        },
        {
          adapter: "fetch",
          responseType: "stream",
          headers: { Accept: "text/event-stream" },
          timeout: 300000,
          withCredentials: true,
        }
      );
      if (!response.headers["content-type"]?.includes("text/event-stream")) {
        throw new Error("The server did not return a chat stream.");
      }
      const reader = response.data.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let completed = false;
      try {
        while (!completed) {
          const { value, done } = await reader.read();
          buffer += decoder.decode(value, { stream: !done });
          const { payloads, rest } = takeSseDataLines(buffer);
          buffer = rest;
          for (const payload of payloads) {
            const event: unknown = JSON.parse(payload);
            if (!event || typeof event !== "object" || !("type" in event)) {
              throw new Error("Invalid chat stream event.");
            }
            switch (event.type) {
              case "token": {
                if (!("content" in event) || typeof event.content !== "string") {
                  throw new Error("Invalid chat token.");
                }
                const content = event.content;
                updateAssistant((message) => ({ ...message, content: message.content + content }));
                break;
              }
              case "reset":
                updateAssistant((message) => ({ ...message, content: "" }));
                break;
              case "sources": {
                if (!("sources" in event) || !Array.isArray(event.sources)) {
                  throw new Error("Invalid chat sources.");
                }
                const sources = parseStreamSources(event.sources);
                const visualQuery = "visual_query_used" in event && typeof event.visual_query_used === "string" ? event.visual_query_used : undefined;
                const variants = "visual_query_variants" in event && Array.isArray(event.visual_query_variants)
                  ? event.visual_query_variants.filter((value): value is string => typeof value === "string") : [];
                updateAssistant((message) => ({ ...message, sources, visual_query_used: visualQuery, visual_query_variants: variants }));
                setScreenshotCount(sources.filter((source) => source.screenshot_url).length);
                break;
              }
              case "phase": {
                if (!("phase" in event) || !isPhaseId(event.phase)) break;
                const id = event.phase;
                const label = "label" in event && typeof event.label === "string" ? event.label : PHASE_LABELS[id];
                setPhases((previous) => advancePhases(previous, id, label, Date.now()));
                break;
              }
              case "error":
                throw new Error("message" in event && typeof event.message === "string" ? event.message : "Chat generation failed.");
              case "done":
                completed = true;
                break;
            }
            if (completed) break;
          }
          if (done) break;
        }
        if (!completed) throw new Error("The connection closed before the answer finished. Please retry.");
        updateAssistant((message) => ({ ...message, isStreaming: false }));
      } finally {
        await reader.cancel().catch(() => undefined);
        reader.releaseLock();
      }
    } catch (error: unknown) {
      if (axios.isAxiosError<unknown>(error) && error.response?.data instanceof ReadableStream) {
        try {
          const body: unknown = await new Response(error.response.data).json();
          error.response.data = body;
        } catch {
          // Proxies can return HTML or an incomplete body; retain the HTTP status fallback.
        }
      }
      const friendly = getFriendlyErrorMessage(error);
      const message = error instanceof Error && !axios.isAxiosError(error) ? error.message : friendly.message;
      updateAssistant((previous) => ({
        ...previous,
        content: previous.content ? `${previous.content}\n\n${message}` : message,
        isError: true,
        errorType: friendly.errorType,
        retryQuestion: textToSend,
        isStreaming: false,
      }));
    }
  };

  const patchMessage = (messageId: string, patch: Partial<Message>) => updateMessage(messageId, (m) => ({ ...m, ...patch }));

  const swapControllers = useRef(new Map<string, AbortController>());

  const swapComparisonFrame = async (
    messageId: string,
    originalQuestion: string | undefined,
    meta: PersonComparisonData,
    frame: TimelineFrame,
    target: "a" | "b",
  ) => {
    if (!videoHash || !originalQuestion) return;
    if (!meta.person || !meta.frame_a || !meta.frame_b) return;
    if (typeof meta.frame_a.timestamp_seconds !== "number") return;

    swapControllers.current.get(messageId)?.abort();
    const controller = new AbortController();
    swapControllers.current.set(messageId, controller);

    patchMessage(messageId, {
      isSwapping: true,
      pendingBSeconds: frame.timestamp_seconds,
      pendingSwapTarget: target,
      swapError: undefined,
    });

    try {
      const response = await axios.post(
        `${API_BASE_URL}/api/chat/comparison/swap`,
        {
          video_hash: videoHash,
          person: meta.person,
          secondary_person: meta.secondary_person,
          frame_a_seconds:
            target === "a" ? frame.timestamp_seconds : meta.frame_a.timestamp_seconds,
          frame_b_seconds:
            target === "b" ? frame.timestamp_seconds : meta.frame_b.timestamp_seconds,
          question: originalQuestion,
          custom_instructions: customInstructions || undefined,
          provider: selectedProvider,
          model: selectedModel || undefined,
          reasoning_effort: selectedEffort,
        },
        {
          signal: controller.signal,
          timeout: 180000,
          withCredentials: true,
        },
      );

      if (controller.signal.aborted) return;

      patchMessage(messageId, {
        content: response.data.answer,
        isSwapping: false,
        pendingBSeconds: null,
        pendingSwapTarget: null,
        swapError: undefined,
      });
    } catch (error: unknown) {
      if (axios.isCancel(error) || (error instanceof Error && (error.name === "CanceledError" || error.name === "AbortError"))) {
        return;
      }
      const { message } = getFriendlyErrorMessage(error);
      patchMessage(messageId, {
        isSwapping: false,
        pendingBSeconds: null,
        pendingSwapTarget: null,
        swapError: message,
      });
    } finally {
      if (swapControllers.current.get(messageId) === controller) swapControllers.current.delete(messageId);
    }
  };

  const dismissSwapError = (messageId: string) => patchMessage(messageId, { swapError: undefined });

  const sendMessage = (
    textToSend: string,
    options?: { retry?: boolean }
  ): boolean => {
    if (!textToSend.trim() || !videoHash || loading) return false;
    const isRetry = Boolean(options?.retry);

    const userMessage: Message = {
      id: newMessageId(),
      role: "user",
      content: textToSend,
    };

    const placeholderAssistant: Message = {
      id: newMessageId(),
      role: "assistant",
      content: "",
      original_question: textToSend,
      isStreaming: true,
    };

    const retryQuestion = isRetry ? textToSend : undefined;
    setMessages((prev) => {
      const settled = settleStreamingMessages(prev, retryQuestion);
      return isRetry ? [...settled, placeholderAssistant] : [...settled, userMessage, placeholderAssistant];
    });
    setLoading(true);
    setPhases([
      {
        id: "generating",
        label: includeVisuals ? "Analyzing video" : PHASE_LABELS.generating,
        status: "active",
        startedAt: Date.now(),
      },
    ]);
    setScreenshotCount(0);

    const history = buildConversationHistory(messages, retryQuestion);

    void (async () => {
      try {
        await sendViaStream(textToSend, history, placeholderAssistant.id);
      } finally {
        setLoading(false);
        setPhases([]);
        setScreenshotCount(0);
      }
    })();
    return true;
  };

  return {
    messages,
    loading,
    phases,
    screenshotCount,
    sendMessage: useStableCallback(sendMessage),
    retryMessage: useStableCallback((question: string) => sendMessage(question, { retry: true })),
    swapComparisonFrame: useStableCallback(swapComparisonFrame),
    dismissSwapError: useStableCallback(dismissSwapError),
  };
}
