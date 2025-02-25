import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { searchTranscription, SearchResponse } from '../../../services/api';

export const AnalyticsPanel = () => {
  const [searchTerm, setSearchTerm] = useState('');
  const [searchResults, setSearchResults] = useState<SearchResponse | null>(null);
  const [semanticSearch, setSemanticSearch] = useState(true);

  const searchMutation = useMutation({
    mutationFn: ({ topic, semantic }: { topic: string; semantic: boolean }) => 
      searchTranscription(topic, semantic),
    onSuccess: (data) => {
      setSearchResults(data);
    },
  });

  const handleSearch = () => {
    if (!searchTerm.trim()) return;
    searchMutation.mutate({ topic: searchTerm, semantic: semanticSearch });
  };

  return (
    <div className="card border rounded-lg overflow-hidden shadow-sm">
      <div className="card-header bg-white p-4 border-b">
        <h3 className="text-lg font-medium text-gray-900">Content Search</h3>
        <p className="text-sm text-gray-500 mt-1">
          Search for keywords or topics in your transcribed content
        </p>
      </div>

      <div className="card-body p-4">
        <div className="mb-4">
          <div className="flex gap-2 mb-2">
            <input
              type="text"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="Enter search term or topic..."
              className="flex-1 px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <button
              onClick={handleSearch}
              disabled={searchMutation.isPending || !searchTerm.trim()}
              className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
            >
              {searchMutation.isPending ? 'Searching...' : 'Search'}
            </button>
          </div>
          
          <div className="flex items-center">
            <label className="inline-flex items-center cursor-pointer">
              <input
                type="checkbox"
                checked={semanticSearch}
                onChange={() => setSemanticSearch(!semanticSearch)}
                className="sr-only peer"
              />
              <div className="relative w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-blue-300 rounded-full peer peer-checked:after:translate-x-full rtl:peer-checked:after:-translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:start-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"></div>
              <span className="ms-3 text-sm font-medium">Semantic Search</span>
            </label>
          </div>
        </div>

        {searchMutation.isPending && (
          <div className="animate-pulse space-y-4 py-2">
            <div className="h-4 bg-gray-200 rounded w-3/4"></div>
            <div className="h-4 bg-gray-200 rounded w-1/2"></div>
            <div className="h-4 bg-gray-200 rounded w-5/6"></div>
          </div>
        )}

        {searchMutation.isError && (
          <div className="p-4 text-red-800 border border-red-300 rounded-md bg-red-50">
            <p>There was an error processing your search request. Please try again.</p>
          </div>
        )}

        {searchResults && (
          <div className="mt-4">
            <h4 className="font-medium text-gray-900 mb-2">
              Found {searchResults.total_matches} matches for "{searchResults.topic}"
            </h4>
            
            {searchResults.matches.length === 0 ? (
              <p className="text-gray-500">No matches found. Try a different search term.</p>
            ) : (
              <div className="space-y-4">
                {searchResults.matches.map((match, index) => (
                  <div key={index} className="border rounded-md p-3 bg-gray-50">
                    <div className="flex justify-between mb-1">
                      <span className="text-sm text-gray-500">
                        {match.timestamp.start} - {match.timestamp.end}
                      </span>
                    </div>
                    <p className="mb-1 font-medium">{match.original_text}</p>
                    {match.translated_text && match.translated_text !== match.original_text && (
                      <p className="text-sm text-gray-600 italic">{match.translated_text}</p>
                    )}
                    {(match.context.before.length > 0 || match.context.after.length > 0) && (
                      <div className="mt-2 text-sm text-gray-500">
                        {match.context.before.length > 0 && (
                          <div className="mb-1">
                            <span className="text-xs font-medium">Before: </span>
                            {match.context.before.join(' ')}
                          </div>
                        )}
                        {match.context.after.length > 0 && (
                          <div>
                            <span className="text-xs font-medium">After: </span>
                            {match.context.after.join(' ')}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}; 