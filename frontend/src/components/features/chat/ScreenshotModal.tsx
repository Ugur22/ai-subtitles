import { useCallback, useEffect } from "react";
import { formatScreenshotUrlSafe } from "../../../utils/url";
import type { Dispatch, SetStateAction } from "react";
import { ComparisonModalFrame } from "./ComparisonModalFrame";
import type { ScreenshotModalState } from "./types";

interface ScreenshotModalProps {
  screenshotModal: ScreenshotModalState;
  setScreenshotModal: Dispatch<SetStateAction<ScreenshotModalState | null>>;
  onTimestampClick?: (timeString: string) => void;
}

export const ScreenshotModal: React.FC<ScreenshotModalProps> = ({
  screenshotModal,
  setScreenshotModal,
  onTimestampClick,
}) => {
  const screenshots = screenshotModal.sources.map((source) => formatScreenshotUrlSafe(source.screenshot_url));

  const step = useCallback((delta: number) => {
    setScreenshotModal((previous) => {
      if (!previous) return previous;
      const currentIndex = previous.currentIndex + delta;
      return currentIndex >= 0 && currentIndex < previous.sources.length ? { ...previous, currentIndex } : previous;
    });
  }, [setScreenshotModal]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setScreenshotModal(null);
      else if (e.key === "ArrowLeft") step(-1);
      else if (e.key === "ArrowRight") step(1);
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [step, setScreenshotModal]);

  const isComparisonModal =
    screenshotModal.sources.length === 2 &&
    screenshotModal.sources.every((source) => source.source_kind === "person_comparison");

  return (
    <div
      className="fixed inset-0 bg-black bg-opacity-90 z-50 flex items-center justify-center p-4"
      onClick={() => setScreenshotModal(null)}
    >
      <div
        className="relative max-w-6xl max-h-full"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          onClick={() => setScreenshotModal(null)}
          className="absolute top-2 right-2 z-10 w-10 h-10 rounded-full flex items-center justify-center transition-colors border"
          style={{
            background: 'var(--bg-overlay)',
            color: 'var(--text-primary)',
            borderColor: 'var(--border-subtle)',
          }}
          aria-label="Close screenshot"
        >
          <svg
            className="w-6 h-6"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M6 18L18 6M6 6l12 12"
            />
          </svg>
        </button>

        <div
          className="absolute top-2 left-2 z-10 px-3 py-1.5 text-xs font-mono tabular-nums rounded-full border"
          style={{
            background: 'var(--bg-overlay)',
            color: 'var(--text-primary)',
            borderColor: 'var(--border-subtle)',
          }}
        >
          {isComparisonModal
            ? "Comparison"
            : `${screenshotModal.currentIndex + 1} / ${screenshots.length}`}
        </div>

        {isComparisonModal ? (
          <div
            className="grid max-h-[88vh] w-[min(96vw,1500px)] gap-4 overflow-y-auto rounded-xl border p-4 lg:grid-cols-2"
            style={{
              background: "var(--bg-surface)",
              borderColor: "var(--border-subtle)",
            }}
          >
            {screenshotModal.sources.map((source, index) => (
              <ComparisonModalFrame
                key={`${source.screenshot_url}-${index}`}
                source={source}
                image={screenshots[index]}
                onTimestampClick={onTimestampClick}
              />
            ))}
          </div>
        ) : (
          <img
            src={screenshots[screenshotModal.currentIndex]}
            alt="Expanded screenshot"
            className="max-w-full max-h-[90vh] object-contain rounded-lg shadow-2xl"
          />
        )}

        {!isComparisonModal && screenshotModal.currentIndex > 0 && (
          <button
            onClick={() => step(-1)}
            className="absolute left-2 top-1/2 -translate-y-1/2 w-12 h-12 rounded-full flex items-center justify-center transition-opacity opacity-60 hover:opacity-100 border"
            style={{
              background: 'var(--bg-overlay)',
              color: 'var(--text-primary)',
              borderColor: 'var(--border-subtle)',
            }}
            aria-label="Previous image"
          >
            <svg
              className="w-6 h-6"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.5}
                d="M15 19l-7-7 7-7"
              />
            </svg>
          </button>
        )}

        {!isComparisonModal && screenshotModal.currentIndex <
          screenshots.length - 1 && (
          <button
            onClick={() => step(1)}
            className="absolute right-2 top-1/2 -translate-y-1/2 w-12 h-12 rounded-full flex items-center justify-center transition-opacity opacity-60 hover:opacity-100 border"
            style={{
              background: 'var(--bg-overlay)',
              color: 'var(--text-primary)',
              borderColor: 'var(--border-subtle)',
            }}
            aria-label="Next image"
          >
            <svg
              className="w-6 h-6"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.5}
                d="M9 5l7 7-7 7"
              />
            </svg>
          </button>
        )}

        {!isComparisonModal && screenshotModal.sources[screenshotModal.currentIndex] && (
          <div className="absolute bottom-2 left-1/2 -translate-x-1/2 px-4 py-2 bg-black bg-opacity-60 text-white rounded-lg backdrop-blur-sm text-center">
            <button
              onClick={() =>
                onTimestampClick?.(
                  screenshotModal.sources[screenshotModal.currentIndex]
                    .start_time,
                )
              }
              className="tc tc-on-image"
              title="Click to jump to this timestamp"
            >
              {
                screenshotModal.sources[screenshotModal.currentIndex]
                  .start_time
              }
            </button>
            {(screenshotModal.sources[screenshotModal.currentIndex]
              ?.likely_speakers?.length ?? 0) > 0 && (
              <p className="text-xs text-white/90 mt-1">
                Likely:{" "}
                {screenshotModal.sources[screenshotModal.currentIndex]?.likely_speakers?.join(", ")}
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
