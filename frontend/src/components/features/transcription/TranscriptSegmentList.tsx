import React from "react";
import { useSpring, animated } from "react-spring";

interface Segment {
  id: string;
  start_time: string;
  end_time: string;
  text: string;
  translation?: string | null;
  speaker?: string;
  screenshot_url?: string;
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
  const style = useSpring({
    transform: isActive ? "scale(1.02)" : "scale(1)",
    boxShadow: isActive
      ? "0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06)"
      : "0 0 0 0 rgba(0, 0, 0, 0)",
    borderColor: isActive ? "rgb(96, 165, 250)" : "rgb(229, 231, 235)",
    backgroundColor: isActive ? "rgb(239, 246, 255)" : "rgb(255, 255, 255)",
    config: { tension: 300, friction: 20 },
  });

  return (
    <animated.div
      style={style}
      id={`transcript-segment-${segment.id}`}
      onClick={props.onClick}
      className={`p-4 md:p-5 rounded-xl border-2 cursor-pointer transition-colors duration-200 hover:bg-gray-50`}
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
    }) => {
      return (
        <div className="p-5 space-y-4">
          {segments.length === 0 ? (
            <div className="text-center py-16">
              <svg
                className="mx-auto h-16 w-16 text-gray-400"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={1.5}
                  d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z"
                />
              </svg>
              <h3 className="mt-4 text-base font-medium text-gray-900">
                No segments found
              </h3>
              <p className="mt-2 text-sm text-gray-500">
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
                <div className="flex items-start gap-4">
                  {segment.screenshot_url && (
                    <div className="flex-shrink-0">
                      <img
                        src={`http://localhost:8000${segment.screenshot_url}`}
                        alt={`Screenshot at ${segment.start_time}`}
                        className="w-40 h-24 object-cover rounded-lg shadow-sm hover:shadow-lg transition-shadow hover:scale-110 cursor-pointer border border-gray-200"
                        onClick={(e) => {
                          e.stopPropagation();
                          openImageModal(
                            `http://localhost:8000${segment.screenshot_url}`
                          );
                        }}
                      />
                    </div>
                  )}
                  <div className="flex-grow min-w-0">
                    <div className="flex items-center flex-wrap gap-2 mb-2 text-xs font-semibold">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          seekToTimestamp(segment.start_time);
                        }}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-indigo-100 hover:bg-indigo-200 text-indigo-700 hover:text-indigo-900 rounded-lg transition-all duration-200 hover:shadow-sm active:scale-95"
                        title="Click to jump to this timestamp"
                      >
                        <svg
                          className="w-4 h-4"
                          viewBox="0 0 24 24"
                          fill="currentColor"
                        >
                          <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z" />
                        </svg>
                        {segment.start_time}
                      </button>
                      <span className="text-gray-400">→</span>
                      <span className="text-gray-600">{segment.end_time}</span>
                      {segment.speaker && editingSegmentId === segment.id && (
                        <div
                          className="flex items-center gap-2"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <input
                            type="text"
                            value={editSpeakerName}
                            onChange={(e) => setEditSpeakerName(e.target.value)}
                            className="px-2 py-1 text-xs border rounded shadow-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
                            autoFocus
                            onKeyDown={(e) => {
                              if (e.key === "Enter")
                                handleSpeakerRename(segment.speaker!);
                              if (e.key === "Escape") setEditingSegmentId(null);
                              e.stopPropagation();
                            }}
                            onClick={(e) => e.stopPropagation()}
                          />
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              handleSpeakerRename(segment.speaker!);
                            }}
                            className="p-1 text-xs text-green-600 hover:text-green-800 bg-green-50 rounded hover:bg-green-100"
                            title="Save"
                          >
                            <svg
                              className="w-4 h-4"
                              fill="none"
                              stroke="currentColor"
                              viewBox="0 0 24 24"
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
                            className="p-1 text-xs text-red-600 hover:text-red-800 bg-red-50 rounded hover:bg-red-100"
                            title="Cancel"
                          >
                            <svg
                              className="w-4 h-4"
                              fill="none"
                              stroke="currentColor"
                              viewBox="0 0 24 24"
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
                      {segment.speaker && editingSegmentId !== segment.id && (
                        <span
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
                          className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold border ${
                            getSpeakerColor(segment.speaker).bg
                          } ${getSpeakerColor(segment.speaker).text} ${
                            getSpeakerColor(segment.speaker).border
                          } cursor-pointer hover:ring-2 hover:ring-offset-1 hover:ring-indigo-300 transition-all`}
                          title="Click to rename speaker"
                        >
                          <svg
                            className="w-3.5 h-3.5"
                            fill="currentColor"
                            viewBox="0 0 20 20"
                          >
                            <path
                              fillRule="evenodd"
                              d="M10 9a3 3 0 100-6 3 3 0 000 6zm-7 9a7 7 0 1114 0H3z"
                              clipRule="evenodd"
                            />
                          </svg>
                          {formatSpeakerLabel(segment.speaker)}
                        </span>
                      )}
                      <span className="ml-auto inline-flex items-center px-3 py-1 rounded-full text-2xs font-semibold bg-indigo-100 text-indigo-700">
                        Segment {index + 1}
                      </span>
                    </div>
                    <p
                      className={`text-gray-800 leading-relaxed ${
                        activeSegmentId === segment.id
                          ? "font-semibold text-gray-900"
                          : "font-medium"
                      }`}
                    >
                      {showTranslation && segment.translation ? (
                        <>
                          {segment.translation}
                          <span className="block text-xs text-gray-500 italic mt-2">
                            Original: {segment.text}
                          </span>
                        </>
                      ) : (
                        segment.text
                      )}
                    </p>
                  </div>
                </div>
              </AnimatedSegment>
            ))
          )}
        </div>
      );
    }
  );
