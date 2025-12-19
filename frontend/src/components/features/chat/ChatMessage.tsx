import { useState } from "react";
import ReactMarkdown from "react-markdown";

interface Source {
  start_time: string;
  end_time: string;
  start: number;
  end: number;
  speaker: string;
  text?: string;
  screenshot_url?: string;
  type?: "text" | "visual" | "audio";
  event_type?: string;
  confidence?: number;
}

interface ChatMessageProps {
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
  onTimestampClick?: (timeString: string) => void;
}

interface ScreenshotGalleryProps {
  screenshots: Source[];
  onTimestampClick?: (timeString: string) => void;
}

interface TextSourcesProps {
  sources: Source[];
  onTimestampClick?: (timeString: string) => void;
}

interface AudioSourcesProps {
  sources: Source[];
  onTimestampClick?: (timeString: string) => void;
}

const ScreenshotGallery: React.FC<ScreenshotGalleryProps> = ({
  screenshots,
  onTimestampClick,
}) => {
  const [selectedImage, setSelectedImage] = useState<string | null>(null);

  if (screenshots.length === 0) return null;

  return (
    <div className="mt-4 pt-4 border-t border-gray-200">
      <div className="flex items-center gap-2 mb-3">
        <svg
          className="w-4 h-4 text-purple-600"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"
          />
        </svg>
        <h4 className="text-sm font-semibold text-gray-800">
          Visual Evidence ({screenshots.length})
        </h4>
      </div>

      <div className="grid grid-cols-3 gap-2">
        {screenshots.map((screenshot, idx) => (
          <div
            key={idx}
            className="relative group cursor-pointer"
            onClick={() => setSelectedImage(screenshot.screenshot_url || null)}
          >
            <img
              src={`http://localhost:8000${screenshot.screenshot_url}`}
              alt={`Screenshot at ${screenshot.start_time}`}
              className="w-full h-24 object-cover rounded-lg border-2 border-gray-200 hover:border-purple-400 transition-all duration-200 group-hover:shadow-lg"
            />
            <div className="absolute inset-0 bg-black bg-opacity-0 group-hover:bg-opacity-30 transition-opacity rounded-lg flex items-center justify-center">
              <svg
                className="w-6 h-6 text-white opacity-0 group-hover:opacity-100 transition-opacity"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0zM10 7v3m0 0v3m0-3h3m-3 0H7"
                />
              </svg>
            </div>
            <button
              onClick={(e) => {
                e.stopPropagation();
                onTimestampClick?.(screenshot.start_time);
              }}
              className="absolute bottom-1 left-1 right-1 px-2 py-1 bg-black bg-opacity-75 text-white text-xs rounded backdrop-blur-sm hover:bg-opacity-90 transition-all font-mono"
              title="Click to jump to this timestamp"
            >
              {screenshot.start_time}
            </button>
          </div>
        ))}
      </div>

      {/* Lightbox Modal */}
      {selectedImage && (
        <div
          className="fixed inset-0 z-50 bg-black bg-opacity-90 flex items-center justify-center p-4"
          onClick={() => setSelectedImage(null)}
        >
          <div className="relative max-w-5xl max-h-full">
            <img
              src={`http://localhost:8000${selectedImage}`}
              alt="Enlarged screenshot"
              className="max-w-full max-h-[90vh] object-contain rounded-lg"
            />
            <button
              onClick={() => setSelectedImage(null)}
              className="absolute top-2 right-2 w-10 h-10 bg-white bg-opacity-20 hover:bg-opacity-30 text-white rounded-full flex items-center justify-center backdrop-blur-sm transition-all"
              aria-label="Close"
            >
              <svg
                className="w-6 h-6"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M6 18L18 6M6 6l12 12"
                />
              </svg>
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

const TextSources: React.FC<TextSourcesProps> = ({
  sources,
  onTimestampClick,
}) => {
  if (sources.length === 0) return null;

  return (
    <div className="mt-4 pt-4 border-t border-gray-200">
      <div className="flex items-center gap-2 mb-3">
        <svg
          className="w-4 h-4 text-indigo-600"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
          />
        </svg>
        <h4 className="text-sm font-semibold text-gray-800">
          Transcript Sources ({sources.length})
        </h4>
      </div>

      <div className="space-y-2">
        {sources.map((source, idx) => (
          <button
            key={idx}
            onClick={() => onTimestampClick?.(source.start_time)}
            className="block w-full text-left px-3 py-2 bg-white hover:bg-indigo-50 rounded-lg border border-gray-200 hover:border-indigo-300 transition-all duration-200 group"
          >
            <div className="flex items-center gap-2 mb-1">
              <span className="font-mono text-xs font-semibold text-indigo-600 group-hover:text-indigo-700">
                {source.start_time}
              </span>
              <svg
                className="w-3 h-3 text-gray-400"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M9 5l7 7-7 7"
                />
              </svg>
              <span className="font-mono text-xs font-semibold text-indigo-600 group-hover:text-indigo-700">
                {source.end_time}
              </span>
              <span className="text-xs px-2 py-0.5 bg-gray-100 text-gray-600 rounded-full ml-auto">
                {source.speaker}
              </span>
            </div>
            {source.text && (
              <p className="text-xs text-gray-600 line-clamp-2 leading-relaxed">
                {source.text}
              </p>
            )}
          </button>
        ))}
      </div>
    </div>
  );
};

const AudioSources: React.FC<AudioSourcesProps> = ({
  sources,
  onTimestampClick,
}) => {
  if (sources.length === 0) return null;

  // Helper function to get emoji and label for event type
  const getEventDetails = (eventType: string) => {
    const type = eventType.toLowerCase();

    // Emotions
    if (type.includes('happy') || type.includes('joy')) {
      return { emoji: '😊', label: 'Happy' };
    }
    if (type.includes('sad') || type.includes('sadness')) {
      return { emoji: '😢', label: 'Sad' };
    }
    if (type.includes('angry') || type.includes('anger')) {
      return { emoji: '😠', label: 'Angry' };
    }
    if (type.includes('fear') || type.includes('scared')) {
      return { emoji: '😨', label: 'Fearful' };
    }
    if (type.includes('neutral') || type.includes('calm')) {
      return { emoji: '😐', label: 'Neutral' };
    }
    if (type.includes('surprise')) {
      return { emoji: '😲', label: 'Surprised' };
    }
    if (type.includes('disgust')) {
      return { emoji: '🤢', label: 'Disgust' };
    }

    // Audio events
    if (type.includes('speech') || type.includes('speaking') || type.includes('narration')) {
      return { emoji: '🗣️', label: 'Speech' };
    }
    if (type.includes('music') || type.includes('melody')) {
      return { emoji: '🎵', label: 'Music' };
    }
    if (type.includes('applause') || type.includes('clap')) {
      return { emoji: '👏', label: 'Applause' };
    }
    if (type.includes('laugh')) {
      return { emoji: '😂', label: 'Laughter' };
    }
    if (type.includes('cry') || type.includes('sobbing')) {
      return { emoji: '😭', label: 'Crying' };
    }
    if (type.includes('silence') || type.includes('ambient') || type.includes('quiet')) {
      return { emoji: '🔇', label: 'Silence' };
    }
    if (type.includes('shout') || type.includes('yell')) {
      return { emoji: '📢', label: 'Shouting' };
    }
    if (type.includes('whisper')) {
      return { emoji: '🤫', label: 'Whisper' };
    }
    if (type.includes('cheer')) {
      return { emoji: '🎉', label: 'Cheering' };
    }

    // Default - capitalize first letter
    const label = eventType.charAt(0).toUpperCase() + eventType.slice(1);
    return { emoji: '🔊', label };
  };

  return (
    <div className="mt-4 pt-4 border-t border-gray-200">
      <div className="bg-gray-50 rounded-xl p-4 border border-gray-200">
        <div className="flex items-center gap-2 mb-4">
          <div className="p-2 bg-amber-100 rounded-lg">
            <svg
              className="w-5 h-5 text-amber-600"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M15.536 8.464a5 5 0 010 7.072m2.828-9.9a9 9 0 010 12.728M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z"
              />
            </svg>
          </div>
          <h4 className="text-sm font-bold text-gray-800 uppercase tracking-wide">
            Audio Events ({sources.length})
          </h4>
        </div>

        <div className="grid grid-cols-3 gap-3">
          {sources.map((source, idx) => {
            const eventDetails = getEventDetails(source.event_type || 'unknown');
            const confidence = source.confidence || 0;

            return (
              <button
                key={idx}
                onClick={() => onTimestampClick?.(source.start_time)}
                className="bg-white rounded-lg border-2 border-gray-200 p-3 hover:border-amber-400 hover:shadow-lg transition-all cursor-pointer text-left"
                title={`Click to jump to ${source.start_time}`}
              >
                {/* Event Emoji - Large and centered at top */}
                <div className="text-2xl mb-2">{eventDetails.emoji}</div>

                {/* Event Type Label */}
                <div className="font-semibold text-sm text-gray-800 mb-1">
                  {eventDetails.label}
                </div>

                {/* Timestamp - Amber colored, font-mono */}
                <div className="text-xs text-amber-600 font-mono mb-1">
                  {source.start_time}
                </div>

                {/* Speaker */}
                {source.speaker && source.speaker !== 'Unknown' && (
                  <div className="text-xs text-gray-500 mb-2">
                    {source.speaker}
                  </div>
                )}

                {/* Confidence Bar */}
                {confidence > 0 && (
                  <div className="mt-2">
                    <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-amber-500 rounded-full transition-all duration-500"
                        style={{ width: `${confidence * 100}%` }}
                      />
                    </div>
                  </div>
                )}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
};

export const ChatMessage: React.FC<ChatMessageProps> = ({
  role,
  content,
  sources,
  onTimestampClick,
}) => {
  // Separate sources by type
  const visualSources = sources?.filter((s) => s.type === "visual") || [];
  const audioSources = sources?.filter((s) => s.type === "audio") || [];
  const textSources = sources?.filter((s) => s.type === "text" || !s.type) || [];

  return (
    <div
      className={`flex ${role === "user" ? "justify-end" : "justify-start"}`}
    >
      <div
        className={`max-w-3xl px-5 py-4 rounded-xl shadow-sm ${
          role === "user"
            ? "bg-gradient-to-br from-indigo-600 to-indigo-700 text-white"
            : "bg-white text-gray-900 border border-gray-200"
        }`}
      >
        {/* Message Content with Markdown */}
        <div
          className={`prose prose-sm max-w-none ${
            role === "user"
              ? "prose-invert prose-headings:text-white prose-p:text-white prose-strong:text-white prose-ul:text-white prose-li:text-white"
              : "prose-headings:text-gray-900 prose-p:text-gray-800"
          }`}
        >
          <ReactMarkdown
            components={{
              // Make timestamps clickable in markdown
              p: ({ children }) => {
                const text = String(children);
                const timestampRegex = /\[(\d{2}:\d{2}:\d{2})\]/g;

                if (timestampRegex.test(text)) {
                  const parts = text.split(timestampRegex);
                  return (
                    <p>
                      {parts.map((part, i) => {
                        // Check if this part matches HH:MM:SS format
                        if (/^\d{2}:\d{2}:\d{2}$/.test(part)) {
                          return (
                            <button
                              key={i}
                              onClick={() => onTimestampClick?.(part)}
                              className={`font-mono font-semibold underline decoration-dotted hover:decoration-solid transition-all ${
                                role === "user"
                                  ? "text-white hover:text-indigo-100"
                                  : "text-indigo-600 hover:text-indigo-700"
                              }`}
                              title="Click to jump to this timestamp"
                            >
                              [{part}]
                            </button>
                          );
                        }
                        return <span key={i}>{part}</span>;
                      })}
                    </p>
                  );
                }
                return <p>{children}</p>;
              },
            }}
          >
            {content}
          </ReactMarkdown>
        </div>

        {/* Visual Evidence Gallery */}
        {role === "assistant" && visualSources.length > 0 && (
          <ScreenshotGallery
            screenshots={visualSources}
            onTimestampClick={onTimestampClick}
          />
        )}

        {/* Audio Events */}
        {role === "assistant" && audioSources.length > 0 && (
          <AudioSources sources={audioSources} onTimestampClick={onTimestampClick} />
        )}

        {/* Text Sources */}
        {role === "assistant" && textSources.length > 0 && (
          <TextSources sources={textSources} onTimestampClick={onTimestampClick} />
        )}
      </div>
    </div>
  );
};
