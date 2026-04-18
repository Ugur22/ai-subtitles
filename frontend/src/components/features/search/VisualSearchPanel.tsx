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
        className="rounded-md overflow-hidden animate-pulse"
        style={{ background: 'var(--bg-subtle)' }}
      >
        <div className="w-full aspect-video" style={{ background: 'var(--bg-base)' }} />
        <div className="p-1.5 space-y-1">
          <div className="h-3 rounded w-16" style={{ background: 'var(--bg-base)' }} />
          <div className="h-3 rounded w-10" style={{ background: 'var(--bg-base)' }} />
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
    <div
      className="rounded-md overflow-hidden border transition-colors group"
      style={{ borderColor: 'var(--border-subtle)', background: 'var(--bg-subtle)' }}
    >
      <div
        className="relative cursor-pointer overflow-hidden aspect-video"
        style={{ background: 'var(--bg-base)' }}
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
              className="h-8 w-8"
              style={{ color: 'var(--text-tertiary)' }}
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
          className="badge font-mono tabular-nums inline-flex items-center gap-1"
          style={
            onSeekToTimestamp
              ? { background: 'var(--accent-dim)', color: 'var(--accent)', cursor: 'pointer' }
              : { background: 'var(--bg-base)', color: 'var(--text-tertiary)' }
          }
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
          <div
            className="text-xs truncate px-0.5"
            style={{ color: 'var(--text-tertiary)' }}
          >
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

  const reindexMutation = useMutation({
    mutationFn: async () => {
      if (!videoHash) throw new Error("No video hash");
      await indexImages(videoHash, true);
    },
    onError: (error) => {
      console.error("[VisualSearch] Re-index failed:", error);
      setIndexingError("Re-indexing failed. Please try again.");
    },
  });

  const searchMutation = useMutation({
    mutationFn: async (query: string) => {
      if (videoHash) {
        try {
          await indexImages(videoHash);
        } catch (err) {
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
              className="h-4 w-4"
              style={{ color: 'var(--text-tertiary)' }}
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
            placeholder="Search screenshots… (e.g., 'person at whiteboard')"
            className="input-base pl-10"
          />
        </div>
        <div className="flex gap-2">
          <button
            type="submit"
            disabled={searchMutation.isPending || !searchQuery.trim()}
            className="btn-primary flex-1"
          >
            {searchMutation.isPending ? (
              <>
                <span className="spinner mr-2" style={{ width: '0.875rem', height: '0.875rem', borderWidth: '1.5px' }} />
                Searching…
              </>
            ) : (
              "Search"
            )}
          </button>
          <button
            type="button"
            disabled={reindexMutation.isPending || !videoHash}
            onClick={() => reindexMutation.mutate()}
            className="btn-secondary px-3"
            title="Re-index images with updated embeddings"
          >
            {reindexMutation.isPending ? (
              <span className="spinner" style={{ width: '0.875rem', height: '0.875rem', borderWidth: '1.5px' }} />
            ) : (
              <svg className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                <path
                  fillRule="evenodd"
                  d="M4 2a1 1 0 011 1v2.101a7.002 7.002 0 0111.601 2.566 1 1 0 11-1.885.666A5.002 5.002 0 005.999 7H9a1 1 0 010 2H4a1 1 0 01-1-1V3a1 1 0 011-1zm.008 9.057a1 1 0 011.276.61A5.002 5.002 0 0014.001 13H11a1 1 0 110-2h5a1 1 0 011 1v5a1 1 0 11-2 0v-2.101a7.002 7.002 0 01-11.601-2.566 1 1 0 01.61-1.276z"
                  clipRule="evenodd"
                />
              </svg>
            )}
          </button>
        </div>
      </form>

      {/* Re-index success message */}
      {reindexMutation.isSuccess && (
        <div
          className="mt-2 p-2 border-l-4 text-xs rounded-md"
          style={{
            background: 'oklch(70% 0.15 145 / 0.10)',
            borderColor: 'var(--c-success)',
            color: 'var(--c-success)',
          }}
        >
          Re-indexing complete. Search again to see updated results.
        </div>
      )}

      {/* Loading skeleton */}
      {searchMutation.isPending && <LoadingSkeleton />}

      {/* Results */}
      {searchMutation.isSuccess && !searchMutation.isPending && (
        <div className="mt-4">
          <div className="flex items-center mb-3">
            <h4
              className="text-sm font-semibold"
              style={{ color: 'var(--text-primary)' }}
            >
              Visual Results
            </h4>
            <span className="ml-2 badge badge-accent">
              {searchMutation.data.results.length}
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
            <div className="empty-state">
              <svg
                className="empty-state-icon"
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
              <p className="text-xs" style={{ color: 'var(--text-tertiary)' }}>
                No matching screenshots. Try a different description.
              </p>
            </div>
          )}
        </div>
      )}

      {/* Empty / initial state */}
      {!searchMutation.isSuccess && !searchMutation.isPending && !searchMutation.isError && (
        <div className="empty-state mt-6">
          <svg
            className="empty-state-icon"
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
          <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>
            Search for visual content in your video
          </p>
          <p className="mt-1 text-xs" style={{ color: 'var(--text-tertiary)' }}>
            Powered by CLIP semantic image search
          </p>
        </div>
      )}

      {/* Error state */}
      {searchMutation.isError && (
        <div
          className="mt-4 p-3 border-l-4 text-sm rounded-md"
          style={{
            background: 'oklch(65% 0.20 25 / 0.10)',
            borderColor: 'var(--c-error)',
            color: 'var(--c-error)',
          }}
        >
          Search failed. Please try again with a different description.
        </div>
      )}

      {indexingError && (
        <div
          className="mt-4 p-3 border-l-4 text-sm rounded-md"
          style={{
            background: 'oklch(78% 0.15 65 / 0.10)',
            borderColor: 'var(--c-warning)',
            color: 'var(--c-warning)',
          }}
        >
          {indexingError}
        </div>
      )}
    </div>
  );
};
