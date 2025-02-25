import { useState } from 'react';
import axios from 'axios';
import { ChevronUpIcon, ChevronDownIcon } from '@heroicons/react/24/outline';

interface SummarySection {
  title: string;
  start: string;
  end: string;
  summary: string;
}

interface SummaryPanelProps {
  isVisible: boolean;
  onSeekTo?: (time: string) => void;
}

export const SummaryPanel = ({ isVisible, onSeekTo }: SummaryPanelProps) => {
  const [summaries, setSummaries] = useState<SummarySection[]>([]);
  const [loading, setLoading] = useState(false);
  const [expandedSection, setExpandedSection] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  
  const generateSummaries = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await axios.post('http://localhost:8000/generate_summary/');
      setSummaries(response.data.summaries);
    } catch (error) {
      console.error('Error generating summaries:', error);
      if (axios.isAxiosError(error) && error.response) {
        setError(`Error: ${error.response.data.detail || 'Failed to generate summaries'}`);
      } else {
        setError('Failed to generate summaries. Please try again.');
      }
    } finally {
      setLoading(false);
    }
  };

  const handleSeekTo = (time: string) => {
    if (onSeekTo) {
      onSeekTo(time);
    }
  };
  
  if (!isVisible) return null;
  
  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-100 overflow-hidden mt-4">
      <div className="px-5 py-3 border-b border-gray-200 flex justify-between items-center">
        <h3 className="text-sm font-medium text-gray-800">Content Summary</h3>
        {!summaries.length && !loading && (
          <button 
            onClick={generateSummaries}
            className="px-3 py-1 text-xs bg-teal-500 text-white rounded hover:bg-teal-600 transition-colors"
            disabled={loading}
          >
            Generate Summary
          </button>
        )}
      </div>
      
      {loading && (
        <div className="p-5 text-center">
          <div className="inline-block animate-spin h-6 w-6 border-2 border-teal-500 border-t-transparent rounded-full"></div>
          <p className="text-sm text-gray-500 mt-2">Generating summaries...</p>
        </div>
      )}
      
      {error && !loading && (
        <div className="p-4 text-red-600 text-sm">
          {error}
          <button 
            className="block mt-2 text-teal-500 hover:text-teal-600"
            onClick={() => setError(null)}
          >
            Dismiss
          </button>
        </div>
      )}
      
      {!loading && summaries.length > 0 && (
        <div className="divide-y divide-gray-100 max-h-96 overflow-y-auto">
          {summaries.map((section, index) => (
            <div key={index} className="hover:bg-gray-50">
              <div 
                className="flex items-center justify-between px-5 py-3 cursor-pointer"
                onClick={() => setExpandedSection(expandedSection === index ? null : index)}
              >
                <div className="flex items-center">
                  <button className="mr-2 text-gray-400">
                    {expandedSection === index ? (
                      <ChevronUpIcon className="w-4 h-4" />
                    ) : (
                      <ChevronDownIcon className="w-4 h-4" />
                    )}
                  </button>
                  <span className="font-medium text-gray-800">{section.title}</span>
                </div>
                <button 
                  className="text-xs text-teal-600 hover:text-teal-700"
                  onClick={(e) => {
                    e.stopPropagation();
                    handleSeekTo(section.start);
                  }}
                >
                  {section.start}
                </button>
              </div>
              
              {expandedSection === index && (
                <div className="px-5 py-3 bg-gray-50 text-sm">
                  <p className="text-gray-700">{section.summary}</p>
                  <div className="mt-2 text-right">
                    <span className="text-xs text-gray-500">
                      {section.start} - {section.end}
                    </span>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}; 