import { useState, useEffect, useRef } from "react";
import axios from "axios";
import ReactMarkdown from "react-markdown";
import { useTransition, animated } from "react-spring";

interface Source {
  start_time: string;
  end_time: string;
  start: number;
  end: number;
  speaker: string;
  text?: string;
  screenshot_url?: string;
  type?: "text" | "visual";
}

interface Message {
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
}

interface ChatPanelProps {
  videoHash: string | null;
  onTimestampClick?: (timeString: string) => void;
}

interface LLMProvider {
  name: string;
  available: boolean;
  model: string;
}

export const ChatPanel: React.FC<ChatPanelProps> = ({
  videoHash,
  onTimestampClick,
}) => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [providers, setProviders] = useState<LLMProvider[]>([]);
  const [selectedProvider, setSelectedProvider] = useState<string>("ollama");
  const [includeVisuals, setIncludeVisuals] = useState(false);
  const [indexingStatus, setIndexingStatus] = useState<string | null>(null);
  const [expandedScreenshot, setExpandedScreenshot] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Message transitions
  const messageTransitions = useTransition(messages, {
    from: { opacity: 0, transform: "translate3d(0, 10px, 0)" },
    enter: { opacity: 1, transform: "translate3d(0, 0px, 0)" },
    keys: (item) => messages.indexOf(item),
    config: { tension: 220, friction: 20 },
  });

  // Load providers on mount
  useEffect(() => {
    loadProviders();
  }, []);

  // Auto-index when video hash changes
  useEffect(() => {
    if (videoHash) {
      indexVideo();
    }
  }, [videoHash]);

  // Scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const loadProviders = async () => {
    try {
      const response = await axios.get(
        "http://localhost:8000/api/llm/providers"
      );
      setProviders(response.data.providers);

      // Set default provider to first available one
      const availableProvider = response.data.providers.find(
        (p: LLMProvider) => p.available
      );
      if (availableProvider) {
        setSelectedProvider(availableProvider.name);
      }
    } catch (error) {
      console.error("Failed to load providers:", error);
    }
  };

  const indexVideo = async () => {
    if (!videoHash) return;

    setIndexingStatus("Indexing video for chat...");
    try {
      await axios.post("http://localhost:8000/api/index_video/", null, {
        params: { video_hash: videoHash },
      });
      setIndexingStatus("Video indexed successfully!");
      setTimeout(() => setIndexingStatus(null), 3000);
    } catch (error) {
      console.error("Failed to index video:", error);
      setIndexingStatus("Indexing failed (video may already be indexed)");
      setTimeout(() => setIndexingStatus(null), 3000);
    }
  };

  const sendMessage = async (messageText?: string | React.MouseEvent) => {
    const textToSend = typeof messageText === "string" ? messageText : input;
    if (!textToSend.trim() || !videoHash) return;

    const userMessage: Message = {
      role: "user",
      content: textToSend,
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setLoading(true);

    try {
      const response = await axios.post("http://localhost:8000/api/chat/", {
        question: textToSend,
        video_hash: videoHash,
        provider: selectedProvider,
        n_results: 8, // Increased for more comprehensive context
        include_visuals: includeVisuals,
        n_images: includeVisuals ? 3 : undefined,
      });

      const assistantMessage: Message = {
        role: "assistant",
        content: response.data.answer,
        sources: response.data.sources,
      };

      setMessages((prev) => [...prev, assistantMessage]);
    } catch (error: any) {
      console.error("Chat error:", error);
      const errorMessage: Message = {
        role: "assistant",
        content: `Error: ${
          error.response?.data?.detail ||
          error.message ||
          "Failed to get response"
        }`,
      };
      setMessages((prev) => [...prev, errorMessage]);
    } finally {
      setLoading(false);
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const quickQuestions = [
    "Summarize the key points",
    "What are the main topics discussed?",
    "Who are the speakers?",
    "What decisions were made?",
  ];

  if (!videoHash) {
    return (
      <div className="flex items-center justify-center h-full p-8">
        <div className="text-center text-gray-500">
          <svg
            className="w-16 h-16 mx-auto mb-4 text-gray-300"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z"
            />
          </svg>
          <p className="text-lg font-medium">No video loaded</p>
          <p className="text-sm mt-2">
            Upload and transcribe a video to start chatting
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full bg-white">
      {/* Header */}
      <div className="px-6 py-4 border-b border-gray-200 bg-gradient-to-r from-gray-50 to-white">
        <div className="flex flex-col gap-3">
          {/* Title Row */}
          <div>
            <h2 className="text-lg font-bold text-gray-900">Chat with Video</h2>
            <p className="text-xs text-gray-500 mt-0.5">
              Ask questions about the content
            </p>
          </div>

          {/* Controls Row */}
          <div className="flex items-center gap-3 flex-wrap">
            {/* Model Selector */}
            <div className="flex items-center gap-2">
              <label className="text-xs font-medium text-gray-600">
                Model:
              </label>
              <select
                value={selectedProvider}
                onChange={(e) => setSelectedProvider(e.target.value)}
                className="text-sm px-3 py-1.5 border border-gray-300 rounded-lg bg-white hover:bg-gray-50 focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-colors cursor-pointer"
                title="Select LLM Provider"
              >
                {providers.map((provider) => (
                  <option
                    key={provider.name}
                    value={provider.name}
                    disabled={!provider.available}
                  >
                    {provider.name} - {provider.model}{" "}
                    {!provider.available && "(unavailable)"}
                  </option>
                ))}
              </select>
            </div>

            {/* Divider */}
            <div className="h-6 w-px bg-gray-300"></div>

            {/* Visual Search Toggle */}
            <div className="relative group flex items-center gap-2">
              <button
                onClick={() => setIncludeVisuals(!includeVisuals)}
                className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${
                  includeVisuals
                    ? "bg-indigo-100 text-indigo-700 border-2 border-indigo-300"
                    : "bg-gray-100 text-gray-600 border-2 border-transparent hover:bg-gray-200"
                }`}
                aria-label={
                  includeVisuals
                    ? "Disable visual search"
                    : "Enable visual search"
                }
              >
                <svg
                  className="w-4 h-4"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  {includeVisuals ? (
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M15 12a3 3 0 11-6 0 3 3 0 016 0z M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"
                    />
                  ) : (
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21"
                    />
                  )}
                </svg>
                <span>Visual Search</span>
                {includeVisuals && (
                  <span className="ml-1 px-1.5 py-0.5 bg-indigo-200 text-indigo-800 text-xs rounded-full">
                    ON
                  </span>
                )}
              </button>

              {/* Info tooltip */}
              <div className="relative">
                <button
                  className="w-4 h-4 rounded-full bg-gray-200 hover:bg-gray-300 text-gray-600 flex items-center justify-center text-xs font-bold transition-colors"
                  title="Learn about Visual Search"
                  aria-label="Visual search information"
                >
                  ?
                </button>
                {/* Tooltip on hover */}
                <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 px-3 py-2 bg-gray-900 text-white text-xs rounded-lg opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none whitespace-nowrap z-10 shadow-lg min-w-max">
                  <div className="font-medium mb-1">Visual Search</div>
                  <div className="text-gray-300">Analyze video frames with AI vision</div>
                  <div className="text-gray-300">for visual context and details</div>
                  <svg
                    className="absolute top-full left-1/2 -translate-x-1/2 text-gray-900"
                    width="8"
                    height="4"
                    viewBox="0 0 8 4"
                  >
                    <path fill="currentColor" d="M0 0l4 4 4-4z" />
                  </svg>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Indexing Status */}
        {indexingStatus && (
          <div className="mt-3 px-3 py-2 bg-blue-50 border border-blue-200 rounded-lg flex items-center gap-2">
            {indexingStatus.includes("Indexing") && (
              <svg
                className="w-4 h-4 text-blue-600 animate-spin"
                fill="none"
                viewBox="0 0 24 24"
              >
                <circle
                  className="opacity-25"
                  cx="12"
                  cy="12"
                  r="10"
                  stroke="currentColor"
                  strokeWidth="4"
                />
                <path
                  className="opacity-75"
                  fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                />
              </svg>
            )}
            {indexingStatus.includes("successfully") && (
              <svg
                className="w-4 h-4 text-green-600"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M5 13l4 4L19 7"
                />
              </svg>
            )}
            {indexingStatus.includes("failed") && (
              <svg
                className="w-4 h-4 text-amber-600"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
                />
              </svg>
            )}
            <p className={`text-sm ${
              indexingStatus.includes("successfully")
                ? "text-green-700"
                : indexingStatus.includes("failed")
                ? "text-amber-700"
                : "text-blue-700"
            }`}>
              {indexingStatus}
            </p>
          </div>
        )}
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-6 space-y-4">
        {messages.length === 0 && (
          <div className="text-center py-8">
            <p className="text-gray-500 mb-4">Start a conversation!</p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-w-2xl mx-auto">
              {quickQuestions.map((question, index) => (
                <button
                  key={index}
                  onClick={() => sendMessage(question)}
                  className="px-4 py-2 text-sm text-left bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors"
                >
                  {question}
                </button>
              ))}
            </div>
          </div>
        )}

        {messageTransitions((style, message) => (
          <animated.div
            style={style}
            className={`flex ${
              message.role === "user" ? "justify-end" : "justify-start"
            }`}
          >
            <div
              className={`max-w-3xl px-4 py-3 rounded-lg ${
                message.role === "user"
                  ? "bg-indigo-600 text-white"
                  : "bg-gray-100 text-gray-900"
              }`}
            >
              <div className="prose prose-sm max-w-none prose-headings:font-bold prose-p:text-gray-800 prose-ul:text-gray-800 prose-li:text-gray-800">
                <ReactMarkdown>{message.content}</ReactMarkdown>
              </div>

              {/* Sources */}
              {message.sources && message.sources.length > 0 && (
                <div className="mt-4 space-y-3">
                  {/* Visual Sources (Screenshots) */}
                  {message.sources.filter((s) => s.type === "visual").length > 0 && (
                    <div className="bg-gradient-to-br from-purple-50 to-indigo-50 rounded-lg p-3 border border-purple-200">
                      <div className="flex items-center gap-2 mb-3">
                        <svg className="w-4 h-4 text-purple-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
                        </svg>
                        <p className="text-xs font-bold text-purple-900 uppercase tracking-wide">
                          Visual Analysis
                        </p>
                      </div>
                      <div className="grid grid-cols-3 gap-2">
                        {message.sources
                          .filter((s) => s.type === "visual")
                          .map((source, idx) => (
                            <button
                              key={idx}
                              onClick={() => {
                                if (source.screenshot_url) {
                                  setExpandedScreenshot(
                                    `http://localhost:8000${source.screenshot_url}`
                                  );
                                }
                              }}
                              className="group relative aspect-video bg-white rounded-lg overflow-hidden border-2 border-purple-200 hover:border-purple-400 transition-all hover:shadow-lg cursor-pointer"
                            >
                              <img
                                src={`http://localhost:8000${source.screenshot_url}`}
                                alt={`Screenshot at ${source.start_time}`}
                                className="w-full h-full object-cover"
                                onError={(e) => {
                                  (e.target as HTMLImageElement).src =
                                    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='100' height='100'%3E%3Crect fill='%23f3f4f6' width='100' height='100'/%3E%3Ctext x='50%25' y='50%25' dominant-baseline='middle' text-anchor='middle' fill='%239ca3af' font-size='12'%3ENo Image%3C/text%3E%3C/svg%3E";
                                }}
                              />
                              {/* Hover overlay */}
                              <div className="absolute inset-0 bg-black bg-opacity-0 group-hover:bg-opacity-40 transition-all flex items-center justify-center">
                                <svg className="w-8 h-8 text-white opacity-0 group-hover:opacity-100 transition-opacity" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0zM10 7v3m0 0v3m0-3h3m-3 0H7" />
                                </svg>
                              </div>
                              {/* Timestamp badge */}
                              <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/80 to-transparent p-2">
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    onTimestampClick?.(source.start_time);
                                  }}
                                  className="text-white text-xs font-mono font-bold hover:text-purple-300 transition-colors"
                                >
                                  {source.start_time}
                                </button>
                                <p className="text-white/80 text-xs truncate">
                                  {source.speaker}
                                </p>
                              </div>
                            </button>
                          ))}
                      </div>
                    </div>
                  )}

                  {/* Text Sources (Transcript) */}
                  {message.sources.filter((s) => !s.type || s.type === "text").length > 0 && (
                    <div className="bg-gradient-to-br from-blue-50 to-cyan-50 rounded-lg p-3 border border-blue-200">
                      <div className="flex items-center gap-2 mb-2">
                        <svg className="w-4 h-4 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                        </svg>
                        <p className="text-xs font-bold text-blue-900 uppercase tracking-wide">
                          Transcript Sources
                        </p>
                      </div>
                      <div className="space-y-1.5">
                        {message.sources
                          .filter((s) => !s.type || s.type === "text")
                          .map((source, idx) => (
                            <button
                              key={idx}
                              onClick={() => onTimestampClick?.(source.start_time)}
                              className="block w-full text-left text-xs px-3 py-2 bg-white hover:bg-blue-50 rounded-lg border border-blue-200 hover:border-blue-300 transition-all hover:shadow-sm group"
                            >
                              <div className="flex items-center justify-between mb-1">
                                <span className="font-mono font-bold text-blue-700 group-hover:text-blue-800">
                                  {source.start_time} - {source.end_time}
                                </span>
                                <span className="text-gray-600 font-medium">
                                  {source.speaker}
                                </span>
                              </div>
                              {source.text && (
                                <p className="text-gray-600 line-clamp-2 leading-relaxed">
                                  {source.text}
                                </p>
                              )}
                            </button>
                          ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          </animated.div>
        ))}

        {loading && (
          <div className="flex justify-start">
            <div className="bg-gray-100 px-4 py-3 rounded-lg">
              <div className="flex items-center space-x-2">
                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce"></div>
                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce delay-100"></div>
                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce delay-200"></div>
              </div>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="px-6 py-4 border-t border-gray-200 bg-gray-50">
        <div className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyPress}
            placeholder="Ask a question about the video..."
            className="flex-1 px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
            disabled={loading}
          />
          <button
            onClick={sendMessage}
            disabled={loading || !input.trim()}
            className="px-6 py-3 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors font-medium"
          >
            <svg
              className="w-5 h-5 transform rotate-90"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"
              />
            </svg>
          </button>
        </div>
      </div>

      {/* Screenshot Modal */}
      {expandedScreenshot && (
        <div
          className="fixed inset-0 bg-black bg-opacity-90 z-50 flex items-center justify-center p-4"
          onClick={() => setExpandedScreenshot(null)}
        >
          <div className="relative max-w-6xl max-h-full">
            <button
              onClick={() => setExpandedScreenshot(null)}
              className="absolute -top-12 right-0 text-white hover:text-gray-300 transition-colors"
              aria-label="Close screenshot"
            >
              <svg className="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
            <img
              src={expandedScreenshot}
              alt="Expanded screenshot"
              className="max-w-full max-h-[90vh] object-contain rounded-lg shadow-2xl"
              onClick={(e) => e.stopPropagation()}
            />
          </div>
        </div>
      )}
    </div>
  );
};
