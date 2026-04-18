import type { Chapter } from "../../../services/api";

interface ChapterPanelProps {
  chapters: Chapter[];
  loading: boolean;
  error: string | null;
  onGenerate: () => void;
  onSeekTo: (timestamp: string) => void;
}

const formatDuration = (seconds: number): string => {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  if (m === 0) return `${s}s`;
  return s > 0 ? `${m}m ${s}s` : `${m}m`;
};

export const ChapterPanel = ({
  chapters,
  loading,
  error,
  onGenerate,
  onSeekTo,
}: ChapterPanelProps) => {
  return (
    <div className="h-full flex flex-col">
      <div
        className="px-5 py-4 border-b flex items-center justify-between"
        style={{ borderColor: 'var(--border-subtle)' }}
      >
        <div className="flex items-center gap-2">
          <svg
            className="w-4 h-4"
            style={{ color: 'var(--accent)' }}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M4 6h16M4 10h16M4 14h16M4 18h16"
            />
          </svg>
          <h3
            className="text-sm font-semibold"
            style={{ color: 'var(--text-primary)' }}
          >
            Chapters
          </h3>
          {chapters.length > 0 && (
            <span className="badge badge-accent">{chapters.length}</span>
          )}
        </div>
        <button
          onClick={onGenerate}
          disabled={loading}
          className="btn-tonal flex items-center gap-1.5"
        >
          {loading ? (
            <>
              <span className="spinner" style={{ width: '0.75rem', height: '0.75rem', borderWidth: '1.5px' }} />
              Generating...
            </>
          ) : chapters.length > 0 ? (
            "Regenerate"
          ) : (
            "Generate"
          )}
        </button>
      </div>

      <div className="flex-grow overflow-auto p-4">
        {/* Error */}
        {error && (
          <div
            className="p-3 border-l-4 text-sm rounded-md mb-4"
            style={{
              background: 'oklch(65% 0.20 25 / 0.10)',
              borderColor: 'var(--c-error)',
              color: 'var(--c-error)',
            }}
          >
            {error}
          </div>
        )}

        {/* Loading skeleton */}
        {loading && chapters.length === 0 && (
          <div className="space-y-3">
            {Array.from({ length: 4 }).map((_, i) => (
              <div
                key={i}
                className="animate-pulse rounded-lg border p-3"
                style={{ borderColor: 'var(--border-subtle)' }}
              >
                <div
                  className="h-4 rounded w-3/4 mb-2"
                  style={{ background: 'var(--bg-subtle)' }}
                />
                <div
                  className="h-3 rounded w-1/3 mb-2"
                  style={{ background: 'var(--bg-base)' }}
                />
                <div
                  className="h-3 rounded w-full"
                  style={{ background: 'var(--bg-base)' }}
                />
              </div>
            ))}
          </div>
        )}

        {/* Empty state */}
        {!loading && chapters.length === 0 && !error && (
          <div className="empty-state">
            <svg
              className="empty-state-icon"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.5}
                d="M4 6h16M4 10h16M4 14h16M4 18h16"
              />
            </svg>
            <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>
              No chapters yet
            </p>
            <p className="mt-1 text-xs" style={{ color: 'var(--text-tertiary)' }}>
              Click Generate to create YouTube-style chapter markers
            </p>
          </div>
        )}

        {/* Chapter list */}
        {chapters.length > 0 && (
          <div className="space-y-2">
            {chapters.map((chapter, index) => {
              const duration = chapter.end - chapter.start;
              return (
                <button
                  key={index}
                  onClick={() => onSeekTo(chapter.start_time)}
                  className="w-full text-left rounded-lg border p-3 transition-colors duration-150 group hover:[background:var(--bg-subtle)]"
                  style={{ borderColor: 'var(--border-subtle)' }}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <span
                          className="inline-flex items-center justify-center w-5 h-5 rounded-full text-xs font-bold flex-shrink-0"
                          style={{
                            background: 'var(--accent-dim)',
                            color: 'var(--accent)',
                          }}
                        >
                          {index + 1}
                        </span>
                        <h4
                          className="text-sm font-semibold truncate transition-colors group-hover:[color:var(--accent)]"
                          style={{ color: 'var(--text-primary)' }}
                        >
                          {chapter.title}
                        </h4>
                      </div>
                      <p
                        className="text-xs line-clamp-2 ml-7"
                        style={{ color: 'var(--text-tertiary)' }}
                      >
                        {chapter.summary}
                      </p>
                    </div>
                    <div className="flex flex-col items-end flex-shrink-0 gap-0.5">
                      <span
                        className="badge badge-default font-mono tabular-nums inline-flex items-center gap-1"
                      >
                        <svg
                          className="w-2.5 h-2.5"
                          viewBox="0 0 20 20"
                          fill="currentColor"
                        >
                          <path
                            fillRule="evenodd"
                            d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-12a1 1 0 10-2 0v4a1 1 0 00.293.707l2.828 2.829a1 1 0 101.415-1.415L11 9.586V6z"
                            clipRule="evenodd"
                          />
                        </svg>
                        {chapter.start_time}
                      </span>
                      <span
                        className="text-[10px]"
                        style={{ color: 'var(--text-tertiary)' }}
                      >
                        {formatDuration(duration)}
                      </span>
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
};
