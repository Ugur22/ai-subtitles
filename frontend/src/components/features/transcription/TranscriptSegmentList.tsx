import React from "react";
import { useSpring, animated } from "react-spring";
import { formatScreenshotUrl } from "../../../utils/url";

interface Segment {
  id: string;
  start_time: string;
  end_time: string;
  text: string;
  translation?: string | null;
  speaker?: string;
  screenshot_url?: string;
  is_silent?: boolean;
}

interface TranscriptSegmentListProps {
  segments: Segment[];
  activeSegmentId: string | null;
  showTranslation: boolean;
  seekToTimestamp: (timestamp: string) => void;
  openImageModal: (imageUrl: string) => void;
  editingSegmentId: string | null;
  setEditingSegmentId: (segmentId: string | null) => void;
  editSpeakerName: string;
  setEditSpeakerName: (name: string) => void;
  handleSpeakerRename: (speaker: string) => void;
  getSpeakerColor: (speaker: string) => {
    bg: string;
    text: string;
    border: string;
  };
  formatSpeakerLabel: (speaker: string) => string;
  onEnrollSpeaker?: (segment: Segment) => void;
}

const AnimatedSegment = ({
  segment,
  isActive,
  ...props
}: {
  segment: Segment;
  isActive: boolean;
  [key: string]: any;
}) => {
  // Different styling for silent/visual segments
  const isSilent = segment.is_silent;

  const style = useSpring({
    transform: isActive ? "scale(1.02)" : "scale(1)",
    boxShadow: isActive
      ? "0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06)"
      : "0 0 0 0 rgba(0, 0, 0, 0), 0 0 0 0 rgba(0, 0, 0, 0)",
    borderColor: isSilent
      ? isActive
        ? "rgb(148, 163, 184)"
        : "rgb(203, 213, 225)" // slate colors for silent
      : isActive
      ? "rgb(96, 165, 250)"
      : "rgb(229, 231, 235)", // original blue/gray for speech
    backgroundColor: isSilent
      ? isActive
        ? "rgb(241, 245, 249)"
        : "rgb(248, 250, 252)" // slate-50/100 for silent
      : isActive
      ? "rgb(239, 246, 255)"
      : "rgb(255, 255, 255)", // original for speech
    config: { tension: 300, friction: 20 },
  });

  return (
    <animated.div
      style={style}
      id={`transcript-segment-${segment.id}`}
      onClick={props.onClick}
      className={`p-4 sm:p-5 rounded-xl border-2 cursor-pointer transition-all duration-200 ${
        isSilent ? "border-dashed hover:border-slate-400" : "hover:bg-gray-50 hover:border-blue-300"
      }`}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          props.onClick?.();
        }
      }}
      aria-label={`Transcript segment ${segment.id}: ${segment.text || 'Visual moment'}`}
    >
      {props.children}
    </animated.div>
  );
};

