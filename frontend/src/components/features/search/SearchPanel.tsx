import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { searchTranscription } from "../../../services/api";

export const SearchPanel = ({
  onSeekToTimestamp,
}: {
  onSeekToTimestamp?: (timestamp: string) => void;
}) => {
  const [searchQuery, setSearchQuery] = useState("");
  const [useSemanticSearch, setUseSemanticSearch] = useState(true);

  const searchMutation = useMutation({
    mutationFn: (query: string) =>
      searchTranscription(query, useSemanticSearch),
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

  // Add a handler for timestamp clicks
  const handleTimestampClick = (timestamp: string) => {
    if (onSeekToTimestamp) {
      onSeekToTimestamp(timestamp);
    }
  };

  return (
    <div className="card">
      <div className="card-header">
        <h3 className="text-lg font-medium text-gray-900">
          Search Transcription
        </h3>
      </div>

      <div className="card-body">
        <form onSubmit={handleSearch} className="space-y-4">
          <div>
            <div className="flex flex-col gap-2">
              <div className="relative w-full">
                <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                  <svg
                    className="h-5 w-5 text-gray-400"
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
                  placeholder="Search for keywords or phrases..."
                  className="block w-full pl-10 pr-3 py-2 border border-gray-300 rounded-md leading-5 bg-white placeholder-gray-500 focus:outline-none focus:ring-blue-500 focus:border-blue-500 sm:text-sm"
                />
              </div>
              <button
                type="submit"
                disabled={searchMutation.isPending}
                className="w-full btn-primary py-2.5 bg-violet-500 text-gray-900 rounded-md hover:bg-violet-600 transition-colors"
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
                      ></circle>
                      <path
                        className="opacity-75"
                        fill="currentColor"
                        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                      ></path>
                    </svg>
                    Searching...
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
                className="h-4 w-4 text-blue-600 rounded border-gray-300 focus:ring-blue-500"
              />
              <label htmlFor="semanticSearch" className="text-sm text-gray-600">
                Use semantic search (finds related content even if exact words
                don't match)
              </label>
            </div>
          </div>
        </form>

        {/* Search Results */}
        {searchMutation.isSuccess && (
          <div className="mt-6 max-h-[300px] overflow-y-auto pr-1">
            <div className="flex items-center mb-4 sticky top-0 bg-white z-10 py-2">
              <h4 className="text-base font-medium text-gray-900">
                Search Results
              </h4>
              <span className="ml-2 px-2.5 py-0.5 rounded-full text-xs font-medium bg-orange-100 text-orange-800">
                {searchMutation.data.total_matches} matches
              </span>
            </div>

            {searchMutation.data.matches.length > 0 ? (
              <div className="space-y-3">
                {searchMutation.data.matches.map((match, index) => (
                  <div
                    key={index}
                    className="border rounded-md p-4 bg-gray-50 hover:bg-gray-100 transition"
                  >
                    <div className="flex justify-between items-start mb-2">
                      <span
                        className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                          onSeekToTimestamp
                            ? "bg-orange-100 text-orange-800 cursor-pointer hover:bg-orange-200"
                            : "bg-gray-100 text-gray-800"
                        }`}
                        onClick={() =>
                          handleTimestampClick(match.timestamp.start)
                        }
                      >
                        <svg
                          className="w-3 h-3 mr-1"
                          viewBox="0 0 20 20"
                          fill="currentColor"
                        >
                          <path
                            fillRule="evenodd"
                            d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-12a1 1 0 10-2 0v4a1 1 0 00.293.707l2.828 2.829a1 1 0 101.415-1.415L11 9.586V6z"
                            clipRule="evenodd"
                          />
                        </svg>
                        {match.timestamp.start} - {match.timestamp.end}
                      </span>
                    </div>

                    {/* Context Before */}
                    {match.context.before.length > 0 && (
                      <div className="text-sm text-gray-500 mb-2">
                        {match.context.before.map((text, i) => (
                          <div key={i}>{text}</div>
                        ))}
                      </div>
                    )}

                    {/* Matched Text */}
                    <div className="text-base font-semibold text-gray-900 my-2 bg-yellow-100 px-2 py-1 rounded">
                      {match.original_text}
                    </div>

                    {/* Translation if available */}
                    {match.translated_text && (
                      <div className="text-sm text-gray-700 italic my-2 bg-gray-100 px-2 py-1 rounded">
                        {match.translated_text}
                      </div>
                    )}

                    {/* Context After */}
                    {match.context.after.length > 0 && (
                      <div className="text-sm text-gray-500 mt-2">
                        {match.context.after.map((text, i) => (
                          <div key={i}>{text}</div>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <div className="py-8 text-center">
                <svg
                  className="mx-auto h-12 w-12 text-gray-400"
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
                <h3 className="mt-2 text-sm font-medium text-gray-900">
                  No results found
                </h3>
                <p className="mt-1 text-sm text-gray-500">
                  Try adjusting your search terms or use semantic search.
                </p>
              </div>
            )}
          </div>
        )}

        {/* Error Display */}
        {searchMutation.isError && (
          <div className="mt-4 p-3 bg-red-50 border-l-4 border-red-400 text-red-700 text-sm rounded-md">
            An error occurred during search. Please try again with different
            search terms.
          </div>
        )}
      </div>
    </div>
  );
};
