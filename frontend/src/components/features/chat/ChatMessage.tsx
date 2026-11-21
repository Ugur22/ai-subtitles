import { memo } from "react";
import type { Dispatch, SetStateAction } from "react";
import { AssistantMessageContent } from "./AssistantMessageContent";
import { ErrorMessageDisplay } from "./ErrorMessageDisplay";
import { MessageSources } from "./MessageSources";
import { PhaseIndicator } from "./PhaseIndicator";
import type { Message, PersonComparisonData, PhaseEntry, ScreenshotModalState, TimelineFrame } from "./types";

interface ChatMessageProps {
  message: Message;
  streamingProgress: { phases: PhaseEntry[]; screenshotCount: number } | null;
  onRetry: (question: string) => void;
  onSwapFrame: (
    messageId: string,
    originalQuestion: string | undefined,
    meta: PersonComparisonData,
    frame: TimelineFrame,
    target: "a" | "b",
  ) => void;
  onDismissSwapError: (messageId: string) => void;
  setScreenshotModal: Dispatch<SetStateAction<ScreenshotModalState | null>>;
  onTimestampClick?: (timeString: string) => void;
  jobId?: string | null;
  accessToken?: string;
}

export const ChatMessage = memo(function ChatMessage({
  message,
  streamingProgress,
  onRetry,
  onSwapFrame,
  onDismissSwapError,
  setScreenshotModal,
  onTimestampClick,
  jobId,
  accessToken,
}: ChatMessageProps) {

  return (
    <div className="msg-col">
    {message.role === "assistant" &&
      ((message.visual_query_variants &&
        message.visual_query_variants.length > 0) ||
        (message.visual_query_used &&
          message.original_question &&
          message.visual_query_used !== message.original_question)) && (
        <div
          className="px-3 py-2 rounded-lg text-xs flex items-start gap-2 border"
          style={{ background: "var(--bg-overlay)", borderColor: "var(--border-subtle)", color: "var(--text-secondary)" }}
        >
          <svg className="w-4 h-4 flex-shrink-0 mt-px" style={{ color: "var(--accent)" }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
          </svg>
          <div className="min-w-0">
            <span className="font-medium" style={{ color: "var(--text-primary)" }}>
              Searched scenes:
            </span>
            {message.visual_query_variants &&
            message.visual_query_variants.length > 0 ? (
              <div className="mt-1 flex flex-wrap gap-1">
                {message.visual_query_variants.slice(0, 5).map((variant) => (
                  <span
                    key={variant}
                    className="rounded-full px-2 py-0.5"
                    style={{
                      background: "var(--accent-dim)",
                      color: "var(--accent)",
                    }}
                  >
                    {variant}
                  </span>
                ))}
              </div>
            ) : (
              <span> "{message.visual_query_used}"</span>
            )}
          </div>
        </div>
      )}

    <div
      className={
        message.isError && !message.sources?.length
          ? "msg-bubble is-error"
          : "msg-bubble"
      }
    >
      {message.isError ? (
        <ErrorMessageDisplay
          message={message}
          onRetry={onRetry}
        />
      ) : (
        <>
          {streamingProgress && (
            <PhaseIndicator phases={streamingProgress.phases} screenshotCount={streamingProgress.screenshotCount} />
          )}
          {message.content && (
            <AssistantMessageContent
              content={message.content}
              role={message.role}
              onTimestampClick={onTimestampClick}
              onOpenScreenshots={(sources, currentIndex) => {
                setScreenshotModal({ currentIndex, sources });
              }}
              isSwapping={message.isSwapping}
              pendingBSeconds={message.pendingBSeconds}
              pendingSwapTarget={message.pendingSwapTarget}
              swapError={message.swapError}
              onSwapFrame={
                message.role === "assistant"
                  ? (meta, frame, target) => onSwapFrame(message.id, message.original_question, meta, frame, target)
                  : undefined
              }
              onDismissSwapError={() => onDismissSwapError(message.id)}
            />
          )}
          {message.role === "assistant" &&
            message.isStreaming &&
            message.content && (
              <span
                aria-hidden="true"
                className="inline-block align-middle ml-0.5 animate-pulse"
                style={{
                  width: "0.55rem",
                  height: "1em",
                  background: "var(--accent)",
                  borderRadius: "1px",
                  marginBottom: "-0.1em",
                }}
              />
            )}
        </>
      )}

              <MessageSources
                message={message}
                setScreenshotModal={setScreenshotModal}
                onTimestampClick={onTimestampClick}
                jobId={jobId}
                accessToken={accessToken}
              />
    </div>
    </div>
  );
});
