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
      <div className="px-5 py-4 border-b border-gray-200 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <svg
            className="w-4 h-4 text-indigo-500"
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
          <h3 className="text-sm font-semibold text-gray-800">Chapters</h3>
          {chapters.length > 0 && (
            <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-indigo-100 text-indigo-700">
              {chapters.length}
            </span>
          )}
        </div>
        <button
          onClick={onGenerate}
          disabled={loading}
          className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all duration-200 flex items-center gap-1.5 ${
            loading
              ? "bg-gray-100 text-gray-400 cursor-not-allowed"
              : "bg-gradient-to-r from-indigo-500 to-purple-600 text-white shadow-sm hover:shadow-md hover:from-indigo-600 hover:to-purple-700"
          }`}
        >
          {loading ? (
            <>
              <svg
                className="animate-spin h-3 w-3"
                xmlns="http://www.w3.org/2000/svg"
                fill="none"
                viewBox="0 0 24 24"
              >
                <circle
                  className="opacity-25"
                  cx="12"
                  cy="12"
                  r="10"
                  stroke="currentColor"
                  strokeWidth="4"
                />
                <path
                  className="opacity-75"
                  fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                />
              </svg>
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
          <div className="p-3 bg-red-50 border-l-4 border-red-400 text-red-700 text-sm rounded-md mb-4">
            {error}
          </div>
        )}

        {/* Loading skeleton */}
        {loading && chapters.length === 0 && (
          <div className="space-y-3">
            {Array.from({ length: 4 }).map((_, i) => (
              <div
                key={i}
                className="animate-pulse rounded-lg border border-gray-100 p-3"
              >
                <div className="h-4 bg-gray-200 rounded w-3/4 mb-2" />
                <div className="h-3 bg-gray-100 rounded w-1/3 mb-2" />
                <div className="h-3 bg-gray-100 rounded w-full" />
              </div>
            ))}
          </div>
        )}

        {/* Empty state */}
        {!loading && chapters.length === 0 && !error && (
          <div className="py-12 text-center">
            <svg
              className="mx-auto h-12 w-12 text-gray-300"
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
            <p className="mt-3 text-sm text-gray-500">No chapters yet</p>
            <p className="mt-1 text-xs text-gray-400">
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
                  className="w-full text-left rounded-lg border border-gray-200 p-3 hover:border-indigo-300 hover:bg-indigo-50/50 transition-all duration-150 group"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-indigo-100 text-indigo-700 text-xs font-bold flex-shrink-0">
                          {index + 1}
                        </span>
                        <h4 className="text-sm font-semibold text-gray-900 truncate group-hover:text-indigo-700 transition-colors">
                          {chapter.title}
                        </h4>
                      </div>
                      <p className="text-xs text-gray-500 line-clamp-2 ml-7">
                        {chapter.summary}
                      </p>
                    </div>
                    <div className="flex flex-col items-end flex-shrink-0 gap-0.5">
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-orange-100 text-orange-800 group-hover:bg-orange-200 transition-colors">
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
                      <span className="text-[10px] text-gray-400">
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
