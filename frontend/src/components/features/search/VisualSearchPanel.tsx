import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  searchImages,
  indexImages,
  ImageSearchResult,
} from "../../../services/api";
import { formatScreenshotUrlSafe } from "../../../utils/url";

interface VisualSearchPanelProps {
  onSeekToTimestamp?: (timestamp: string) => void;
  onImageClick?: (url: string) => void;
  videoHash?: string;
}

const formatSeconds = (seconds: number): string => {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  const hh = h.toString().padStart(2, "0");
  const mm = m.toString().padStart(2, "0");
  const ss = s.toString().padStart(2, "0");
  return `${hh}:${mm}:${ss}`;
};

const LoadingSkeleton = () => (
  <div className="mt-4 grid grid-cols-2 gap-2">
    {Array.from({ length: 6 }).map((_, i) => (
      <div
        key={i}
        className="rounded-md overflow-hidden bg-gray-100 animate-pulse"
      >
        <div className="w-full aspect-video bg-gray-200" />
        <div className="p-1.5 space-y-1">
          <div className="h-3 bg-gray-200 rounded w-16" />
          <div className="h-3 bg-gray-200 rounded w-10" />
        </div>
      </div>
    ))}
  </div>
);

interface ThumbnailProps {
  result: ImageSearchResult;
  onSeekToTimestamp?: (timestamp: string) => void;
  onImageClick?: (url: string) => void;
}

const Thumbnail = ({ result, onSeekToTimestamp, onImageClick }: ThumbnailProps) => {
  const imageUrl = formatScreenshotUrlSafe(result.screenshot_path);
  const timestamp = formatSeconds(result.start);

  const handleTimestampClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (onSeekToTimestamp) {
      onSeekToTimestamp(timestamp);
    }
  };

  const handleImageClick = () => {
    if (onImageClick && imageUrl) {
      onImageClick(imageUrl);
    }
  };

  return (
    <div className="rounded-md overflow-hidden border border-gray-200 bg-gray-50 hover:border-violet-400 transition-colors group">
      <div
        className="relative cursor-pointer overflow-hidden aspect-video bg-gray-100"
        onClick={handleImageClick}
        role="button"
        aria-label={`Open screenshot at ${timestamp}`}
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            handleImageClick();
          }
        }}
      >
        {imageUrl ? (
          <img
            src={imageUrl}
            alt={`Screenshot at ${timestamp}`}
            className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-200"
            loading="lazy"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center">
            <svg
              className="h-8 w-8 text-gray-300"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.5}
                d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"
              />
            </svg>
          </div>
        )}
      </div>
      <div className="p-1.5 space-y-0.5">
        <button
          onClick={handleTimestampClick}
          className={`inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-xs font-medium ${
            onSeekToTimestamp
              ? "bg-orange-100 text-orange-800 hover:bg-orange-200 cursor-pointer"
              : "bg-gray-100 text-gray-700"
          }`}
          aria-label={`Seek to ${timestamp}`}
        >
          <svg className="w-2.5 h-2.5" viewBox="0 0 20 20" fill="currentColor">
            <path
              fillRule="evenodd"
              d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-12a1 1 0 10-2 0v4a1 1 0 00.293.707l2.828 2.829a1 1 0 101.415-1.415L11 9.586V6z"
              clipRule="evenodd"
            />
          </svg>
          {timestamp}
        </button>
        {result.speaker && (
          <div className="text-xs text-gray-500 truncate px-0.5">
            {result.speaker}
          </div>
        )}
      </div>
    </div>
  );
};

