import { useRef, useState } from "react";
import type { RefObject } from "react";
import { isEditableTarget } from "../../../utils/dom";
import { useSpeakerMentions } from "./hooks/useSpeakerMentions";
import { getMentionContext } from "./mentions";

interface ChatComposerProps {
  input: string;
  setInput: (value: string) => void;
  loading: boolean;
  customInstructions: string;
  setCustomInstructions: (value: string) => void;
  onSend: () => void;
  messagesContainerRef: RefObject<HTMLDivElement | null>;
  videoHash: string | null;
  transcriptSpeakers: string[];
}

export const ChatComposer: React.FC<ChatComposerProps> = ({
  input,
  setInput,
  loading,
  customInstructions,
  setCustomInstructions,
  onSend,
  messagesContainerRef,
  videoHash,
  transcriptSpeakers,
}) => {
  const [showCustomInstructions, setShowCustomInstructions] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const {
    showMentions,
    setShowMentions,
    setMentionFilter,
    mentionIndex,
    setMentionIndex,
    filteredSpeakers,
  } = useSpeakerMentions(videoHash, transcriptSpeakers);

  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const messagesContainer = messagesContainerRef.current;
    const previousScrollTop = messagesContainer?.scrollTop ?? 0;
    const wasPinnedToBottom = messagesContainer
      ? messagesContainer.scrollHeight -
          messagesContainer.scrollTop -
          messagesContainer.clientHeight <=
        8
      : false;

    const value = e.target.value;
    setInput(value);
    const cursorPos = e.target.selectionStart || value.length;
    const ctx = getMentionContext(value, cursorPos);
    if (ctx) {
      setShowMentions(true);
      setMentionFilter(ctx.filter);
      setMentionIndex(0);
    } else {
      setShowMentions(false);
    }
    const el = e.target;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 120) + "px";

    if (messagesContainer) {
      requestAnimationFrame(() => {
        if (wasPinnedToBottom) {
          messagesContainer.scrollTop = messagesContainer.scrollHeight;
        } else {
          messagesContainer.scrollTop = previousScrollTop;
        }
      });
    }
  };

  const selectMention = (speaker: string) => {
    const el = inputRef.current;
    const cursorPos = el?.selectionStart || input.length;
    const ctx = getMentionContext(input, cursorPos);
    if (ctx) {
      const before = input.slice(0, ctx.start);
      const after = input.slice(cursorPos);
      const newValue = before + speaker + " " + after;
      setInput(newValue);
      setShowMentions(false);
      setTimeout(() => {
        el?.focus();
        const pos = before.length + speaker.length + 1;
        el?.setSelectionRange(pos, pos);
      }, 0);
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    e.stopPropagation();

    if (showMentions && filteredSpeakers.length > 0) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setMentionIndex((i) => Math.min(i + 1, filteredSpeakers.length - 1));
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setMentionIndex((i) => Math.max(i - 1, 0));
        return;
      }
      if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        selectMention(filteredSpeakers[mentionIndex]);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setShowMentions(false);
        return;
      }
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      onSend();
    }
  };

  return (
    <div className="composer">
      <div className="mb-3">
        <button
          onClick={() => setShowCustomInstructions(!showCustomInstructions)}
          className="flex items-center gap-2 text-sm font-medium transition-colors"
          style={{ color: "var(--text-secondary)" }}
          aria-expanded={showCustomInstructions}
          aria-label="Toggle custom instructions"
        >
          <svg
            className={`w-4 h-4 transition-transform ${showCustomInstructions ? "rotate-90" : ""}`}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M9 5l7 7-7 7"
            />
          </svg>
          <svg
            className="w-4 h-4"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"
            />
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"
            />
          </svg>
          <span>Custom instructions</span>
          {customInstructions && (
            <span className="badge badge-accent ml-1">
              Active
            </span>
          )}
        </button>

        {showCustomInstructions && (
          <div className="mt-3 rounded-lg border p-3" style={{ background: "var(--bg-surface)", borderColor: "var(--border-default)" }}>
            <textarea
              value={customInstructions}
              onChange={(e) => setCustomInstructions(e.target.value)}
              onKeyDown={(e) => {
                if (isEditableTarget(e.target)) e.stopPropagation();
              }}
              onKeyUp={(e) => e.stopPropagation()}
              onKeyPress={(e) => e.stopPropagation()}
              placeholder="For example: respond in Spanish, keep it brief, focus on technical details"
              className="input-base w-full px-3 py-2 resize-none text-sm"
              rows={3}
              disabled={loading}
            />
            <p className="mt-2 text-xs" style={{ color: "var(--text-tertiary)" }}>
              These instructions will be applied to all your questions. They
              persist across messages.
            </p>
          </div>
        )}
      </div>

      <div className="relative">
        {showMentions && filteredSpeakers.length > 0 && (
          <div className="absolute bottom-full mb-1 left-0 w-64 rounded-lg shadow-lg max-h-48 overflow-y-auto z-50 border" style={{ background: "var(--bg-overlay)", borderColor: "var(--border-default)" }}>
            {filteredSpeakers.map((speaker, i) => (
              <button
                key={speaker}
                className="w-full text-left px-3 py-2 text-sm transition-colors"
                style={
                  i === mentionIndex
                    ? { background: "var(--accent-dim)", color: "var(--accent)" }
                    : { color: "var(--text-primary)" }
                }
                onMouseDown={(e) => {
                  e.preventDefault();
                  selectMention(speaker);
                }}
              >
                <span className="mr-1" style={{ color: "var(--text-tertiary)" }}>@</span>
                {speaker}
              </button>
            ))}
          </div>
        )}
        <div className="composer-box">
          <textarea
            ref={inputRef}
            rows={1}
            value={input}
            onChange={handleInputChange}
            onKeyDown={handleKeyPress}
            onKeyUp={(e) => e.stopPropagation()}
            onKeyPress={(e) => e.stopPropagation()}
            placeholder="Ask about this video"
            disabled={loading}
          />
          <div className="composer-row">
            <button
              onClick={onSend}
              disabled={loading || !input.trim()}
              className="send-btn"
              aria-label="Send"
              title="Send message"
            >
              <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 19V5m0 0l-7 7m7-7l7 7" />
              </svg>
            </button>
          </div>
        </div>
      </div>
      <div className="composer-foot">
        <div className="tips-k">
          <span><span className="kbd">↵</span> send</span>
          <span><span className="kbd">⇧</span>+<span className="kbd">↵</span> new line</span>
          <span><span className="kbd">@</span> speaker</span>
        </div>
        <span>Answers cite the original audio — not trained knowledge.</span>
      </div>
    </div>
  );
};
