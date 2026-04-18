import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { searchTranscription } from "../../../services/api";
import { VisualSearchPanel } from "./VisualSearchPanel";

type ActiveTab = "text" | "visual";

interface SearchPanelProps {
  onSeekToTimestamp?: (timestamp: string) => void;
  onImageClick?: (url: string) => void;
  videoHash?: string;
}

export const SearchPanel = ({
  onSeekToTimestamp,
  onImageClick,
  videoHash,
}: SearchPanelProps) => {
  const [searchQuery, setSearchQuery] = useState("");
  const [useSemanticSearch, setUseSemanticSearch] = useState(true);
  const [activeTab, setActiveTab] = useState<ActiveTab>("text");

  const searchMutation = useMutation({
    mutationFn: (query: string) =>
      searchTranscription(query, useSemanticSearch, videoHash),
    onError: (error) => {
      console.error("Search failed:", error);
    },
    retry: false,
  });

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (searchQuery.trim()) {
      searchMutation.mutate(searchQuery);
    }
  };

  const handleTimestampClick = (timestamp: string) => {
    if (onSeekToTimestamp) {
      onSeekToTimestamp(timestamp);
    }
  };

  return (
    <div className="surface-panel flex flex-col h-full">
      <div
        className="px-5 py-3 border-b"
        style={{ borderColor: 'var(--border-subtle)' }}
      >
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
            Search
          </h3>
          <div className="flex gap-1">
            <button
              onClick={() => setActiveTab("text")}
              className={activeTab === "text" ? "btn-primary text-xs px-3 py-1" : "btn-ghost text-xs px-3 py-1"}
            >
              Text
            </button>
            <button
              onClick={() => setActiveTab("visual")}
              className={activeTab === "visual" ? "btn-primary text-xs px-3 py-1" : "btn-ghost text-xs px-3 py-1"}
            >
              Visual
            </button>
          </div>
        </div>
      </div>

      <div className="p-5">
        {activeTab === "text" ? (
          <>
            <form onSubmit={handleSearch} className="space-y-4">
              <div>
                <div className="flex flex-col gap-2">
                  <div className="relative w-full">
                    <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                      <svg
                        className="h-4 w-4"
                        style={{ color: 'var(--text-tertiary)' }}
                        viewBox="0 0 20 20"
                        fill="currentColor"
                      >
                        <path
                          fillRule="evenodd"
                          d="M8 4a4 4 0 100 8 4 4 0 000-8zM2 8a6 6 0 1110.89 3.476l4.817 4.817a1 1 0 01-1.414 1.414l-4.816-4.816A6 6 0 012 8z"
                          clipRule="evenodd"
                        />
                      </svg>
                    </div>
                    <input
                      type="text"
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      placeholder="Search for keywords or phrases…"
                      className="input-base pl-10"
                    />
                  </div>
                  <button
                    type="submit"
                    disabled={searchMutation.isPending}
                    className="btn-primary w-full"
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
                </div>

                <div className="flex items-center gap-2 mt-3">
                  <input
                    type="checkbox"
                    id="semanticSearch"
                    checked={useSemanticSearch}
                    onChange={(e) => setUseSemanticSearch(e.target.checked)}
                    className="h-4 w-4 rounded"
                    style={{ accentColor: 'var(--accent)' }}
                  />
                  <label
                    htmlFor="semanticSearch"
                    className="text-xs"
                    style={{ color: 'var(--text-secondary)' }}
                  >
                    Use semantic search (finds related content even if exact words don't match)
                  </label>
                </div>
              </div>
            </form>

            {/* Search Results */}
            {searchMutation.isSuccess && (
              <div className="mt-6 max-h-[300px] overflow-y-auto pr-1">
                <div
                  className="flex items-center mb-4 sticky top-0 z-10 py-2"
                  style={{ background: 'var(--bg-surface)' }}
                >
                  <h4 className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
                    Results
                  </h4>
                  <span className="ml-2 badge badge-accent">
                    {searchMutation.data.total_matches}
                  </span>
                </div>

                {searchMutation.data.matches.length > 0 ? (
                  <div className="space-y-2">
                    {searchMutation.data.matches.map((match, index) => (
                      <div
                        key={index}
                        className="rounded-md p-3 border transition-colors hover:[background:var(--bg-subtle)]"
                        style={{ borderColor: 'var(--border-subtle)' }}
                      >
                        <div className="flex justify-between items-start mb-2">
                          <span
                            className="badge font-mono tabular-nums inline-flex items-center gap-1 cursor-pointer"
                            style={onSeekToTimestamp ? {
                              background: 'var(--accent-dim)',
                              color: 'var(--accent)',
                            } : {
                              background: 'var(--bg-subtle)',
                              color: 'var(--text-tertiary)',
                            }}
                            onClick={() => handleTimestampClick(match.timestamp.start)}
                          >
                            <svg className="w-2.5 h-2.5" viewBox="0 0 20 20" fill="currentColor">
                              <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-12a1 1 0 10-2 0v4a1 1 0 00.293.707l2.828 2.829a1 1 0 101.415-1.415L11 9.586V6z" clipRule="evenodd" />
                            </svg>
                            {match.timestamp.start} – {match.timestamp.end}
                          </span>
                        </div>

                        {/* Context Before */}
                        {match.context.before.length > 0 && (
                          <div className="text-xs mb-2" style={{ color: 'var(--text-tertiary)' }}>
                            {match.context.before.map((text, i) => (
                              <div key={i}>{text}</div>
                            ))}
                          </div>
                        )}

                        {/* Matched Text — accent highlight */}
                        <div
                          className="text-sm font-semibold my-2 px-2 py-1 rounded"
                          style={{
                            color: 'var(--text-primary)',
                            background: 'var(--accent-dim)',
                          }}
                        >
                          {match.original_text}
                        </div>

                        {/* Translation if available */}
                        {match.translated_text && (
                          <div
                            className="text-xs italic my-2 px-2 py-1 rounded"
                            style={{
                              color: 'var(--text-secondary)',
                              background: 'var(--bg-subtle)',
                            }}
                          >
                            {match.translated_text}
                          </div>
                        )}

                        {/* Context After */}
                        {match.context.after.length > 0 && (
                          <div className="text-xs mt-2" style={{ color: 'var(--text-tertiary)' }}>
                            {match.context.after.map((text, i) => (
                              <div key={i}>{text}</div>
                            ))}
                          </div>
                        )}
                      </div>
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
                        d="M9.172 16.172a4 4 0 015.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                      />
                    </svg>
                    <h3 className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
                      No results
                    </h3>
                    <p className="mt-1 text-xs" style={{ color: 'var(--text-tertiary)' }}>
                      Try adjusting your terms or use semantic search.
                    </p>
                  </div>
                )}
              </div>
            )}

            {/* Error Display */}
            {searchMutation.isError && (
              <div
                className="mt-4 p-3 border-l-4 text-sm rounded-md"
                style={{
                  background: 'oklch(65% 0.20 25 / 0.10)',
                  borderColor: 'var(--c-error)',
                  color: 'var(--c-error)',
                }}
              >
                Search failed. Please try again with different terms.
              </div>
            )}
          </>
        ) : (
          <VisualSearchPanel
            onSeekToTimestamp={onSeekToTimestamp}
            onImageClick={onImageClick}
            videoHash={videoHash}
          />
        )}
      </div>
    </div>
  );
};
