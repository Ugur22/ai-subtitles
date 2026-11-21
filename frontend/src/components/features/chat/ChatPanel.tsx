import { memo, useCallback, useState, useLayoutEffect, useRef } from "react";
import { useTransition, animated } from "react-spring";
import { ChatComposer } from "./ChatComposer";
import { ChatMessage } from "./ChatMessage";
import { ChatSettingsPanel } from "./ChatSettingsPanel";
import { ChatStatusBanners } from "./ChatStatusBanners";
import { ChatSuggestions } from "./ChatSuggestions";
import { ScreenshotModal } from "./ScreenshotModal";
import { useChatConversation } from "./hooks/useChatConversation";
import { useChatIndexing } from "./hooks/useChatIndexing";
import { useChatProviders } from "./hooks/useChatProviders";
import type { ScreenshotModalState } from "./types";

interface ChatPanelProps {
  videoHash: string | null;
  transcriptSpeakers: string[];
  onTimestampClick?: (timeString: string) => void;
  jobId?: string | null;
  accessToken?: string;
}

const ChatPanelInner: React.FC<ChatPanelProps> = ({
  videoHash,
  transcriptSpeakers,
  onTimestampClick,
  jobId,
  accessToken,
}) => {
  const [input, setInput] = useState("");
  const [includeVisuals, setIncludeVisuals] = useState(true);
  const [screenshotModal, setScreenshotModal] = useState<ScreenshotModalState | null>(null);
  const [customInstructions, setCustomInstructions] = useState<string>("");
  const chatProviders = useChatProviders();
  const { indexingStatus, reindexing, reindexStatus, handleReindex } = useChatIndexing(videoHash);
  const conversation = useChatConversation({
    videoHash,
    selectedProvider: chatProviders.selectedProvider,
    selectedModel: chatProviders.selectedModel,
    selectedEffort: chatProviders.selectedEffort,
    includeVisuals,
    customInstructions,
  });
  const { messages, loading, phases, screenshotCount, swapComparisonFrame, dismissSwapError } = conversation;
  const messagesContainerRef = useRef<HTMLDivElement>(null);
  const latestQuestionRef = useRef<HTMLDivElement>(null);
  const latestQuestion = [...messages].reverse().find((message) => message.role === "user");

  const sendMessage = (text: string) => {
    if (conversation.sendMessage(text)) setInput("");
  };
  const conversationSend = conversation.sendMessage;
  const retryMessage = useCallback((question: string) => {
    conversationSend(question, { retry: true });
  }, [conversationSend]);

  // Message transitions
  const messageTransitions = useTransition(messages, {
    from: { opacity: 0, transform: "translate3d(0, 10px, 0)" },
    enter: { opacity: 1, transform: "translate3d(0, 0px, 0)" },
    keys: (item) => item.id,
    config: { tension: 220, friction: 20 },
  });

  useLayoutEffect(() => {
    const container = messagesContainerRef.current;
    const question = latestQuestionRef.current;
    if (!container || !question) return;

    const reserveAnswerSpace = () => {
      const padding = 30;
      const gap = 18;
      container.style.setProperty(
        "--current-answer-min-height",
        `${Math.max(0, container.clientHeight - question.offsetHeight - padding - gap)}px`,
      );
    };
    reserveAnswerSpace();
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    container.scrollTo({
      top: question.offsetTop - 18,
      behavior: reduceMotion ? "instant" : "smooth",
    });

    const observer = new ResizeObserver(reserveAnswerSpace);
    observer.observe(container);
    observer.observe(question);
    return () => observer.disconnect();
  }, [latestQuestion]);

  if (!videoHash) {
    return (
      <div className="flex items-center justify-center h-full p-8">
        <div className="text-center" style={{ color: "var(--text-secondary)" }}>
          <svg
            className="w-16 h-16 mx-auto mb-4"
            style={{ color: "var(--text-tertiary)" }}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z"
            />
          </svg>
          <p className="text-lg font-medium">No video loaded</p>
          <p className="text-sm mt-2">
            Upload and transcribe a video to start chatting
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full" style={{ background: "var(--bg-surface)" }}>
      {/* Chat Header — spark + title */}
      <div className="chat-head">
        <div className="spark" aria-hidden="true">
          <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round"
              d="M12 2v4m6.364.636l-2.828 2.828M22 12h-4m-.636 6.364l-2.828-2.828M12 22v-4m-6.364-.636l2.828-2.828M2 12h4m.636-6.364l2.828 2.828" />
          </svg>
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <h3>Ask this transcript anything</h3>
          <p>Every answer cites the exact moment in the video — click to jump there.</p>
        </div>
      </div>

      <ChatSettingsPanel
        chatProviders={chatProviders}
        includeVisuals={includeVisuals}
        setIncludeVisuals={setIncludeVisuals}
        handleReindex={handleReindex}
        reindexing={reindexing}
      />

      <ChatStatusBanners reindexStatus={reindexStatus} indexingStatus={indexingStatus} />

      {/* Messages */}
      <div
        ref={messagesContainerRef}
        className="flex-1 overflow-y-auto"
        style={{ padding: "18px 16px 12px", display: "flex", flexDirection: "column", gap: "18px", position: "relative", overflowAnchor: "none" }}
      >
        {messages.length === 0 && <ChatSuggestions sendMessage={sendMessage} />}

        {messageTransitions((style, message) => (
          <animated.div
            ref={message === latestQuestion ? latestQuestionRef : undefined}
            style={{
              ...style,
              flexShrink: 0,
              minHeight: message.role === "assistant" && message === messages[messages.length - 1]
                ? "var(--current-answer-min-height, 0px)"
                : undefined,
            }}
            className={`msg ${message.role === "user" ? "user" : "ai"}`}
          >
            <ChatMessage
              message={message}
              phases={message.isStreaming ? phases : null}
              screenshotCount={message.isStreaming ? screenshotCount : 0}
              onRetry={retryMessage}
              onSwapFrame={swapComparisonFrame}
              onDismissSwapError={dismissSwapError}
              setScreenshotModal={setScreenshotModal}
              onTimestampClick={onTimestampClick}
              jobId={jobId}
              accessToken={accessToken}
            />
          </animated.div>
        ))}
      </div>

      {/* Input */}
      <ChatComposer
        input={input}
        setInput={setInput}
        loading={loading}
        customInstructions={customInstructions}
        setCustomInstructions={setCustomInstructions}
        onSend={() => sendMessage(input)}
        messagesContainerRef={messagesContainerRef}
        videoHash={videoHash}
        transcriptSpeakers={transcriptSpeakers}
      />

      {/* Screenshot Modal with Slideshow */}
      {screenshotModal && (
        <ScreenshotModal
          screenshotModal={screenshotModal}
          setScreenshotModal={setScreenshotModal}
          onTimestampClick={onTimestampClick}
        />
      )}
    </div>
  );
};

export const ChatPanel = memo(ChatPanelInner);
