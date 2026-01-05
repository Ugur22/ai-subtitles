import { useState, useEffect, useRef } from "react";
import axios from "axios";
import ReactMarkdown from "react-markdown";
import { useTransition, animated } from "react-spring";
import { API_BASE_URL } from "../../../config";
import { formatScreenshotUrlSafe } from "../../../utils/url";

// Alias for backward compatibility within this file
const formatScreenshotUrl = formatScreenshotUrlSafe;

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
  likely_speakers?: string[];
  overlap_score?: number;
}

interface Message {
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
  visual_query_used?: string;
  original_question?: string;
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

// Helper function to get emoji, label, and category for audio event types
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
        icon: 'text-purple-600',
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
        icon: 'text-blue-600',
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
        icon: 'text-emerald-600',
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
        icon: 'text-amber-600',
      };
  }
};

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
  const [screenshotModal, setScreenshotModal] = useState<{ screenshots: string[], currentIndex: number, sources: Source[] } | null>(null);
  const [customInstructions, setCustomInstructions] = useState<string>("");
  const [showCustomInstructions, setShowCustomInstructions] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Message transitions
  const messageTransitions = useTransition(messages, {
    from: { opacity: 0, transform: "translate3d(0, 10px, 0)" },
    enter: { opacity: 1, transform: "translate3d(0, 0px, 0)" },
    keys: (item) => messages.indexOf(item),
    config: { tension: 220, friction: 20 },
  });

  // Screenshot modal keyboard navigation
  useEffect(() => {
    if (!screenshotModal) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setScreenshotModal(null);
      } else if (e.key === "ArrowLeft" && screenshotModal.currentIndex > 0) {
        setScreenshotModal({ ...screenshotModal, currentIndex: screenshotModal.currentIndex - 1 });
      } else if (e.key === "ArrowRight" && screenshotModal.currentIndex < screenshotModal.screenshots.length - 1) {
        setScreenshotModal({ ...screenshotModal, currentIndex: screenshotModal.currentIndex + 1 });
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [screenshotModal]);

  const handlePreviousScreenshot = () => {
    if (screenshotModal && screenshotModal.currentIndex > 0) {
      setScreenshotModal({ ...screenshotModal, currentIndex: screenshotModal.currentIndex - 1 });
    }
  };

  const handleNextScreenshot = () => {
    if (screenshotModal && screenshotModal.currentIndex < screenshotModal.screenshots.length - 1) {
      setScreenshotModal({ ...screenshotModal, currentIndex: screenshotModal.currentIndex + 1 });
    }
  };

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
        `${API_BASE_URL}/api/llm/providers`
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
      // Index text transcription
      await axios.post(`${API_BASE_URL}/api/index_video/`, null, {
        params: { video_hash: videoHash },
      });

      // Index images for visual search
      try {
        await axios.post(`${API_BASE_URL}/api/index_images/`, null, {
          params: { video_hash: videoHash },
        });
        setIndexingStatus("Video and images indexed successfully!");
      } catch (imageError) {
        console.warn("Failed to index images:", imageError);
        setIndexingStatus("Video indexed (images indexing skipped)");
      }

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
      const response = await axios.post(`${API_BASE_URL}/api/chat/`, {
        question: textToSend,
        video_hash: videoHash,
        provider: selectedProvider,
        n_results: 8, // Increased for more comprehensive context
        include_visuals: includeVisuals,
        n_images: includeVisuals ? 6 : undefined,
        custom_instructions: customInstructions || undefined,
      });

      const assistantMessage: Message = {
        role: "assistant",
        content: response.data.answer,
        sources: response.data.sources,
        visual_query_used: response.data.visual_query_used,
        original_question: textToSend,
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
                    ? "Disable scene search"
                    : "Enable scene search"
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
                <span>Scene Search</span>
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
                  title="Scene Search finds visual moments (actions, objects, settings). Cannot identify specific people by name - use transcript for speaker queries."
                  aria-label="Scene search information"
                >
                  ?
                </button>
                {/* Tooltip on hover */}
                <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 px-3 py-2 bg-gray-900 text-white text-xs rounded-lg opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none w-64 z-10 shadow-lg">
                  <div className="font-medium mb-1.5">Scene Search</div>
                  <div className="text-gray-300 mb-1">Finds visual moments (actions, objects, settings).</div>
                  <div className="text-gray-300">Cannot identify specific people by name - use transcript for speaker queries.</div>
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
            className={`flex flex-col gap-2 ${
              message.role === "user" ? "items-end" : "items-start"
            }`}
          >
            {/* Show query transformation notification for assistant messages */}
            {message.role === "assistant" &&
             message.visual_query_used &&
             message.original_question &&
             message.visual_query_used !== message.original_question && (
              <div className="max-w-3xl px-3 py-2 bg-blue-50 border border-blue-200 rounded-lg text-xs text-gray-700 flex items-start gap-2">
                <span className="text-sm">💡</span>
                <div>
                  <span className="font-medium">Scene search:</span> "{message.visual_query_used}"
                </div>
              </div>
            )}

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
                  {message.sources.filter((s) => s.screenshot_url).length > 0 && (
                    <div className="bg-gradient-to-br from-purple-50 to-indigo-50 rounded-lg p-3 border border-purple-200">
                      <div className="flex items-center gap-2 mb-3">
                        <span className="text-base">🎨</span>
                        <p className="text-xs font-bold text-purple-900 uppercase tracking-wide">
                          Scene Matches
                        </p>
                      </div>
                      <div className="grid grid-cols-3 gap-2">
                        {message.sources
                          .filter((s) => s.screenshot_url)
                          .map((source, idx) => (
                            <button
                              key={idx}
                              onClick={() => {
                                if (source.screenshot_url) {
                                  const visualSources = message.sources!.filter((s) => s.screenshot_url);
                                  const screenshots = visualSources.map((s) => formatScreenshotUrl(s.screenshot_url));
                                  setScreenshotModal({ screenshots, currentIndex: idx, sources: visualSources });
                                }
                              }}
                              className="group relative aspect-video bg-white rounded-lg overflow-hidden border-2 border-purple-200 hover:border-purple-400 transition-all hover:shadow-lg cursor-pointer"
                            >
                              <img
                                src={formatScreenshotUrl(source.screenshot_url)}
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
                              {/* Timestamp and speaker info badge */}
                              <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/90 via-black/60 to-transparent p-2">
                                <span
                                  role="button"
                                  tabIndex={0}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    onTimestampClick?.(source.start_time);
                                  }}
                                  onKeyDown={(e) => {
                                    if (e.key === 'Enter' || e.key === ' ') {
                                      e.stopPropagation();
                                      onTimestampClick?.(source.start_time);
                                    }
                                  }}
                                  className="text-white text-xs font-mono font-bold hover:text-purple-300 transition-colors cursor-pointer block mb-0.5"
                                >
                                  {source.start_time}
                                </span>
                                {(source as any).likely_speakers && (source as any).likely_speakers.length > 0 ? (
                                  <p className="text-white/90 text-xs truncate">
                                    Likely: {(source as any).likely_speakers.join(", ")}
                                  </p>
                                ) : (
                                  <p className="text-white/80 text-xs truncate">
                                    {source.speaker}
                                  </p>
                                )}
                              </div>
                            </button>
                          ))}
                      </div>
                    </div>
                  )}

                  {/* Text Sources (Transcript) */}
                  {message.sources.filter((s) => !s.screenshot_url && s.type !== "audio").length > 0 && (
                    <div className="bg-gradient-to-br from-blue-50 to-cyan-50 rounded-lg p-3 border border-blue-200">
                      <div className="flex items-center gap-2 mb-2">
                        <span className="text-base">📝</span>
                        <p className="text-xs font-bold text-blue-900 uppercase tracking-wide">
                          From Transcript
                        </p>
                      </div>
                      <div className="space-y-1.5">
                        {message.sources
                          .filter((s) => !s.screenshot_url && s.type !== "audio")
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

                  {/* Audio Events */}
                  {message.sources.filter((s) => s.type === "audio").length > 0 && (
                    <div className="bg-gradient-to-br from-gray-50 to-slate-50 rounded-lg p-4 border border-gray-200">
                      <div className="flex items-center justify-between mb-4">
                        <div className="flex items-center gap-2">
                          <div className="p-2 bg-gradient-to-br from-indigo-100 to-purple-100 rounded-lg">
                            <svg className="w-5 h-5 text-indigo-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.536 8.464a5 5 0 010 7.072m2.828-9.9a9 9 0 010 12.728M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z" />
                            </svg>
                          </div>
                          <div>
                            <p className="text-sm font-bold text-gray-900">
                              Audio Events Detected
                            </p>
                            <p className="text-xs text-gray-500">
                              {message.sources.filter((s) => s.type === "audio").length} events found
                            </p>
                          </div>
                        </div>
                      </div>
                      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                        {message.sources
                          .filter((s) => s.type === "audio")
                          .map((source, idx) => {
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
        {/* Custom Instructions Section */}
        <div className="mb-3">
          <button
            onClick={() => setShowCustomInstructions(!showCustomInstructions)}
            className="flex items-center gap-2 text-sm font-medium text-gray-700 hover:text-gray-900 transition-colors"
            aria-expanded={showCustomInstructions}
            aria-label="Toggle custom instructions"
          >
            <svg
              className={`w-4 h-4 transition-transform ${showCustomInstructions ? 'rotate-90' : ''}`}
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
            <svg
              className="w-4 h-4"
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
            <span>Custom Instructions</span>
            {customInstructions && (
              <span className="ml-1 px-2 py-0.5 bg-indigo-100 text-indigo-700 text-xs rounded-full font-semibold">
                Active
              </span>
            )}
          </button>

          {showCustomInstructions && (
            <div className="mt-3 bg-white rounded-lg border border-gray-300 p-3">
              <textarea
                value={customInstructions}
                onChange={(e) => setCustomInstructions(e.target.value)}
                placeholder="Add custom instructions for the AI (e.g., 'Respond in Spanish', 'Be brief and casual', 'Focus on technical details')..."
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-transparent resize-none text-sm"
                rows={3}
                disabled={loading}
              />
              <p className="mt-2 text-xs text-gray-500">
                These instructions will be applied to all your questions. They persist across messages.
              </p>
            </div>
          )}
        </div>

        {/* Chat Input */}
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

      {/* Screenshot Modal with Slideshow */}
      {screenshotModal && (
        <div
          className="fixed inset-0 bg-black bg-opacity-90 z-50 flex items-center justify-center p-4"
          onClick={() => setScreenshotModal(null)}
        >
          <div className="relative max-w-6xl max-h-full" onClick={(e) => e.stopPropagation()}>
            {/* Close Button */}
            <button
              onClick={() => setScreenshotModal(null)}
              className="absolute top-2 right-2 z-10 w-10 h-10 bg-white bg-opacity-20 hover:bg-opacity-30 text-white rounded-full flex items-center justify-center backdrop-blur-sm transition-all"
              aria-label="Close screenshot"
            >
              <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>

            {/* Image Counter */}
            <div className="absolute top-2 left-2 z-10 px-3 py-1.5 bg-black bg-opacity-60 text-white text-sm font-medium rounded-full backdrop-blur-sm">
              {screenshotModal.currentIndex + 1} of {screenshotModal.screenshots.length}
            </div>

            {/* Main Image */}
            <img
              src={screenshotModal.screenshots[screenshotModal.currentIndex]}
              alt="Expanded screenshot"
              className="max-w-full max-h-[90vh] object-contain rounded-lg shadow-2xl"
            />

            {/* Previous Button */}
            {screenshotModal.currentIndex > 0 && (
              <button
                onClick={handlePreviousScreenshot}
                className="absolute left-2 top-1/2 -translate-y-1/2 w-12 h-12 bg-white bg-opacity-20 hover:bg-opacity-40 text-white rounded-full flex items-center justify-center backdrop-blur-sm transition-all opacity-50 hover:opacity-100"
                aria-label="Previous image"
              >
                <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M15 19l-7-7 7-7" />
                </svg>
              </button>
            )}

            {/* Next Button */}
            {screenshotModal.currentIndex < screenshotModal.screenshots.length - 1 && (
              <button
                onClick={handleNextScreenshot}
                className="absolute right-2 top-1/2 -translate-y-1/2 w-12 h-12 bg-white bg-opacity-20 hover:bg-opacity-40 text-white rounded-full flex items-center justify-center backdrop-blur-sm transition-all opacity-50 hover:opacity-100"
                aria-label="Next image"
              >
                <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M9 5l7 7-7 7" />
                </svg>
              </button>
            )}

            {/* Timestamp and Speaker Info */}
            {screenshotModal.sources[screenshotModal.currentIndex] && (
              <div className="absolute bottom-2 left-1/2 -translate-x-1/2 px-4 py-2 bg-black bg-opacity-60 text-white rounded-lg backdrop-blur-sm text-center">
                <button
                  onClick={() => onTimestampClick?.(screenshotModal.sources[screenshotModal.currentIndex].start_time)}
                  className="text-sm font-mono font-bold hover:text-purple-300 transition-colors"
                  title="Click to jump to this timestamp"
                >
                  {screenshotModal.sources[screenshotModal.currentIndex].start_time}
                </button>
                {(screenshotModal.sources[screenshotModal.currentIndex] as any).likely_speakers?.length > 0 && (
                  <p className="text-xs text-white/90 mt-1">
                    Likely: {(screenshotModal.sources[screenshotModal.currentIndex] as any).likely_speakers.join(", ")}
                  </p>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