export const VisualSearchPanel = ({
  onSeekToTimestamp,
  onImageClick,
  videoHash,
}: VisualSearchPanelProps) => {
  const [searchQuery, setSearchQuery] = useState("");
  const [indexingError, setIndexingError] = useState<string | null>(null);

  const searchMutation = useMutation({
    mutationFn: async (query: string) => {
      // Attempt search; if the index is missing the backend may return an empty
      // result set. We proactively index before the first search when we have a
      // videoHash so the user doesn't need a separate "index" step.
      if (videoHash) {
        try {
          await indexImages(videoHash);
        } catch (err) {
          // Non-fatal: indexing may have already been done, or the video may not
          // have screenshots yet. Continue to search regardless.
          console.warn("[VisualSearch] indexImages failed (non-fatal):", err);
        }
      }
      return searchImages(query, videoHash, 12);
    },
    onError: (error) => {
      console.error("[VisualSearch] Search failed:", error);
      setIndexingError(null);
    },
    retry: false,
  });

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (searchQuery.trim()) {
      setIndexingError(null);
      searchMutation.mutate(searchQuery);
    }
  };

  return (
    <div>
      <form onSubmit={handleSearch} className="space-y-3">
        <div className="relative w-full">
          <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
            <svg
              className="h-5 w-5 text-gray-400"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z"
              />
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M15 13a3 3 0 11-6 0 3 3 0 016 0z"
              />
            </svg>
          </div>
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search screenshots... (e.g., 'person at whiteboard')"
            className="block w-full pl-10 pr-3 py-2 border border-gray-300 rounded-md leading-5 bg-white placeholder-gray-500 focus:outline-none focus:ring-violet-500 focus:border-violet-500 sm:text-sm"
          />
        </div>
        <button
          type="submit"
          disabled={searchMutation.isPending || !searchQuery.trim()}
          className="w-full btn-primary py-2.5 bg-violet-500 text-gray-900 rounded-md hover:bg-violet-600 transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
        >
          {searchMutation.isPending ? (
            <>
              <svg
                className="animate-spin -ml-1 mr-2 h-4 w-4 text-gray-900 inline-block"
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
              Searching...
            </>
          ) : (
            "Search"
          )}
        </button>
      </form>

      {/* Loading skeleton */}
      {searchMutation.isPending && <LoadingSkeleton />}

      {/* Results */}
      {searchMutation.isSuccess && !searchMutation.isPending && (
        <div className="mt-4">
          <div className="flex items-center mb-3">
            <h4 className="text-sm font-medium text-gray-900">
              Visual Results
            </h4>
            <span className="ml-2 px-2 py-0.5 rounded-full text-xs font-medium bg-orange-100 text-orange-800">
              {searchMutation.data.results.length} found
            </span>
          </div>

          {searchMutation.data.results.length > 0 ? (
            <div className="grid grid-cols-2 gap-2 max-h-[400px] overflow-y-auto pr-0.5">
              {searchMutation.data.results.map((result, index) => (
                <Thumbnail
                  key={`${result.segment_id}-${index}`}
                  result={result}
                  onSeekToTimestamp={onSeekToTimestamp}
                  onImageClick={onImageClick}
                />
              ))}
            </div>
          ) : (
            <div className="py-8 text-center">
              <svg
                className="mx-auto h-12 w-12 text-gray-300"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={1.5}
                  d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"
                />
              </svg>
              <p className="mt-2 text-sm text-gray-500">
                No matching screenshots found. Try a different description.
              </p>
            </div>
          )}
        </div>
      )}

      {/* Empty / initial state */}
      {!searchMutation.isSuccess && !searchMutation.isPending && !searchMutation.isError && (
        <div className="mt-8 py-6 text-center">
          <svg
            className="mx-auto h-12 w-12 text-gray-300"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={1.5}
              d="M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z"
            />
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={1.5}
              d="M15 13a3 3 0 11-6 0 3 3 0 016 0z"
            />
          </svg>
          <p className="mt-2 text-sm text-gray-500">
            Search for visual content in your video
          </p>
          <p className="mt-1 text-xs text-gray-400">
            Powered by CLIP semantic image search
          </p>
        </div>
      )}

      {/* Error state */}
      {searchMutation.isError && (
        <div className="mt-4 p-3 bg-red-50 border-l-4 border-red-400 text-red-700 text-sm rounded-md">
          Search failed. Please try again with a different description.
        </div>
      )}

      {indexingError && (
        <div className="mt-4 p-3 bg-yellow-50 border-l-4 border-yellow-400 text-yellow-700 text-sm rounded-md">
          {indexingError}
        </div>
      )}
    </div>
  );
};
