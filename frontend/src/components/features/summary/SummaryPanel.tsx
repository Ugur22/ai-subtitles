import { useState, useEffect } from "react";
import axios from "axios";
import { ChevronUpIcon, ChevronDownIcon } from "@heroicons/react/24/outline";

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

// Simple Image Modal Component
interface ImageModalProps {
  imageUrl: string;
  onClose: () => void;
}

const ImageModal: React.FC<ImageModalProps> = ({ imageUrl, onClose }) => {
  // Prevent closing modal when clicking on the image itself
  const handleImageClick = (e: React.MouseEvent) => {
    e.stopPropagation();
  };

  return (
    <div
      className="fixed inset-0 bg-black bg-opacity-75 flex items-center justify-center z-50 p-4"
      onClick={onClose} // Close when clicking backdrop
    >
      <div
        className="relative bg-white p-2 rounded-lg shadow-xl max-w-6xl max-h-[90vh]"
        onClick={handleImageClick} // Prevent closing on image container click
      >
        <img
          src={imageUrl}
          alt="Enlarged screenshot"
          className="block w-[900px] max-h-[85vh] object-contain rounded-xl"
        />
        <button
          onClick={onClose}
          className="absolute top-2 right-2 bg-white rounded-full p-1 text-gray-700 hover:bg-gray-200 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-gray-500"
          aria-label="Close image modal"
        >
          <svg
            className="w-5 h-5"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth="2"
              d="M6 18L18 6M6 6l12 12"
            />
          </svg>
        </button>
      </div>
    </div>
  );
};

export const SummaryPanel = ({
  isVisible,
  onSeekTo,
  summaries,
  setSummaries,
  loading,
  generateSummaries,
}: SummaryPanelProps) => {
  const [expandedSection, setExpandedSection] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [modalImageUrl, setModalImageUrl] = useState<string | null>(null);

  const handleSeekTo = (time: string) => {
    if (onSeekTo) {
      onSeekTo(time);
    }
  };

  const formatScreenshotUrl = (
    url: string | null | undefined
  ): string | undefined => {
    if (!url) return undefined;

    // If URL already starts with http, return as is
    if (url.startsWith("http")) {
      return url;
    }

    // Otherwise, prepend the API server URL
    return `http://localhost:8000${url}`;
  };

  const openImageModal = (imageUrl: string | undefined) => {
    if (imageUrl) {
      setModalImageUrl(imageUrl);
      setIsModalOpen(true);
    }
  };

  if (!isVisible) return null;

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-100 overflow-hidden flex flex-col h-full">
      <div className="px-5 py-3 border-b border-gray-200 flex justify-between items-center">
        <h3 className="text-sm font-medium text-gray-800">Content Summary</h3>
        {(!summaries.length || summaries.length > 0) && !loading && (
          <div>
            {!summaries.length ? (
              <button
                onClick={generateSummaries}
                className="px-3 py-1 text-xs bg-gray-600 text-white rounded hover:bg-gray-700 transition-colors"
              >
                Generate Summary
              </button>
            ) : (
              <button
                onClick={generateSummaries}
                className="px-3 py-1 text-xs bg-gray-600 text-white rounded hover:bg-gray-700 transition-colors"
              >
                Regenerate Summary
              </button>
            )}
          </div>
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
            className="block mt-2 text-rose-500 hover:text-rose-600"
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
                onClick={() =>
                  setExpandedSection(expandedSection === index ? null : index)
                }
              >
                {section.screenshot_url ? (
                  <div className="flex-shrink-0 mr-3">
                    <img
                      src={formatScreenshotUrl(section.screenshot_url)}
                      alt={`Screenshot for ${section.title}`}
                      className="w-32 h-32 object-cover rounded-md shadow-sm hover:shadow-md transition-shadow cursor-pointer"
                      onClick={(e) => {
                        e.stopPropagation();
                        openImageModal(
                          formatScreenshotUrl(section.screenshot_url)
                        );
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
                    <h4 className="text-sm font-medium text-gray-900">
                      {section.title}
                    </h4>
                    <div className="ml-2 flex-shrink-0">
                      {expandedSection === index ? (
                        <ChevronUpIcon className="h-5 w-5 text-gray-500" />
                      ) : (
                        <ChevronDownIcon className="h-5 w-5 text-gray-500" />
                      )}
                    </div>
                  </div>
                  <p
                    className="mt-1 text-xs text-gray-500 cursor-pointer hover:text-rose-600 hover:underline"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleSeekTo(section.start);
                    }}
                  >
                    {section.start} - {section.end}
                  </p>
                  {expandedSection !== index && (
                    <p className="mt-1 text-sm text-gray-700 line-clamp-2">
                      {section.summary}
                    </p>
                  )}
                </div>
              </div>

              {expandedSection === index && (
                <div className="px-5 py-2 bg-gray-50">
                  <p className="text-sm text-gray-700">{section.summary}</p>
                  <button
                    className="mt-2 text-xs text-rose-600 hover:text-rose-800"
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

      {/* Image Modal */}
      {isModalOpen && modalImageUrl && (
        <ImageModal
          imageUrl={modalImageUrl}
          onClose={() => setIsModalOpen(false)}
        />
      )}
    </div>
  );
};
