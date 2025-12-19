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

  // Helper function to get emoji, label, and category for event type
  const getEventDetails = (eventType: string) => {
    const type = eventType.toLowerCase();

    // Emotions - Purple category
    if (type.includes('happy') || type.includes('joy')) {
      return { emoji: '😊', label: 'Happy', category: 'emotion' };
    }
    if (type.includes('sad') || type.includes('sadness')) {
      return { emoji: '😢', label: 'Sad', category: 'emotion' };
    }
    if (type.includes('angry') || type.includes('anger')) {
      return { emoji: '😠', label: 'Angry', category: 'emotion' };
    }
    if (type.includes('fear') || type.includes('scared')) {
      return { emoji: '😨', label: 'Fearful', category: 'emotion' };
    }
    if (type.includes('neutral') || type.includes('calm')) {
      return { emoji: '😐', label: 'Neutral', category: 'emotion' };
    }
    if (type.includes('surprise')) {
      return { emoji: '😲', label: 'Surprised', category: 'emotion' };
    }
    if (type.includes('disgust')) {
      return { emoji: '🤢', label: 'Disgust', category: 'emotion' };
    }

    // Vocal expressions and reactions - Speech category
    if (type.includes('sigh')) {
      return { emoji: '😮‍💨', label: 'Sigh', category: 'speech' };
    }
    if (type.includes('gasp')) {
      return { emoji: '😮', label: 'Gasp', category: 'speech' };
    }
    if (type.includes('moan')) {
      return { emoji: '😩', label: 'Moan', category: 'speech' };
    }
    if (type.includes('groan')) {
      return { emoji: '😫', label: 'Groan', category: 'speech' };
    }
    if (type.includes('panting')) {
      return { emoji: '😤', label: 'Panting', category: 'speech' };
    }
    if (type.includes('huff') || type.includes('huffing')) {
      return { emoji: '😤', label: 'Huffing', category: 'speech' };
    }
    if (type.includes('scream')) {
      return { emoji: '😱', label: 'Scream', category: 'speech' };
    }
    if (type.includes('whimper')) {
      return { emoji: '🥺', label: 'Whimper', category: 'speech' };
    }
    if (type.includes('sniff') || type.includes('sniffle')) {
      return { emoji: '🤧', label: 'Sniffling', category: 'speech' };
    }
    if (type.includes('yawn')) {
      return { emoji: '🥱', label: 'Yawn', category: 'speech' };
    }
    if (type.includes('sneeze')) {
      return { emoji: '🤧', label: 'Sneeze', category: 'speech' };
    }
    if (type.includes('cough')) {
      return { emoji: '🤒', label: 'Cough', category: 'speech' };
    }
    if (type.includes('hiccup')) {
      return { emoji: '😯', label: 'Hiccup', category: 'speech' };
    }

    // Breathing sounds - Speech category
    if (type.includes('breath') || type.includes('breathing')) {
      return { emoji: '💨', label: 'Breathing', category: 'speech' };
    }
    if (type.includes('exhale')) {
      return { emoji: '😮‍💨', label: 'Exhale', category: 'speech' };
    }
    if (type.includes('inhale')) {
      return { emoji: '😤', label: 'Inhale', category: 'speech' };
    }

    // Speech and vocalizations - Speech category
    if (type.includes('speech') || type.includes('speaking') || type.includes('narration')) {
      return { emoji: '🗣️', label: 'Speech', category: 'speech' };
    }
    if (type.includes('laugh')) {
      return { emoji: '😂', label: 'Laughter', category: 'speech' };
    }
    if (type.includes('giggle') || type.includes('chuckle')) {
      return { emoji: '😄', label: 'Giggling', category: 'speech' };
    }
    if (type.includes('cry') || type.includes('sobbing')) {
      return { emoji: '😭', label: 'Crying', category: 'speech' };
    }
    if (type.includes('shout') || type.includes('yell')) {
      return { emoji: '📢', label: 'Shouting', category: 'speech' };
    }
    if (type.includes('whisper')) {
      return { emoji: '🤫', label: 'Whisper', category: 'speech' };
    }
    if (type.includes('cheer')) {
      return { emoji: '🎉', label: 'Cheering', category: 'speech' };
    }
    if (type.includes('hum') || type.includes('humming')) {
      return { emoji: '🎵', label: 'Humming', category: 'speech' };
    }
    if (type.includes('sing')) {
      return { emoji: '🎤', label: 'Singing', category: 'speech' };
    }

    // Body sounds - Sound category
    if (type.includes('clap') || type.includes('applause')) {
      return { emoji: '👏', label: 'Applause', category: 'sound' };
    }
    if (type.includes('snap') || type.includes('finger snap')) {
      return { emoji: '👆', label: 'Snap', category: 'sound' };
    }
    if (type.includes('footstep') || type.includes('step')) {
      return { emoji: '👣', label: 'Footsteps', category: 'sound' };
    }
    if (type.includes('knock')) {
      return { emoji: '🚪', label: 'Knocking', category: 'sound' };
    }
    if (type.includes('tap') || type.includes('tapping')) {
      return { emoji: '👆', label: 'Tapping', category: 'sound' };
    }
    if (type.includes('stomp')) {
      return { emoji: '🦶', label: 'Stomping', category: 'sound' };
    }

    // Music and audio - Sound category
    if (type.includes('music') || type.includes('melody')) {
      return { emoji: '🎵', label: 'Music', category: 'sound' };
    }
    if (type.includes('silence') || type.includes('ambient') || type.includes('quiet')) {
      return { emoji: '🔇', label: 'Silence', category: 'sound' };
    }
    if (type.includes('noise')) {
      return { emoji: '🔊', label: 'Noise', category: 'sound' };
    }

    // Default - other category
    const label = eventType.charAt(0).toUpperCase() + eventType.slice(1);
    return { emoji: '🔊', label, category: 'other' };
  };

  // Get color theme based on event category
  const getCategoryTheme = (category: string) => {
    switch (category) {
      case 'emotion':
        return {
          bg: 'from-purple-50 to-fuchsia-50',
          border: 'border-purple-300',
          hoverBorder: 'hover:border-purple-400',
          hoverShadow: 'hover:shadow-purple-200',
          text: 'text-purple-700',
          timestamp: 'text-purple-600',
          confidence: 'bg-purple-500',
          badge: 'bg-purple-100 text-purple-700',
        };
      case 'speech':
        return {
          bg: 'from-blue-50 to-cyan-50',
          border: 'border-blue-300',
          hoverBorder: 'hover:border-blue-400',
          hoverShadow: 'hover:shadow-blue-200',
          text: 'text-blue-700',
          timestamp: 'text-blue-600',
          confidence: 'bg-blue-500',
          badge: 'bg-blue-100 text-blue-700',
        };
      case 'sound':
        return {
          bg: 'from-emerald-50 to-teal-50',
          border: 'border-emerald-300',
          hoverBorder: 'hover:border-emerald-400',
          hoverShadow: 'hover:shadow-emerald-200',
          text: 'text-emerald-700',
          timestamp: 'text-emerald-600',
          confidence: 'bg-emerald-500',
          badge: 'bg-emerald-100 text-emerald-700',
        };
      default:
        return {
          bg: 'from-amber-50 to-orange-50',
          border: 'border-amber-300',
          hoverBorder: 'hover:border-amber-400',
          hoverShadow: 'hover:shadow-amber-200',
          text: 'text-amber-700',
          timestamp: 'text-amber-600',
          confidence: 'bg-amber-500',
          badge: 'bg-amber-100 text-amber-700',
        };
    }
  };

  return (
    <div className="mt-4 pt-4 border-t border-gray-200">
      <div className="bg-gradient-to-br from-gray-50 to-slate-50 rounded-lg p-4 border border-gray-200">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <div className="p-2 bg-gradient-to-br from-indigo-100 to-purple-100 rounded-lg">
              <svg
                className="w-5 h-5 text-indigo-600"
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
            <div>
              <p className="text-sm font-bold text-gray-900">
                Audio Events Detected
              </p>
              <p className="text-xs text-gray-500">
                {sources.length} events found
              </p>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {sources.map((source, idx) => {
            const eventDetails = getEventDetails(source.event_type || 'unknown');
            const theme = getCategoryTheme(eventDetails.category);
            const confidence = source.confidence || 0;
            const duration = source.end && source.start
              ? `${(source.end - source.start).toFixed(1)}s`
              : null;

            return (
              <button
                key={idx}
                onClick={() => onTimestampClick?.(source.start_time)}
                className={`relative bg-gradient-to-br ${theme.bg} rounded-xl border-2 ${theme.border} ${theme.hoverBorder} p-4 hover:shadow-lg ${theme.hoverShadow} transition-all duration-200 text-left group`}
                title={`${eventDetails.label} at ${source.start_time}${duration ? ` (${duration})` : ''} - Click to play`}
                aria-label={`Jump to ${eventDetails.label} event at ${source.start_time}`}
              >
                {/* Confidence badge - Top right */}
                {confidence > 0 && (
                  <div className={`absolute top-3 right-3 px-2 py-0.5 ${theme.badge} rounded-full text-xs font-bold`}>
                    {Math.round(confidence * 100)}%
                  </div>
                )}

                {/* Event Emoji - Large and prominent */}
                <div className="text-3xl mb-3 group-hover:scale-110 transition-transform duration-200">
                  {eventDetails.emoji}
                </div>

                {/* Event Type Label - Bold and clear */}
                <div className={`font-bold text-base ${theme.text} mb-2`}>
                  {eventDetails.label}
                </div>

                {/* Timestamp - Prominent with icon */}
                <div className="flex items-center gap-1.5 mb-2">
                  <svg className={`w-3.5 h-3.5 ${theme.timestamp}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  <span className={`text-sm font-mono font-semibold ${theme.timestamp} group-hover:underline`}>
                    {source.start_time}
                  </span>
                  {duration && (
                    <span className="text-xs text-gray-500 ml-1">
                      ({duration})
                    </span>
                  )}
                </div>

                {/* Speaker - If available */}
                {source.speaker && source.speaker !== 'Unknown' && (
                  <div className="flex items-center gap-1.5">
                    <svg className="w-3.5 h-3.5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                    </svg>
                    <span className="text-xs text-gray-600 font-medium">
                      {source.speaker}
                    </span>
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