export const TranscriptSegmentList: React.FC<TranscriptSegmentListProps> =
  React.memo(
    ({
      segments,
      activeSegmentId,
      showTranslation,
      seekToTimestamp,
      openImageModal,
      editingSegmentId,
      setEditingSegmentId,
      editSpeakerName,
      setEditSpeakerName,
      handleSpeakerRename,
      getSpeakerColor,
      formatSpeakerLabel,
      onEnrollSpeaker,
    }) => {
      return (
        <div className="p-4 sm:p-5 space-y-4">
          {segments.length === 0 ? (
            <div className="text-center py-16">
              <div className="w-16 h-16 mx-auto bg-indigo-50 rounded-full flex items-center justify-center mb-4">
                <svg
                  className="h-8 w-8 text-indigo-400"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  aria-hidden="true"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z"
                  />
                </svg>
              </div>
              {/* Phase 1: Typography improvements - text-base font-semibold */}
              <h3 className="text-base font-semibold text-gray-900 mb-2">
                No segments found
              </h3>
              <p className="text-sm text-gray-600 max-w-sm mx-auto leading-relaxed">
                No segments match the current speaker filter.
              </p>
            </div>
          ) : (
            segments.map((segment, index) => (
              <AnimatedSegment
                key={segment.id}
                segment={segment}
                isActive={activeSegmentId === segment.id}
                onClick={() => {
                  console.log(
                    "Segment div clicked - seeking to",
                    segment.start_time,
                    "segment ID:",
                    segment.id
                  );
                  seekToTimestamp(segment.start_time);
                }}
              >
                {/* Phase 3: Layout improvements with responsive breakpoints */}
                <div
                  className={`flex items-start gap-3 sm:gap-4 ${
                    segment.is_silent ? "flex-col" : "flex-col sm:flex-row"
                  }`}
                >
                  {/* Phase 3: Thumbnail size optimization - 160px -> 96px */}
                  {segment.screenshot_url && (
                    <div
                      className={segment.is_silent ? "w-full" : "flex-shrink-0 w-full sm:w-24"}
                    >
                      <img
                        src={formatScreenshotUrl(segment.screenshot_url)}
                        alt={`Screenshot at ${segment.start_time}`}
                        className={`object-cover rounded-lg shadow-sm hover:shadow-md transition-all duration-200 hover:scale-105 cursor-pointer border ${
                          segment.is_silent
                            ? "w-full h-48 sm:h-64 border-slate-300"
                            : "w-full sm:w-24 h-24 border-gray-200"
                        }`}
                        onClick={(e) => {
                          e.stopPropagation();
                          openImageModal(
                            formatScreenshotUrl(segment.screenshot_url) || ""
                          );
                        }}
                        role="button"
                        tabIndex={0}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault();
                            e.stopPropagation();
                            openImageModal(formatScreenshotUrl(segment.screenshot_url) || "");
                          }
                        }}
                        aria-label={`View full screenshot at ${segment.start_time}`}
                      />
                    </div>
                  )}
                  <div className="flex-grow min-w-0 w-full">
                    {/* Phase 1: Better spacing and color consistency */}
                    <div className="flex items-center flex-wrap gap-2 mb-2.5 text-xs font-semibold">
                      {/* Phase 2: Improved hover states and accessibility */}
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          seekToTimestamp(segment.start_time);
                        }}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-indigo-100 hover:bg-indigo-200 text-indigo-700 hover:text-indigo-800 rounded-lg transition-all duration-200 hover:shadow-sm active:scale-95 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2"
                        title="Click to jump to this timestamp"
                        aria-label={`Jump to timestamp ${segment.start_time}`}
                      >
                        <svg
                          className="w-4 h-4"
                          viewBox="0 0 24 24"
                          fill="currentColor"
                          aria-hidden="true"
                        >
                          <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z" />
                        </svg>
                        {segment.start_time}
                      </button>
                      <span className="text-gray-400" aria-hidden="true">→</span>
                      <span className="text-gray-600 font-medium">{segment.end_time}</span>
                      {segment.is_silent ? (
                        <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold bg-slate-200 text-slate-700">
                          <svg
                            className="w-3.5 h-3.5"
                            fill="none"
                            stroke="currentColor"
                            viewBox="0 0 24 24"
                          >
                            <path
                              strokeLinecap="round"
                              strokeLinejoin="round"
                              strokeWidth={2}
                              d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z"
                            />
                          </svg>
                          Visual Moment
                        </span>
                      ) : (
                        <>
                          {segment.speaker &&
                            editingSegmentId === segment.id && (
                              <div
                                className="flex items-center gap-2"
                                onClick={(e) => e.stopPropagation()}
                              >
                                <input
                                  type="text"
                                  value={editSpeakerName}
                                  onChange={(e) =>
                                    setEditSpeakerName(e.target.value)
                                  }
                                  className="px-3 py-1.5 text-xs font-medium border border-indigo-300 rounded-lg shadow-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 transition-all duration-200"
                                  autoFocus
                                  onKeyDown={(e) => {
                                    if (e.key === "Enter")
                                      handleSpeakerRename(segment.speaker!);
                                    if (e.key === "Escape")
                                      setEditingSegmentId(null);
                                    e.stopPropagation();
                                  }}
                                  onClick={(e) => e.stopPropagation()}
                                  aria-label="Edit speaker name"
                                />
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    handleSpeakerRename(segment.speaker!);
                                  }}
                                  className="p-1.5 text-xs text-green-600 hover:text-green-800 bg-green-50 rounded-lg hover:bg-green-100 transition-all duration-200 active:scale-95 focus:outline-none focus:ring-2 focus:ring-green-500 focus:ring-offset-2"
                                  title="Save speaker name"
                                  aria-label="Save speaker name"
                                >
                                  <svg
                                    className="w-4 h-4"
                                    fill="none"
                                    stroke="currentColor"
                                    viewBox="0 0 24 24"
                                    aria-hidden="true"
                                  >
                                    <path
                                      strokeLinecap="round"
                                      strokeLinejoin="round"
                                      strokeWidth="2"
                                      d="M5 13l4 4L19 7"
                                    ></path>
                                  </svg>
                                </button>
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setEditingSegmentId(null);
                                  }}
                                  className="p-1.5 text-xs text-red-600 hover:text-red-800 bg-red-50 rounded-lg hover:bg-red-100 transition-all duration-200 active:scale-95 focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2"
                                  title="Cancel editing"
                                  aria-label="Cancel editing"
                                >
                                  <svg
                                    className="w-4 h-4"
                                    fill="none"
                                    stroke="currentColor"
                                    viewBox="0 0 24 24"
                                    aria-hidden="true"
                                  >
                                    <path
                                      strokeLinecap="round"
                                      strokeLinejoin="round"
                                      strokeWidth="2"
                                      d="M6 18L18 6M6 6l12 12"
                                    ></path>
                                  </svg>
                                </button>
                              </div>
                            )}
                          {segment.speaker &&
                            editingSegmentId !== segment.id && (
                              <button
                                onClick={(e) => {
                                  console.log("Speaker badge clicked", {
                                    speaker: segment.speaker,
                                    segmentStartTime: segment.start_time,
                                    segmentId: segment.id,
                                    segmentIndex: index,
                                    totalSegments: segments.length,
                                    clickedElement: e.currentTarget,
                                    targetElement: e.target,
                                  });
                                  e.stopPropagation();
                                  e.preventDefault();
                                  setEditingSegmentId(segment.id);
                                  setEditSpeakerName(
                                    formatSpeakerLabel(segment.speaker!)
                                  );
                                }}
                                className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold border ${
                                  getSpeakerColor(segment.speaker).bg
                                } ${getSpeakerColor(segment.speaker).text} ${
                                  getSpeakerColor(segment.speaker).border
                                } cursor-pointer hover:ring-2 hover:ring-offset-1 hover:ring-indigo-300 transition-all duration-200 active:scale-95 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2`}
                                title="Click to rename speaker"
                                aria-label={`Edit speaker name: ${formatSpeakerLabel(segment.speaker!)}`}
                              >
                                <svg
                                  className="w-3.5 h-3.5"
                                  fill="currentColor"
                                  viewBox="0 0 20 20"
                                  aria-hidden="true"
                                >
                                  <path
                                    fillRule="evenodd"
                                    d="M10 9a3 3 0 100-6 3 3 0 000 6zm-7 9a7 7 0 1114 0H3z"
                                    clipRule="evenodd"
                                  />
                                </svg>
                                {formatSpeakerLabel(segment.speaker)}
                              </button>
                            )}
                          {segment.speaker && onEnrollSpeaker && (
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                onEnrollSpeaker(segment);
                              }}
                              className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-semibold bg-purple-100 text-purple-700 hover:bg-purple-200 transition-all duration-200 border border-purple-200 active:scale-95 focus:outline-none focus:ring-2 focus:ring-purple-500 focus:ring-offset-2"
                              title="Enroll this speaker for automatic recognition"
                              aria-label={`Enroll ${formatSpeakerLabel(segment.speaker!)} for automatic recognition`}
                            >
                              <svg
                                className="w-3 h-3"
                                fill="none"
                                stroke="currentColor"
                                viewBox="0 0 24 24"
                                aria-hidden="true"
                              >
                                <path
                                  strokeLinecap="round"
                                  strokeLinejoin="round"
                                  strokeWidth={2}
                                  d="M12 6v6m0 0v6m0-6h6m-6 0H6"
                                />
                              </svg>
                              Enroll
                            </button>
                          )}
                        </>
                      )}
                      <span className="ml-auto inline-flex items-center px-3 py-1 rounded-full text-2xs font-semibold bg-indigo-100 text-indigo-700">
                        Segment {index + 1}
                      </span>
                    </div>
                    {/* Phase 1: Typography improvements with better color and spacing */}
                    {segment.is_silent ? (
                      <p className="text-slate-600 leading-relaxed italic text-sm mt-1">
                        No speech during this segment
                      </p>
                    ) : (
                      <p
                        className={`text-sm sm:text-base leading-relaxed mt-1 transition-all duration-200 ${
                          activeSegmentId === segment.id
                            ? "font-semibold text-gray-900"
                            : "font-medium text-gray-800"
                        }`}
                      >
                        {showTranslation && segment.translation ? (
                          <>
                            {segment.translation}
                            <span className="block text-xs text-gray-500 italic mt-2 font-normal">
                              Original: {segment.text}
                            </span>
                          </>
                        ) : (
                          segment.text
                        )}
                      </p>
                    )}
                  </div>
                </div>
              </AnimatedSegment>
            ))
          )}
        </div>
      );
    }
  );
