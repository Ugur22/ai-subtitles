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
}

export const SummaryPanel = ({ isVisible, onSeekTo }: SummaryPanelProps) => {
  const [summaries, setSummaries] = useState<SummarySection[]>([]);
  const [loading, setLoading] = useState(false);
  const [expandedSection, setExpandedSection] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  
  const fetchScreenshotsForSummaries = async (summaryData: SummarySection[]) => {
    try {
      // Get the current transcription data
      const response = await axios.get('http://localhost:8000/current_transcription/');
      
      if (response.status !== 200) {
        console.error(`Error fetching transcription data: ${response.status}`);
        return summaryData;
      }
      
      const segments: Segment[] = response.data.transcription.segments;
      
      console.log("Fetched transcription data successfully");
      console.log("Number of segments with screenshots:", segments.filter(s => s.screenshot_url).length);
      
      // Match summary sections with segment screenshots
      const enhancedSummaries = summaryData.map(summary => {
        console.log(`Looking for screenshot for summary: ${summary.title} (${summary.start})`);
        
        // Try to find the best matching segment for this summary
        // Strategy 1: Find a segment that's very close to the start time of the summary (within 5 seconds)
        let matchingSegment = segments.find(segment => 
          Math.abs(timeToSeconds(segment.start_time) - timeToSeconds(summary.start)) < 5
        );
        
        // Strategy 2: If no exact match found, try to find a segment that's contained within the summary time range
        if (!matchingSegment) {
          const summaryStartTime = timeToSeconds(summary.start);
          const summaryEndTime = timeToSeconds(summary.end);
          
          matchingSegment = segments.find(segment => {
            const segmentTime = timeToSeconds(segment.start_time);
            return segmentTime >= summaryStartTime && segmentTime <= summaryEndTime;
          });
        }
        
        // Strategy 3: If still no match, just take the closest segment
        if (!matchingSegment) {
          let closestSegment = segments[0];
          let closestDiff = Math.abs(timeToSeconds(segments[0].start_time) - timeToSeconds(summary.start));
          
          for (const segment of segments) {
            const diff = Math.abs(timeToSeconds(segment.start_time) - timeToSeconds(summary.start));
            if (diff < closestDiff) {
              closestDiff = diff;
              closestSegment = segment;
            }
          }
          
          matchingSegment = closestSegment;
        }
        
        console.log(`Found matching segment:`, matchingSegment);
        console.log(`Screenshot URL:`, matchingSegment?.screenshot_url);
        
        return {
          ...summary,
          screenshot_url: matchingSegment?.screenshot_url || null
        };
      });
      
      console.log("Enhanced summaries with screenshots:", enhancedSummaries);
      return enhancedSummaries;
    } catch (error) {
      console.error('Error getting screenshots for summaries:', error);
      return summaryData; // Return original data if something fails
    }
  };
  
  const timeToSeconds = (timeStr: string): number => {
    try {
      console.log(`Converting time string: "${timeStr}"`);
      // Handle different time formats: HH:MM:SS or HH:MM:SS.mmm
      const parts = timeStr.split(':');
      if (parts.length !== 3) {
        console.error(`Invalid time format: ${timeStr}`);
        return 0;
      }
      
      const hours = parseInt(parts[0], 10);
      const minutes = parseInt(parts[1], 10);
      // Handle seconds with milliseconds
      const seconds = parseFloat(parts[2]);
      
      const totalSeconds = hours * 3600 + minutes * 60 + seconds;
      console.log(`Time ${timeStr} converted to ${totalSeconds} seconds`);
      return totalSeconds;
    } catch (error) {
      console.error(`Error converting time ${timeStr} to seconds:`, error);
      return 0;
    }
  };
  
  useEffect(() => {
    // If summaries are already generated but don't have screenshots, try to fetch them
    if (summaries.length > 0 && !summaries.some(s => s.screenshot_url)) {
      console.log("Summaries exist but no screenshots - attempting to fetch screenshots");
      const fetchScreenshots = async () => {
        try {
          const enhancedSummaries = await fetchScreenshotsForSummaries(summaries);
          setSummaries(enhancedSummaries);
        } catch (error) {
          console.error("Failed to fetch screenshots for existing summaries:", error);
        }
      };
      
      fetchScreenshots();
    }
  }, [summaries]);
  
  const generateSummaries = async () => {
    setLoading(true);
    setError(null);
    try {
      console.log("Generating summaries...");
      const response = await axios.post('http://localhost:8000/generate_summary/');
      const summaryData = response.data.summaries;
      
      console.log("Received summary data:", summaryData);
      console.log("Now fetching screenshots for summaries...");
      
      // First set the basic summaries without screenshots
      setSummaries(summaryData);
      
      // Then try to enhance them with screenshots
      try {
        const enhancedSummaries = await fetchScreenshotsForSummaries(summaryData);
        console.log("Final enhanced summaries:", enhancedSummaries);
        setSummaries(enhancedSummaries);
      } catch (screenshotError) {
        console.error("Error adding screenshots to summaries:", screenshotError);
        // We still have the basic summaries displayed
      }
      
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
    <div className="bg-white rounded-lg shadow-sm border border-gray-100 overflow-hidden">
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
                      onError={(e) => {
                        console.error(`Error loading image: ${section.screenshot_url}`);
                        e.currentTarget.style.display = 'none';
                      }}
                    />
                  </div>
                ) : (
                  <div className="flex-shrink-0 mr-3">
                    <div 
                      className="w-24 h-24 bg-gray-100 flex items-center justify-center rounded-md cursor-pointer"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleSeekTo(section.start);
                      }}
                    >
                      <svg className="w-8 h-8 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                      </svg>
                    </div>
                  </div>
                )}
                
                <div className="flex flex-col flex-grow">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center mr-2">
                      <button className="mr-1 text-gray-400">
                        {expandedSection === index ? (
                          <ChevronUpIcon className="w-4 h-4" />
                        ) : (
                          <ChevronDownIcon className="w-4 h-4" />
                        )}
                      </button>
                      <span className="font-medium text-gray-800">{section.title}</span>
                    </div>
                    <div className="flex items-center space-x-2 ml-auto">
                      <button 
                        className="text-xs text-teal-600 hover:text-teal-700 transition-colors"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleSeekTo(section.start);
                        }}
                      >
                        {section.start}
                      </button>
                      <span className="text-xs text-gray-400">-</span>
                      <button 
                        className="text-xs text-teal-600 hover:text-teal-700 transition-colors"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleSeekTo(section.end);
                        }}
                      >
                        {section.end}
                      </button>
                    </div>
                  </div>
                </div>
              </div>
              
              {expandedSection === index && (
                <div className="px-5 py-3 bg-gray-50 text-sm">
                  <p className="text-gray-700">{section.summary}</p>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}; 