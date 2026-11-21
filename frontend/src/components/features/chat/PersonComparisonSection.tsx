import { useState } from "react";
import ReactMarkdown, { Components } from "react-markdown";
import { ComparisonTimelineStrip } from "./ComparisonTimelineStrip";
import { parsePersonComparisonSection } from "./answerSections";
import { getSectionIcon } from "./markdown";
import { imagePlaceholderSrc } from "./screenshots";
import { formatScreenshotUrlSafe } from "../../../utils/url";
import { formatSecondsToTimestamp } from "./timestamps";
import type { ComparisonFrame, PersonComparisonData, Source, TimelineFrame } from "./types";

const MIN_TIMELINE_FRAMES_FOR_STRIP = 3;

export const PersonComparisonSection: React.FC<{
  body: string;
  components: Components;
  onTimestampClick?: (ts: string) => void;
  onOpenScreenshots?: (sources: Source[], index: number) => void;
  isSwapping?: boolean;
  pendingBSeconds?: number | null;
  pendingSwapTarget?: "a" | "b" | null;
  swapError?: string;
  onSwapFrame?: (meta: PersonComparisonData, frame: TimelineFrame, target: "a" | "b") => void;
  onDismissSwapError?: () => void;
}> = ({
  body,
  components,
  onTimestampClick,
  onOpenScreenshots,
  isSwapping = false,
  pendingBSeconds = null,
  pendingSwapTarget = null,
  swapError,
  onSwapFrame,
  onDismissSwapError,
}) => {
  const { metadata, prose } = parsePersonComparisonSection(body);
  const [replaceTarget, setReplaceTarget] = useState<"a" | "b">("b");
  const frames = [metadata?.frame_a, metadata?.frame_b].filter(
    (frame): frame is ComparisonFrame => !!frame?.url,
  );
  const sources: Source[] = frames.map((frame, idx) => ({
    start_time:
      frame.timestamp ||
      formatSecondsToTimestamp(Number(frame.timestamp_seconds || 0)),
    end_time:
      frame.timestamp ||
      formatSecondsToTimestamp(Number(frame.timestamp_seconds || 0)),
    start: Number(frame.timestamp_seconds || 0),
    end: Number(frame.timestamp_seconds || 0),
    speaker: metadata?.person || "Person",
    screenshot_url: frame.url,
    type: "visual",
    evidence_label: frame.label || (idx === 0 ? "Earlier state" : "Later state"),
    source_kind: "person_comparison",
    bboxes: frame.bboxes?.length
      ? frame.bboxes
      : frame.bbox
        ? [{ person: metadata?.person, bbox: frame.bbox }]
        : undefined,
  }));

  const activeASeconds = Number(metadata?.frame_a?.timestamp_seconds || 0);
  const activeBSeconds = Number(metadata?.frame_b?.timestamp_seconds || 0);
  const timeline = metadata?.timeline || [];
  const showStrip =
    onSwapFrame !== undefined &&
    !!metadata?.frame_a &&
    !!metadata?.frame_b &&
    timeline.length >= MIN_TIMELINE_FRAMES_FOR_STRIP;

  return (
    <section className="my-3 border-y py-3" style={{ borderColor: "var(--border-subtle)" }}>
      <div className="mb-2 flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          {getSectionIcon("Person Comparison")}
          <h2 className="truncate text-sm font-medium" style={{ color: "var(--text-primary)" }}>
            Person comparison{metadata?.person ? `: ${metadata.person}` : ""}
          </h2>
        </div>
      </div>

      {frames.length === 2 && (
        <div className="grid gap-2.5 sm:grid-cols-2">
          {frames.map((frame, idx) => {
            const timestamp =
              frame.timestamp ||
              formatSecondsToTimestamp(Number(frame.timestamp_seconds || 0));
            const boxes = frame.bboxes?.length
              ? frame.bboxes
              : frame.bbox
                ? [{ person: metadata?.person, bbox: frame.bbox }]
                : [];
            const isPendingFrame =
              isSwapping &&
              ((idx === 0 && pendingSwapTarget === "a") ||
                (idx === 1 && (pendingSwapTarget === "b" || pendingSwapTarget == null)));
            return (
              <div
                key={`${frame.url}-${idx}`}
                className="group relative overflow-hidden rounded-lg border"
                style={{
                  borderColor: "var(--border-default)",
                  background: "var(--bg-overlay)",
                }}
              >
                {isPendingFrame && (
                  <div
                    aria-hidden
                    className="absolute left-0 right-0 top-0 z-10 h-0.5 overflow-hidden"
                  >
                    <div
                      className="h-full animate-pulse"
                      style={{ background: "var(--accent)", width: "100%" }}
                    />
                  </div>
                )}
                <button
                  type="button"
                  onClick={() => onOpenScreenshots?.(sources, idx)}
                  className="relative block aspect-video w-full overflow-hidden text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]"
                  title={`Open ${idx === 0 ? "first" : "second"} comparison frame at ${timestamp}`}
                  aria-label={`Open ${idx === 0 ? "first" : "second"} comparison frame at ${timestamp}`}
                >
                  <img
                    src={formatScreenshotUrlSafe(frame.url)}
                    alt={`${metadata?.person || "Person"} comparison frame at ${timestamp}`}
                    className="h-full w-full object-cover transition-opacity duration-150 group-hover:opacity-90"
                    loading="lazy"
                    onError={(e) => {
                      e.currentTarget.src = imagePlaceholderSrc;
                    }}
                  />
                  {boxes.map(({ person, bbox }, boxIdx) => bbox && (
                    <span
                      aria-label={person ? `${person} face box` : "Face box"}
                      title={person || "Face"}
                      key={`${person || "face"}-${boxIdx}`}
                      className="absolute rounded"
                      style={{
                        left: `${bbox.x * 100}%`,
                        top: `${bbox.y * 100}%`,
                        width: `${bbox.w * 100}%`,
                        height: `${bbox.h * 100}%`,
                        border: `2px solid ${boxIdx === 0 ? "var(--accent)" : "#f59e0b"}`,
                        boxShadow: boxIdx === 0 ? "0 0 0 9999px rgb(0 0 0 / 0.18)" : "none",
                      }}
                    />
                  ))}
                  <span className="img-label absolute left-2 top-2">
                    {idx === 0 ? "Frame A" : "Frame B"}
                  </span>
                </button>
                <div className="flex items-center justify-between gap-2 px-2 py-2">
                  <button
                    type="button"
                    onClick={() => onTimestampClick?.(timestamp)}
                    className="tc"
                    title={`Jump to ${timestamp}`}
                    aria-label={`Jump video to ${timestamp}`}
                  >
                    {timestamp}
                  </button>
                  <span className="truncate text-[11px]" style={{ color: "var(--text-tertiary)" }}>
                    {frame.label || (idx === 0 ? "Earlier state" : "Later state")}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {showStrip && metadata && (
        <ComparisonTimelineStrip
          frames={timeline}
          activeASeconds={activeASeconds}
          activeBSeconds={activeBSeconds}
          person={metadata.person || "Person"}
          isSwapping={isSwapping}
          pendingBSeconds={pendingBSeconds}
          replaceTarget={replaceTarget}
          swapError={swapError}
          onReplaceTargetChange={setReplaceTarget}
          onSwap={(frame, target) => onSwapFrame?.(metadata, frame, target)}
          onDismissError={onDismissSwapError}
        />
      )}

      {prose && (
        <div
          className="prose prose-sm mt-3 max-w-none transition-opacity"
          style={{ opacity: isSwapping ? 0.4 : 1 }}
        >
          <ReactMarkdown components={components}>{prose}</ReactMarkdown>
        </div>
      )}
    </section>
  );
};
