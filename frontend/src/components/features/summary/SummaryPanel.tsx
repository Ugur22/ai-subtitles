import { useState, useEffect } from 'react';
import axios from 'axios';
import { ChevronUpIcon, ChevronDownIcon } from '@heroicons/react/24/outline';

interface SummarySection {
  title: string;
  start: string;
  end: string;
  summary: string;
  screenshot_url?: string | null;
}

// Define the segment interface to match the API response
interface Segment {
  id: number;
  start_time: string;
  end_time: string;
  text: string;
  translation: string | null;
  screenshot_url?: string;
}

interface SummaryPanelProps {
  isVisible: boolean;
  onSeekTo?: (time: string) => void;
  summaries: SummarySection[];
  setSummaries: React.Dispatch<React.SetStateAction<SummarySection[]>>;
  loading: boolean;
  generateSummaries: () => Promise<void>;
}

export const SummaryPanel = ({ 
  isVisible, 
  onSeekTo, 
  summaries, 
  setSummaries, 
  loading, 
  generateSummaries 
}: SummaryPanelProps) => {
  const [expandedSection, setExpandedSection] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  
  const handleSeekTo = (time: string) => {
    if (onSeekTo) {
      onSeekTo(time);
    }
  };
  
  const formatScreenshotUrl = (url: string | null | undefined): string | undefined => {
    if (!url) return undefined;
    
    // If URL already starts with http, return as is
    if (url.startsWith('http')) {
      return url;
    }
    
    // Otherwise, prepend the API server URL
    return `http://localhost:8000${url}`;
  };
  
  if (!isVisible) return null;
  
  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-100 overflow-hidden flex flex-col h-full">
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
        <div className="divide-y divide-gray-100 overflow-y-auto flex-1">
          {summaries.map((section, index) => (
            <div key={index} className="hover:bg-gray-50">
              <div 
                className="flex items-start px-5 py-3 cursor-pointer"
                onClick={() => setExpandedSection(expandedSection === index ? null : index)}
              >
                {section.screenshot_url ? (
                  <div className="flex-shrink-0 mr-3">
                    <img 
                      src={formatScreenshotUrl(section.screenshot_url)}
                      alt={`Screenshot for ${section.title}`}
                      className="w-32 h-32 object-cover rounded-md shadow-sm hover:shadow-md transition-shadow cursor-pointer"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleSeekTo(section.start);
                      }}
                    />
                  </div>
                ) : (
                  <div className="flex-shrink-0 mr-3 w-32 h-32 bg-gray-100 rounded-md flex items-center justify-center">
                    <span className="text-xs text-gray-400">[No preview]</span>
                  </div>
                )}
                
                <div className="flex-1">
                  <div className="flex justify-between items-start">
                    <h4 className="text-sm font-medium text-gray-900">{section.title}</h4>
                    <div className="ml-2 flex-shrink-0">
                      {expandedSection === index ? (
                        <ChevronUpIcon className="h-5 w-5 text-gray-500" />
                      ) : (
                        <ChevronDownIcon className="h-5 w-5 text-gray-500" />
                      )}
                    </div>
                  </div>
                  <p className="mt-1 text-xs text-gray-500">{section.start} - {section.end}</p>
                  {expandedSection !== index && (
                    <p className="mt-1 text-sm text-gray-700 line-clamp-2">{section.summary}</p>
                  )}
                </div>
              </div>
              
              {expandedSection === index && (
                <div className="px-5 py-2 bg-gray-50">
                  <p className="text-sm text-gray-700">{section.summary}</p>
                  <button 
                    className="mt-2 text-xs text-teal-600 hover:text-teal-800"
                    onClick={() => handleSeekTo(section.start)}
                  >
                    Jump to this section
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}; 