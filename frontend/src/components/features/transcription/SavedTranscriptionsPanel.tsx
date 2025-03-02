import { useState, useEffect } from 'react';
import { getSavedTranscriptions, loadSavedTranscription, SavedTranscription } from '../../../services/api';
import { useQueryClient } from '@tanstack/react-query';

interface SavedTranscriptionsPanelProps {
  onTranscriptionLoaded?: () => void;
}

export const SavedTranscriptionsPanel = ({ onTranscriptionLoaded }: SavedTranscriptionsPanelProps) => {
  const [transcriptions, setTranscriptions] = useState<SavedTranscription[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [loadingTranscription, setLoadingTranscription] = useState(false);
  const queryClient = useQueryClient();

  useEffect(() => {
    fetchTranscriptions();
  }, []);

  const fetchTranscriptions = async () => {
    try {
      setLoading(true);
      const response = await getSavedTranscriptions();
      setTranscriptions(response.transcriptions);
      setLoading(false);
    } catch (err) {
      console.error('Failed to load saved transcriptions:', err);
      setError('Failed to load saved transcriptions. Please try again.');
      setLoading(false);
    }
  };

  const handleLoadTranscription = async (hash: string) => {
    try {
      setLoadingTranscription(true);
      const transcriptionData = await loadSavedTranscription(hash);
      setLoadingTranscription(false);
      
      // Reset any cached data in react-query
      queryClient.invalidateQueries();
      
      // Callback to notify parent component
      if (onTranscriptionLoaded) {
        onTranscriptionLoaded();
      }
    } catch (err) {
      console.error('Failed to load transcription:', err);
      setLoadingTranscription(false);
      setError('Failed to load transcription. Please try again.');
    }
  };

  const formatDate = (dateString: string) => {
    try {
      const date = new Date(dateString);
      return date.toLocaleDateString() + ' ' + date.toLocaleTimeString();
    } catch (e) {
      return dateString;
    }
  };

  return (
    <div className="card border rounded-lg overflow-hidden shadow-sm bg-white">
      <div className="card-header p-4 border-b">
        <h3 className="text-lg font-medium text-gray-900">Saved Transcriptions</h3>
        <p className="text-sm text-gray-500 mt-1">
          Load a previously transcribed video
        </p>
      </div>

      <div className="card-body p-4">
        {loading ? (
          <div className="flex justify-center py-8">
            <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-gray-900"></div>
          </div>
        ) : error ? (
          <div className="p-4 text-red-800 border border-red-300 rounded-md bg-red-50">
            <p>{error}</p>
            <button 
              onClick={() => fetchTranscriptions()}
              className="mt-2 text-sm text-blue-600 hover:text-blue-800"
            >
              Try Again
            </button>
          </div>
        ) : transcriptions.length === 0 ? (
          <div className="text-center py-8">
            <svg xmlns="http://www.w3.org/2000/svg" className="h-16 w-16 mx-auto text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
            </svg>
            <p className="mt-2 text-gray-500">No saved transcriptions found.</p>
            <p className="text-sm text-gray-400">Transcriptions will be saved automatically when you process videos.</p>
          </div>
        ) : (
          <div className="overflow-y-auto max-h-[350px]">
            <ul className="divide-y divide-gray-200">
              {transcriptions.map((t) => (
                <li key={t.video_hash} className="py-3 hover:bg-gray-50 transition-colors">
                  <div className="flex items-center justify-between">
                    <div className="ml-2">
                      <h4 className="font-medium text-gray-900 truncate max-w-[200px]">{t.filename}</h4>
                      <p className="text-xs text-gray-500">{formatDate(t.created_at)}</p>
                    </div>
                    <button
                      onClick={() => handleLoadTranscription(t.video_hash)}
                      disabled={loadingTranscription}
                      className={`ml-4 px-3 py-1.5 text-sm rounded-md transition-colors ${
                        loadingTranscription 
                          ? 'bg-gray-300 text-gray-600 cursor-not-allowed' 
                          : 'bg-blue-600 text-white hover:bg-blue-700'
                      }`}
                    >
                      {loadingTranscription ? 'Loading...' : 'Load'}
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}
        
        {/* Refresh Button */}
        {!loading && transcriptions.length > 0 && (
          <button 
            onClick={fetchTranscriptions}
            className="mt-4 w-full py-2 text-sm border border-gray-300 rounded-md bg-gray-50 text-gray-600 hover:bg-gray-100 transition-colors"
          >
            Refresh List
          </button>
        )}
      </div>
    </div>
  );
}; 