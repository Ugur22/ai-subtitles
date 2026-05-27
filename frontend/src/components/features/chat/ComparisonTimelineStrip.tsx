import { useEffect, useMemo, useRef } from "react";
import { formatScreenshotUrlSafe } from "../../../utils/url";

export interface TimelineFrame {
  url: string;
  timestamp: string;
  timestamp_seconds: number;
  bbox?: { x: number; y: number; w: number; h: number } | null;
  similarity?: number;
}

interface ComparisonTimelineStripProps {
  frames: TimelineFrame[];
  activeASeconds: number;
  activeBSeconds: number;
  person: string;
  isSwapping: boolean;
  pendingBSeconds: number | null;
  replaceTarget: "a" | "b";
  swapError?: string;
  onReplaceTargetChange: (target: "a" | "b") => void;
  onSwap: (frame: TimelineFrame, target: "a" | "b") => void;
  onDismissError?: () => void;
}

const ACTIVE_TOLERANCE_SECONDS = 0.5;

const imagePlaceholderSrc =
  "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='100' height='100'%3E%3Crect fill='%23f3f4f6' width='100' height='100'/%3E%3Ctext x='50%25' y='50%25' dominant-baseline='middle' text-anchor='middle' fill='%239ca3af' font-size='12'%3ENo Image%3C/text%3E%3C/svg%3E";

function isSameMoment(a: number, b: number): boolean {
  return Math.abs(a - b) < ACTIVE_TOLERANCE_SECONDS;
}

