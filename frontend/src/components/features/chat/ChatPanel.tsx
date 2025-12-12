import { useState, useEffect, useRef } from "react";
import axios from "axios";
import ReactMarkdown from "react-markdown";

interface Message {
  role: "user" | "assistant";
  content: string;
  sources?: {
    start_time: string;
    end_time: string;
    start: number;
    end: number;
    speaker: string;
    text: string;
  }[];
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
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [indexingStatus, setIndexingStatus] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

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
      const response = await axios.get("http://localhost:8000/api/llm/providers");
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

  const sendMessage = async () => {
    if (!input.trim() || !videoHash) return;

    const userMessage: Message = {
      role: "user",
      content: input,
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setLoading(true);

    try {
      const response = await axios.post("http://localhost:8000/api/chat/", {
        question: input,
        video_hash: videoHash,
        provider: selectedProvider,
        n_results: 5,
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
        content: `Error: ${error.response?.data?.detail || error.message || "Failed to get response"}`,
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

  const parseTimestampFromText = (text: string): number | null => {
    // Match timestamps in format HH:MM:SS or MM:SS
    const match = text.match(/(\d{1,2}):(\d{2}):(\d{2})|(\d{1,2}):(\d{2})/);
    if (!match) return null;

    if (match[1] && match[2] && match[3]) {
      // HH:MM:SS format
      return parseInt(match[1]) * 3600 + parseInt(match[2]) * 60 + parseInt(match[3]);
    } else if (match[4] && match[5]) {
      // MM:SS format
      return parseInt(match[4]) * 60 + parseInt(match[5]);
    }
    return null;
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
          <p className="text-sm mt-2">Upload and transcribe a video to start chatting</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full bg-white">
      {/* Header */}
      <div className="px-6 py-4 border-b border-gray-200 bg-gradient-to-r from-gray-50 to-white">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-bold text-gray-900">Chat with Video</h2>
            <p className="text-xs text-gray-500 mt-1">
              Ask questions about the content
            </p>
          </div>
          <button
            onClick={() => setSettingsOpen(!settingsOpen)}
            className="p-2 rounded-lg hover:bg-gray-100 transition-colors"
            title="Settings"
          >
            <svg
              className="w-5 h-5 text-gray-600"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"
              />
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"
              />
            </svg>
          </button>
        </div>

        {/* Settings Panel */}
        {settingsOpen && (
          <div className="mt-4 p-4 bg-gray-50 rounded-lg border border-gray-200">
            <label className="block text-sm font-medium text-gray-700 mb-2">
              LLM Provider
            </label>
            <select
              value={selectedProvider}
              onChange={(e) => setSelectedProvider(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
            >
              {providers.map((provider) => (
                <option
                  key={provider.name}
                  value={provider.name}
                  disabled={!provider.available}
                >
                  {provider.name} - {provider.model} {!provider.available && "(unavailable)"}
                </option>
              ))}
            </select>
            <p className="text-xs text-gray-500 mt-2">
              Selected: <span className="font-medium">{selectedProvider}</span>
            </p>
          </div>
        )}

        {/* Indexing Status */}
        {indexingStatus && (
          <div className="mt-3 px-3 py-2 bg-blue-50 border border-blue-200 rounded-lg">
            <p className="text-sm text-blue-700">{indexingStatus}</p>
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
                  onClick={() => setInput(question)}
                  className="px-4 py-2 text-sm text-left bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors"
                >
                  {question}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((message, index) => (
          <div
            key={index}
            className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-3xl px-4 py-3 rounded-lg ${
                message.role === "user"
                  ? "bg-indigo-600 text-white"
                  : "bg-gray-100 text-gray-900"
              }`}
            >
              <ReactMarkdown className="prose prose-sm max-w-none">
                {message.content}
              </ReactMarkdown>

              {/* Sources */}
              {message.sources && message.sources.length > 0 && (
                <div className="mt-3 pt-3 border-t border-gray-200">
                  <p className="text-xs font-semibold text-gray-700 mb-2">Sources:</p>
                  <div className="space-y-1">
                    {message.sources.map((source, idx) => (
                      <button
                        key={idx}
                        onClick={() => onTimestampClick?.(source.start_time)}
                        className="block w-full text-left text-xs px-2 py-1 bg-white hover:bg-gray-50 rounded border border-gray-200 transition-colors"
                      >
                        <span className="font-medium text-indigo-600">
                          [{source.start_time} - {source.end_time}]
                        </span>
                        <span className="text-gray-600 ml-2">{source.speaker}</span>
                        <p className="text-gray-500 mt-1 line-clamp-2">{source.text}</p>
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
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
            onKeyPress={handleKeyPress}
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
              className="w-5 h-5"
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
    </div>
  );
};