export const ComparisonTimelineStrip: React.FC<ComparisonTimelineStripProps> = ({
  frames,
  activeASeconds,
  activeBSeconds,
  person,
  isSwapping,
  pendingBSeconds,
  replaceTarget,
  swapError,
  onReplaceTargetChange,
  onSwap,
  onDismissError,
}) => {
  const listRef = useRef<HTMLOListElement | null>(null);
  const itemRefs = useRef<Array<HTMLButtonElement | null>>([]);

  const focusableIndex = useMemo(() => {
    // Roving tabindex: first index that is neither the current A nor B frame.
    for (let i = 0; i < frames.length; i++) {
      const t = frames[i].timestamp_seconds;
      const blocked = isSameMoment(t, activeASeconds) || isSameMoment(t, activeBSeconds);
      if (!blocked) {
        return i;
      }
    }
    return 0;
  }, [frames, activeASeconds, activeBSeconds, replaceTarget]);

  useEffect(() => {
    const list = listRef.current;
    if (!list) return;
    const activeIdx = frames.findIndex((f) => isSameMoment(f.timestamp_seconds, activeBSeconds));
    if (activeIdx < 0) return;
    const node = itemRefs.current[activeIdx];
    if (node && typeof node.scrollIntoView === "function") {
      node.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "center" });
    }
  }, [frames, activeBSeconds]);

  const handleKeyDown = (event: React.KeyboardEvent<HTMLOListElement>) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    const focused = document.activeElement;
    const currentIdx = itemRefs.current.findIndex((n) => n === focused);
    if (currentIdx < 0) return;
    event.preventDefault();
    const dir = event.key === "ArrowRight" ? 1 : -1;
    let nextIdx = currentIdx + dir;
    while (nextIdx >= 0 && nextIdx < frames.length) {
      const t = frames[nextIdx].timestamp_seconds;
      const inert = isSameMoment(t, activeASeconds) || isSameMoment(t, activeBSeconds);
      if (!inert) break;
      nextIdx += dir;
    }
    if (nextIdx < 0 || nextIdx >= frames.length) return;
    const target = itemRefs.current[nextIdx];
    if (target) target.focus();
  };

  if (!frames || frames.length === 0) return null;

  return (
    <div className="mt-3">
      {swapError && (
        <div
          role="alert"
          className="mb-2 flex items-start gap-2 rounded-md border px-3 py-2 text-[12px]"
          style={{
            borderColor: "rgba(239, 68, 68, 0.4)",
            background: "rgba(239, 68, 68, 0.08)",
            color: "var(--text-primary)",
          }}
        >
          <svg
            aria-hidden
            className="mt-0.5 h-4 w-4 flex-shrink-0"
            fill="currentColor"
            viewBox="0 0 20 20"
            style={{ color: "#ef4444" }}
          >
            <path
              fillRule="evenodd"
              d="M18 10A8 8 0 11 2 10a8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z"
              clipRule="evenodd"
            />
          </svg>
          <span className="flex-1">{swapError}</span>
          {onDismissError && (
            <button
              type="button"
              onClick={onDismissError}
              className="rounded px-1 text-[11px] font-semibold uppercase tracking-wide hover:opacity-80"
              aria-label="Dismiss error"
            >
              Dismiss
            </button>
          )}
        </div>
      )}

      <div
        className="flex items-center justify-between gap-2 px-0.5 pb-1.5 text-[11px]"
        style={{ color: "var(--text-tertiary)" }}
      >
        <span className="font-medium uppercase tracking-wider">
          Other moments of {person}
        </span>
        <div className="flex items-center gap-2">
          <div
            className="inline-flex rounded-full border p-0.5"
            style={{ borderColor: "var(--border-subtle)", background: "var(--bg-overlay)" }}
            aria-label="Choose comparison frame to replace"
          >
            {(["a", "b"] as const).map((target) => (
              <button
                key={target}
                type="button"
                onClick={() => onReplaceTargetChange(target)}
                className="rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase transition-colors"
                style={{
                  background: replaceTarget === target ? "var(--accent-dim)" : "transparent",
                  color: replaceTarget === target ? "var(--accent)" : "var(--text-tertiary)",
                }}
              >
                Replace {target.toUpperCase()}
              </button>
            ))}
          </div>
          <span aria-hidden>{frames.length} frames</span>
        </div>
      </div>

      <ol
        ref={listRef}
        role="listbox"
        aria-label={`Alternate Frame B candidates for ${person}`}
        onKeyDown={handleKeyDown}
        className="flex gap-2 overflow-x-auto pb-2"
        style={{
          scrollSnapType: "x mandatory",
          scrollbarWidth: "thin",
        }}
      >
        {frames.map((frame, idx) => {
          const isA = isSameMoment(frame.timestamp_seconds, activeASeconds);
          const isCurrentB = isSameMoment(frame.timestamp_seconds, activeBSeconds);
          const isPending =
            pendingBSeconds != null &&
            isSameMoment(frame.timestamp_seconds, pendingBSeconds);
          const inert = isA || isCurrentB;
          const disabledByLock = isSwapping && !isPending && !inert;
          const ring = isA
            ? "var(--accent)"
            : isCurrentB
              ? "#f59e0b"
              : isPending
                ? "var(--accent)"
                : "transparent";
          const label = isA ? "A" : isCurrentB ? "B" : null;

          return (
            <li
              key={`${frame.url}-${frame.timestamp_seconds}-${idx}`}
              role="option"
              aria-selected={isCurrentB || isPending}
              className="shrink-0"
              style={{ scrollSnapAlign: "start" }}
            >
              <button
                type="button"
                ref={(el) => {
                  itemRefs.current[idx] = el;
                }}
                tabIndex={idx === focusableIndex ? 0 : -1}
                onClick={() => {
                  if (inert || disabledByLock) return;
                  onSwap(frame, replaceTarget);
                }}
                disabled={inert || disabledByLock}
                aria-disabled={inert || disabledByLock}
                aria-current={isCurrentB ? "true" : undefined}
                title={
                  isA
                    ? replaceTarget === "a"
                      ? `Current Frame A at ${frame.timestamp}`
                      : `Frame A (anchor) at ${frame.timestamp}`
                    : isCurrentB
                      ? replaceTarget === "b"
                        ? `Current Frame B at ${frame.timestamp}`
                        : `Frame B (locked while replacing A) at ${frame.timestamp}`
                      : `Replace Frame ${replaceTarget.toUpperCase()} with ${frame.timestamp}`
                }
                className={`relative block aspect-video w-24 overflow-hidden rounded-md border outline-none transition-transform focus-visible:ring-2 focus-visible:ring-emerald-500 ${
                  inert ? "cursor-default" : disabledByLock ? "cursor-not-allowed" : "cursor-pointer hover:scale-[1.03]"
                }`}
                style={{
                  borderColor: "var(--border-default)",
                  background: "var(--bg-overlay)",
                  boxShadow: ring !== "transparent" ? `0 0 0 2px ${ring}` : undefined,
                  opacity: disabledByLock ? 0.55 : 1,
                }}
              >
                <img
                  src={formatScreenshotUrlSafe(frame.url)}
                  alt={`${person} at ${frame.timestamp}`}
                  loading="lazy"
                  className="h-full w-full object-cover"
                  onError={(e) => {
                    e.currentTarget.src = imagePlaceholderSrc;
                  }}
                />
                {frame.bbox && (
                  <span
                    aria-hidden
                    className="absolute rounded-sm"
                    style={{
                      left: `${frame.bbox.x * 100}%`,
                      top: `${frame.bbox.y * 100}%`,
                      width: `${frame.bbox.w * 100}%`,
                      height: `${frame.bbox.h * 100}%`,
                      border: `1.5px solid ${isA ? "var(--accent)" : isCurrentB ? "#f59e0b" : "rgba(255,255,255,0.75)"}`,
                    }}
                  />
                )}

                {label && (
                  <span
                    className="absolute left-1 top-1 rounded-full bg-black/70 px-1.5 py-0 text-[10px] font-semibold text-white"
                    aria-hidden
                  >
                    {label}
                  </span>
                )}

                {isPending && (
                  <span
                    className="absolute inset-0 flex items-center justify-center"
                    style={{ background: "rgba(0,0,0,0.35)" }}
                  >
                    <svg
                      className="h-5 w-5 animate-spin text-white"
                      viewBox="0 0 24 24"
                      aria-hidden
                    >
                      <circle
                        cx="12"
                        cy="12"
                        r="9"
                        stroke="currentColor"
                        strokeWidth="3"
                        opacity="0.25"
                        fill="none"
                      />
                      <path
                        d="M21 12a9 9 0 00-9-9"
                        stroke="currentColor"
                        strokeWidth="3"
                        strokeLinecap="round"
                        fill="none"
                      />
                    </svg>
                  </span>
                )}

                {frame.similarity != null && frame.similarity >= 0.85 && !inert && !isPending && (
                  <span
                    aria-hidden
                    className="absolute bottom-1 right-1 h-1.5 w-1.5 rounded-full"
                    style={{ background: "var(--accent)" }}
                    title={`High confidence (${Math.round(frame.similarity * 100)}%)`}
                  />
                )}

                <span
                  className="absolute bottom-0 left-0 right-0 px-1 py-0.5 text-center font-mono text-[10px] font-semibold tabular-nums text-white"
                  style={{ background: "linear-gradient(0deg, rgba(0,0,0,0.7), rgba(0,0,0,0))" }}
                >
                  {frame.timestamp}
                </span>
              </button>
            </li>
          );
        })}
      </ol>
    </div>
  );
};

export default ComparisonTimelineStrip;
