import { useState, useEffect, useRef, useMemo } from "react";
import axios from "axios";
import ReactMarkdown, { Components } from "react-markdown";
import { useTransition, animated } from "react-spring";
import {
  Disclosure,
  DisclosureButton,
  DisclosurePanel,
} from "@headlessui/react";
import { API_BASE_URL } from "../../../config";
import { formatScreenshotUrlSafe } from "../../../utils/url";
import { listSpeakers, getFaceTagSpeakers } from "../../../services/api";
import { useSpeechRecognition } from "../../../hooks/useSpeechRecognition";

// Alias for backward compatibility within this file
const formatScreenshotUrl = formatScreenshotUrlSafe;

// Timestamp pattern: [HH:MM:SS] or [HH:MM:SS - HH:MM:SS]
const TIMESTAMP_REGEX =
  /\[(\d{1,2}:\d{2}:\d{2})(?:\s*-\s*(\d{1,2}:\d{2}:\d{2}))?\]/g;

// Section icon map for h2 headings
const SECTION_ICONS: Record<string, string> = {
  "direct answer": "sparkles",
  "key analysis": "magnifying-glass",
  analysis: "magnifying-glass",
  "visual observations": "eye",
  visual: "eye",
  summary: "document-text",
  context: "information-circle",
  speaker: "user",
  timeline: "clock",
  audio: "speaker-wave",
};

function getSectionIcon(heading: string): React.ReactNode {
  const lower = heading.toLowerCase();
  for (const [key, icon] of Object.entries(SECTION_ICONS)) {
    if (lower.includes(key)) {
      const iconMap: Record<string, React.ReactNode> = {
        sparkles: (
          <svg
            className="w-4 h-4"
            style={{ color: "var(--accent)" }}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z"
            />
          </svg>
        ),
        "magnifying-glass": (
          <svg
            className="w-4 h-4"
            style={{ color: "var(--accent)" }}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
            />
          </svg>
        ),
        eye: (
          <svg
            className="w-4 h-4"
            style={{ color: "var(--accent)" }}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"
            />
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"
            />
          </svg>
        ),
        "document-text": (
          <svg
            className="w-4 h-4"
            style={{ color: "var(--accent)" }}
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
        ),
        "information-circle": (
          <svg
            className="w-4 h-4"
            style={{ color: "var(--accent)" }}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
            />
          </svg>
        ),
        user: (
          <svg
            className="w-4 h-4"
            style={{ color: "var(--accent)" }}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"
            />
          </svg>
        ),
        clock: (
          <svg
            className="w-4 h-4"
            style={{ color: "var(--accent)" }}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"
            />
          </svg>
        ),
        "speaker-wave": (
          <svg
            className="w-4 h-4"
            style={{ color: "var(--accent)" }}
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
        ),
      };
      return iconMap[icon] || null;
    }
  }
  return null;
}

/** Render text with timestamp badges inline */
function renderWithTimestamps(
  text: string,
  onTimestampClick?: (ts: string) => void,
): React.ReactNode[] {
  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  const regex = new RegExp(TIMESTAMP_REGEX.source, "g");

  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }
    const startTs = match[1];
    const endTs = match[2];
    const label = endTs ? `${startTs} - ${endTs}` : startTs;
    parts.push(
      <button
        key={`ts-${match.index}`}
        onClick={() => onTimestampClick?.(startTs)}
        className="inline-flex items-center gap-0.5 px-1.5 py-0.5 mx-0.5 text-xs font-mono font-semibold rounded-md transition-colors cursor-pointer align-baseline"
        style={{ background: "var(--accent-dim)", color: "var(--accent)" }}
      >
        <svg
          className="w-3 h-3"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"
          />
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
          />
        </svg>
        {label}
      </button>,
    );
    lastIndex = regex.lastIndex;
  }
  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }
  return parts;
}

/** Process children nodes to inject timestamp badges */
function processChildren(
  children: React.ReactNode,
  onTimestampClick?: (ts: string) => void,
): React.ReactNode {
  if (typeof children === "string") {
    return renderWithTimestamps(children, onTimestampClick);
  }
  if (Array.isArray(children)) {
    return children.map((child, i) =>
      typeof child === "string" ? (
        <span key={i}>{renderWithTimestamps(child, onTimestampClick)}</span>
      ) : (
        child
      ),
    );
  }
  return children;
}

/** Split markdown content into sections by ## headings */
function splitIntoSections(
  content: string,
): { heading: string; body: string }[] {
  const lines = content.split("\n");
  const sections: { heading: string; body: string }[] = [];
  let currentHeading = "";
  let currentBody: string[] = [];

  const flush = () => {
    if (currentHeading || currentBody.length > 0) {
      sections.push({
        heading: currentHeading,
        body: currentBody.join("\n").trim(),
      });
    }
  };

  // Accept a few heading styles the LLM sometimes emits:
  //   ## Heading        (canonical)
  //   ### Heading       (deeper level)
  //   **Heading**       or **Heading:** on its own line
  const headingPatterns: RegExp[] = [
    /^\s*#{2,6}\s+(.+?)\s*:?\s*$/,
    /^\s*\*\*(.+?)\*\*\s*:?\s*$/,
  ];

  for (const line of lines) {
    let heading: string | null = null;
    for (const re of headingPatterns) {
      const m = line.match(re);
      if (m) {
        heading = m[1].replace(/:$/, "").trim();
        break;
      }
    }
    if (heading) {
      flush();
      currentHeading = heading;
      currentBody = [];
    } else {
      currentBody.push(line);
    }
  }
  flush();
  return sections;
}

/** Build custom ReactMarkdown renderers */
function buildMarkdownComponents(
  onTimestampClick?: (ts: string) => void,
): Components {
  return {
    h2({ children }) {
      const text = typeof children === "string" ? children : String(children);
      const icon = getSectionIcon(text);
      return (
        <h2
          className="flex items-center gap-2 text-base font-bold mt-5 mb-2 pb-1.5 border-b"
          style={{ color: "var(--text-primary)", borderColor: "var(--border-subtle)" }}
        >
          {icon}
          <span>{children}</span>
        </h2>
      );
    },
    h3({ children }) {
      return (
        <h3 className="text-sm font-semibold mt-3 mb-1" style={{ color: "var(--text-primary)" }}>
          {children}
        </h3>
      );
    },
    p({ children }) {
      return (
        <p className="text-sm my-1.5 leading-relaxed" style={{ color: "var(--text-primary)" }}>
          {processChildren(children, onTimestampClick)}
        </p>
      );
    },
    li({ children }) {
      return (
        <li className="text-sm leading-relaxed" style={{ color: "var(--text-primary)" }}>
          {processChildren(children, onTimestampClick)}
        </li>
      );
    },
    blockquote({ children }) {
      return (
        <blockquote
          className="border-l-4 rounded-r-lg px-4 py-2 my-3 not-italic"
          style={{ borderLeftColor: "var(--accent)", background: "var(--accent-dim)" }}
        >
          {children}
        </blockquote>
      );
    },
    strong({ children }) {
      return (
        <strong className="font-semibold" style={{ color: "var(--text-primary)" }}>{children}</strong>
      );
    },
  };
}

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
  isError?: boolean;
  errorType?: "timeout" | "server" | "network" | "unknown";
  retryQuestion?: string;
  isStreaming?: boolean;
}

type PhaseId =
  | "searching"
  | "analyzing_scenes"
  | "matching_faces"
  | "analyzing_audio"
  | "generating";

interface PhaseEntry {
  id: PhaseId;
  label: string;
  status: "active" | "done";
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
  if (type.includes("happy") || type.includes("joy")) {
    return { emoji: "😊", label: "Happy", category: "emotion" };
  }
  if (type.includes("sad") || type.includes("sadness")) {
    return { emoji: "😢", label: "Sad", category: "emotion" };
  }
  if (type.includes("angry") || type.includes("anger")) {
    return { emoji: "😠", label: "Angry", category: "emotion" };
  }
  if (type.includes("fear") || type.includes("scared")) {
    return { emoji: "😨", label: "Fearful", category: "emotion" };
  }
  if (type.includes("neutral") || type.includes("calm")) {
    return { emoji: "😐", label: "Neutral", category: "emotion" };
  }
  if (type.includes("surprise")) {
    return { emoji: "😲", label: "Surprised", category: "emotion" };
  }
  if (type.includes("disgust")) {
    return { emoji: "🤢", label: "Disgust", category: "emotion" };
  }

  // Vocal expressions and reactions - Speech category
  if (type.includes("sigh")) {
    return { emoji: "😮‍💨", label: "Sigh", category: "speech" };
  }
  if (type.includes("gasp")) {
    return { emoji: "😮", label: "Gasp", category: "speech" };
  }
  if (type.includes("moan")) {
    return { emoji: "😩", label: "Moan", category: "speech" };
  }
  if (type.includes("groan")) {
    return { emoji: "😫", label: "Groan", category: "speech" };
  }
  if (type.includes("panting")) {
    return { emoji: "😤", label: "Panting", category: "speech" };
  }
  if (type.includes("huff") || type.includes("huffing")) {
    return { emoji: "😤", label: "Huffing", category: "speech" };
  }
  if (type.includes("scream")) {
    return { emoji: "😱", label: "Scream", category: "speech" };
  }
  if (type.includes("whimper")) {
    return { emoji: "🥺", label: "Whimper", category: "speech" };
  }
  if (type.includes("sniff") || type.includes("sniffle")) {
    return { emoji: "🤧", label: "Sniffling", category: "speech" };
  }
  if (type.includes("yawn")) {
    return { emoji: "🥱", label: "Yawn", category: "speech" };
  }
  if (type.includes("sneeze")) {
    return { emoji: "🤧", label: "Sneeze", category: "speech" };
  }
  if (type.includes("cough")) {
    return { emoji: "🤒", label: "Cough", category: "speech" };
  }
  if (type.includes("hiccup")) {
    return { emoji: "😯", label: "Hiccup", category: "speech" };
  }

  // Breathing sounds - Speech category
  if (type.includes("breath") || type.includes("breathing")) {
    return { emoji: "💨", label: "Breathing", category: "speech" };
  }
  if (type.includes("exhale")) {
    return { emoji: "😮‍💨", label: "Exhale", category: "speech" };
  }
  if (type.includes("inhale")) {
    return { emoji: "😤", label: "Inhale", category: "speech" };
  }

  // Speech and vocalizations - Speech category
  if (
    type.includes("speech") ||
    type.includes("speaking") ||
    type.includes("narration")
  ) {
    return { emoji: "🗣️", label: "Speech", category: "speech" };
  }
  if (type.includes("laugh")) {
    return { emoji: "😂", label: "Laughter", category: "speech" };
  }
  if (type.includes("giggle") || type.includes("chuckle")) {
    return { emoji: "😄", label: "Giggling", category: "speech" };
  }
  if (type.includes("cry") || type.includes("sobbing")) {
    return { emoji: "😭", label: "Crying", category: "speech" };
  }
  if (type.includes("shout") || type.includes("yell")) {
    return { emoji: "📢", label: "Shouting", category: "speech" };
  }
  if (type.includes("whisper")) {
    return { emoji: "🤫", label: "Whisper", category: "speech" };
  }
  if (type.includes("cheer")) {
    return { emoji: "🎉", label: "Cheering", category: "speech" };
  }
  if (type.includes("hum") || type.includes("humming")) {
    return { emoji: "🎵", label: "Humming", category: "speech" };
  }
  if (type.includes("sing")) {
    return { emoji: "🎤", label: "Singing", category: "speech" };
  }

  // Body sounds - Sound category
  if (type.includes("clap") || type.includes("applause")) {
    return { emoji: "👏", label: "Applause", category: "sound" };
  }
  if (type.includes("snap") || type.includes("finger snap")) {
    return { emoji: "👆", label: "Snap", category: "sound" };
  }
  if (type.includes("footstep") || type.includes("step")) {
    return { emoji: "👣", label: "Footsteps", category: "sound" };
  }
  if (type.includes("knock")) {
    return { emoji: "🚪", label: "Knocking", category: "sound" };
  }
  if (type.includes("tap") || type.includes("tapping")) {
    return { emoji: "👆", label: "Tapping", category: "sound" };
  }
  if (type.includes("stomp")) {
    return { emoji: "🦶", label: "Stomping", category: "sound" };
  }

  // Music and audio - Sound category
  if (type.includes("music") || type.includes("melody")) {
    return { emoji: "🎵", label: "Music", category: "sound" };
  }
  if (
    type.includes("silence") ||
    type.includes("ambient") ||
    type.includes("quiet")
  ) {
    return { emoji: "🔇", label: "Silence", category: "sound" };
  }
  if (type.includes("noise")) {
    return { emoji: "🔊", label: "Noise", category: "sound" };
  }

  // Default - other category
  const label = eventType.charAt(0).toUpperCase() + eventType.slice(1);
  return { emoji: "🔊", label, category: "other" };
};


/** Renders assistant message content with Direct Answer highlight and collapsible sections */
const AssistantMessageContent: React.FC<{
  content: string;
  role: "user" | "assistant";
  onTimestampClick?: (ts: string) => void;
}> = ({ content, role, onTimestampClick }) => {
  const components = useMemo(
    () => buildMarkdownComponents(onTimestampClick),
    [onTimestampClick],
  );

  if (role === "user") {
    return (
      <div className="prose prose-sm prose-invert max-w-none text-white">
        <ReactMarkdown>{content}</ReactMarkdown>
      </div>
    );
  }

  const sections = useMemo(() => {
    const raw = splitIntoSections(content);
    const hasDirectAnswer = raw.some((s) =>
      s.heading.toLowerCase().includes("direct answer"),
    );
    if (hasDirectAnswer) return raw;
    // LLM skipped the "## Direct Answer" heading (happens intermittently
    // with Grok). Promote the first pre-heading prose block to a synthetic
    // Direct Answer so the highlight card still renders.
    const firstProseIdx = raw.findIndex(
      (s) => !s.heading && s.body.trim().length > 0,
    );
    if (firstProseIdx === -1) return raw;
    return raw.map((s, i) =>
      i === firstProseIdx ? { ...s, heading: "Direct Answer" } : s,
    );
  }, [content]);
  const hasMultipleSections = sections.filter((s) => s.heading).length >= 2;
  const totalLength = content.length;
  const shouldCollapse = hasMultipleSections && totalLength > 1500;

  // Find Direct Answer section
  const directAnswerIdx = sections.findIndex((s) =>
    s.heading.toLowerCase().includes("direct answer"),
  );

  return (
    <div className="space-y-1">
      {sections.map((section, idx) => {
        const isDirectAnswer = idx === directAnswerIdx;
        const isPreHeading = !section.heading; // content before any heading
        const shouldStartCollapsed =
          shouldCollapse && !isDirectAnswer && !isPreHeading;

        // Direct Answer gets a highlight card
        if (isDirectAnswer) {
          return (
            <div
              key={idx}
              className="rounded-lg px-4 py-3 my-2 border"
              style={{ background: "var(--bg-surface)", borderColor: "var(--accent)" }}
            >
              <div className="flex items-center gap-2 mb-1.5">
                <svg
                  className="w-4 h-4"
                  style={{ color: "var(--accent)" }}
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z"
                  />
                </svg>
                <span className="text-sm font-bold" style={{ color: "var(--text-primary)" }}>
                  {section.heading}
                </span>
              </div>
              <div className="prose prose-sm max-w-none">
                <ReactMarkdown components={components}>
                  {section.body}
                </ReactMarkdown>
              </div>
            </div>
          );
        }

        // Content before any heading — render inline
        if (isPreHeading) {
          if (!section.body) return null;
          return (
            <div key={idx} className="prose prose-sm max-w-none">
              <ReactMarkdown components={components}>
                {section.body}
              </ReactMarkdown>
            </div>
          );
        }

        // Collapsible section
        if (shouldStartCollapsed) {
          return (
            <Disclosure key={idx} defaultOpen={false}>
              {({ open }) => (
                <div className="border-b last:border-b-0" style={{ borderColor: "var(--border-subtle)" }}>
                  <DisclosureButton className="flex items-center gap-2 w-full text-left py-2 group">
                    <svg
                      className={`w-4 h-4 transition-transform ${open ? "rotate-90" : ""}`}
                      style={{ color: "var(--text-tertiary)" }}
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
                    {getSectionIcon(section.heading)}
                    <span
                      className="text-sm font-bold transition-colors"
                      style={{ color: "var(--text-secondary)" }}
                    >
                      {section.heading}
                    </span>
                  </DisclosureButton>
                  <DisclosurePanel className="pb-2 pl-6">
                    <div className="prose prose-sm max-w-none">
                      <ReactMarkdown components={components}>
                        {section.body}
                      </ReactMarkdown>
                    </div>
                  </DisclosurePanel>
                </div>
              )}
            </Disclosure>
          );
        }

        // Regular section (not collapsible)
        return (
          <div key={idx} className="prose prose-sm max-w-none">
            <ReactMarkdown components={components}>
              {`## ${section.heading}\n\n${section.body}`}
            </ReactMarkdown>
          </div>
        );
      })}
    </div>
  );
};

const PhaseIndicator: React.FC<{ phases: PhaseEntry[] }> = ({ phases }) => {
  if (phases.length === 0) return null;
  return (
    <div className="flex flex-col gap-1.5 mb-3">
      {phases.map((phase) => (
        <div
          key={phase.id}
          className="flex items-center gap-2 text-xs"
          style={{
            color:
              phase.status === "active"
                ? "var(--text-primary)"
                : "var(--text-tertiary)",
          }}
        >
          {phase.status === "done" ? (
            <svg
              className="w-3.5 h-3.5 flex-shrink-0"
              style={{ color: "var(--c-success, oklch(70% 0.15 150))" }}
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2.5}
                d="M5 13l4 4L19 7"
              />
            </svg>
          ) : (
            <span
              className="relative flex h-3.5 w-3.5 items-center justify-center flex-shrink-0"
            >
              <span
                className="absolute inline-flex h-full w-full rounded-full animate-ping opacity-60"
                style={{ background: "var(--accent)" }}
              />
              <span
                className="relative inline-flex rounded-full h-2 w-2"
                style={{ background: "var(--accent)" }}
              />
            </span>
          )}
          <span
            className={phase.status === "active" ? "phase-shimmer" : ""}
            style={{
              fontWeight: phase.status === "active" ? 500 : 400,
            }}
          >
            {phase.label}
          </span>
        </div>
      ))}
    </div>
  );
};

export const ChatPanel: React.FC<ChatPanelProps> = ({
  videoHash,
  onTimestampClick,
}) => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [providers, setProviders] = useState<LLMProvider[]>([]);
  const [loadingProviders, setLoadingProviders] = useState(true);
  const [selectedProvider, setSelectedProvider] = useState<string>("grok");
  const [includeVisuals, setIncludeVisuals] = useState(true);

  // Models that support vision/scene search
  const VISION_SUPPORTED_PROVIDERS = ["grok", "grok-deep", "openai", "anthropic"];
  const [indexingStatus, setIndexingStatus] = useState<string | null>(null);
  const [screenshotModal, setScreenshotModal] = useState<{
    screenshots: string[];
    currentIndex: number;
    sources: Source[];
  } | null>(null);
  const [customInstructions, setCustomInstructions] = useState<string>("");
  const [showCustomInstructions, setShowCustomInstructions] = useState(false);
  const [retryCount, setRetryCount] = useState(0);
  const [reindexing, setReindexing] = useState(false);
  const [reindexStatus, setReindexStatus] = useState<string | null>(null);
  const [phases, setPhases] = useState<PhaseEntry[]>([]);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const speech = useSpeechRecognition({
    onFinalTranscript: (text) => {
      if (!text) return;
      setInput(prev => (prev ? prev.trimEnd() + ' ' : '') + text);
    },
  });


  // @mention autocomplete state
  const [speakers, setSpeakers] = useState<string[]>([]);
  const [showMentions, setShowMentions] = useState(false);
  const [mentionFilter, setMentionFilter] = useState("");
  const [mentionIndex, setMentionIndex] = useState(0);

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
        setScreenshotModal({
          ...screenshotModal,
          currentIndex: screenshotModal.currentIndex - 1,
        });
      } else if (
        e.key === "ArrowRight" &&
        screenshotModal.currentIndex < screenshotModal.screenshots.length - 1
      ) {
        setScreenshotModal({
          ...screenshotModal,
          currentIndex: screenshotModal.currentIndex + 1,
        });
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [screenshotModal]);

  const handlePreviousScreenshot = () => {
    if (screenshotModal && screenshotModal.currentIndex > 0) {
      setScreenshotModal({
        ...screenshotModal,
        currentIndex: screenshotModal.currentIndex - 1,
      });
    }
  };

  const handleNextScreenshot = () => {
    if (
      screenshotModal &&
      screenshotModal.currentIndex < screenshotModal.screenshots.length - 1
    ) {
      setScreenshotModal({
        ...screenshotModal,
        currentIndex: screenshotModal.currentIndex + 1,
      });
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
    setLoadingProviders(true);
    try {
      const response = await axios.get(`${API_BASE_URL}/api/llm/providers`);
      setProviders(response.data.providers);

      // Prefer "grok" if available, otherwise fall back to first available provider
      const grokProvider = response.data.providers.find(
        (p: LLMProvider) => p.name === "grok" && p.available,
      );
      if (grokProvider) {
        setSelectedProvider("grok");
      } else {
        // Fall back to first available provider
        const availableProvider = response.data.providers.find(
          (p: LLMProvider) => p.available,
        );
        if (availableProvider) {
          setSelectedProvider(availableProvider.name);
        }
      }
    } catch (error) {
      console.error("Failed to load providers:", error);
    } finally {
      setLoadingProviders(false);
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

  const handleReindex = async () => {
    if (!videoHash || reindexing) return;
    setReindexing(true);
    setReindexStatus(null);
    try {
      await axios.post(`${API_BASE_URL}/api/index_images/`, null, {
        params: { video_hash: videoHash, force_reindex: true },
        timeout: 15000,
      });
      setReindexStatus("Re-indexing started — visual search will update in a few minutes.");
      setTimeout(() => setReindexStatus(null), 8000);
    } catch (error) {
      console.error("Failed to re-index images:", error);
      setReindexStatus("Re-indexing failed. Please try again.");
      setTimeout(() => setReindexStatus(null), 5000);
    } finally {
      setReindexing(false);
    }
  };

  const getFriendlyErrorMessage = (error: any): { message: string; errorType: "timeout" | "server" | "network" | "unknown" } => {
    const status = error.response?.status;
    const code = error.code;

    if (status === 502 || status === 503 || status === 504) {
      return {
        message: "The server is temporarily unavailable, likely warming up. Please try again in a few seconds.",
        errorType: "server",
      };
    }
    if (code === "ECONNABORTED" || error.message?.includes("timeout")) {
      return {
        message: "The request timed out. The server might be starting up — please try again in a moment.",
        errorType: "timeout",
      };
    }
    if (!error.response && error.request) {
      return {
        message: "Could not reach the server. Please check your connection and try again.",
        errorType: "network",
      };
    }
    const detail = error.response?.data?.detail;
    if (detail && typeof detail === "string" && detail.length < 200) {
      return { message: detail, errorType: "unknown" };
    }
    return { message: "Something went wrong. Please try again.", errorType: "unknown" };
  };

  const isRetryableError = (error: any): boolean => {
    const status = error.response?.status;
    return status === 502 || status === 503 || status === 504 || error.code === "ECONNABORTED" || error.message?.includes("timeout");
  };

  const PHASE_LABELS: Record<PhaseId, string> = {
    searching: "Searching transcript",
    analyzing_scenes: "Analyzing scenes",
    matching_faces: "Matching faces",
    analyzing_audio: "Scanning audio events",
    generating: "Writing answer",
  };

  const sendViaLegacy = async (
    textToSend: string,
    history: Array<{ role: string; content: string }>
  ) => {
    const MAX_RETRIES = 2;
    const RETRY_DELAY = 3000;

    for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
      try {
        if (attempt > 0) {
          setRetryCount(attempt);
          await new Promise((resolve) => setTimeout(resolve, RETRY_DELAY));
        }

        const response = await axios.post(
          `${API_BASE_URL}/api/chat/`,
          {
            question: textToSend,
            video_hash: videoHash,
            provider: selectedProvider,
            n_results: 8,
            include_visuals: includeVisuals,
            n_images: includeVisuals ? 6 : undefined,
            custom_instructions: customInstructions || undefined,
            conversation_history: history.length > 0 ? history : undefined,
          },
          { timeout: 30000 }
        );

        setMessages((prev) => {
          const next = [...prev];
          for (let i = next.length - 1; i >= 0; i--) {
            if (next[i].role === "assistant" && next[i].isStreaming) {
              next[i] = {
                ...next[i],
                content: response.data.answer,
                sources: response.data.sources,
                visual_query_used: response.data.visual_query_used,
                isStreaming: false,
              };
              return next;
            }
          }
          return [
            ...next,
            {
              role: "assistant",
              content: response.data.answer,
              sources: response.data.sources,
              visual_query_used: response.data.visual_query_used,
              original_question: textToSend,
            },
          ];
        });
        return true;
      } catch (error: any) {
        console.error(`Chat error (attempt ${attempt + 1}):`, error);
        if (attempt < MAX_RETRIES && isRetryableError(error)) continue;

        const { message, errorType } = getFriendlyErrorMessage(error);
        setMessages((prev) => {
          const next = [...prev];
          for (let i = next.length - 1; i >= 0; i--) {
            if (next[i].role === "assistant" && next[i].isStreaming) {
              next[i] = {
                ...next[i],
                content: message,
                isError: true,
                errorType,
                retryQuestion: textToSend,
                isStreaming: false,
              };
              return next;
            }
          }
          return [
            ...next,
            {
              role: "assistant",
              content: message,
              isError: true,
              errorType,
              retryQuestion: textToSend,
            },
          ];
        });
        return false;
      }
    }
    return false;
  };

  const sendMessage = async (messageText?: string | React.MouseEvent) => {
    const textToSend = typeof messageText === "string" ? messageText : input;
    if (!textToSend.trim() || !videoHash) return;

    const userMessage: Message = {
      role: "user",
      content: textToSend,
    };

    const placeholderAssistant: Message = {
      role: "assistant",
      content: "",
      original_question: textToSend,
      isStreaming: true,
    };

    setMessages((prev) => {
      // Finalize any prior streaming assistant message so only the new
      // placeholder drives the PhaseIndicator. A stream can get stuck
      // (backend timeout, dropped connection) and leave isStreaming=true,
      // which otherwise makes older messages keep pulsing.
      const finalized = prev.map((m) => {
        if (m.role !== "assistant" || !m.isStreaming) return m;
        if (m.content) {
          return { ...m, isStreaming: false };
        }
        return {
          ...m,
          isStreaming: false,
          isError: true,
          errorType: "server" as const,
          content: "That request didn't finish. Retry?",
          retryQuestion: m.original_question,
        };
      });
      return [...finalized, userMessage, placeholderAssistant];
    });
    setInput("");
    setLoading(true);
    setRetryCount(0);
    setPhases([
      { id: "searching", label: PHASE_LABELS.searching, status: "active" },
    ]);

    const history = messages
      .filter((m) => !m.isError && !m.isStreaming)
      .slice(-10)
      .map((m) => ({ role: m.role, content: m.content }));

    const updateStreamingMessage = (updater: (msg: Message) => Message) => {
      setMessages((prev) => {
        const next = [...prev];
        for (let i = next.length - 1; i >= 0; i--) {
          if (next[i].role === "assistant" && next[i].isStreaming) {
            next[i] = updater(next[i]);
            return next;
          }
        }
        return next;
      });
    };

    const handleEvent = (evt: any) => {
      if (!evt || typeof evt !== "object") return;
      switch (evt.type) {
        case "phase": {
          const id = evt.phase as PhaseId;
          const label = evt.label || PHASE_LABELS[id] || id;
          setPhases((prev) => {
            const existing = prev.find((p) => p.id === id);
            if (existing) return prev;
            return [
              ...prev.map((p) => ({ ...p, status: "done" as const })),
              { id, label, status: "active" as const },
            ];
          });
          break;
        }
        case "sources": {
          updateStreamingMessage((m) => ({
            ...m,
            sources: evt.sources || [],
            visual_query_used: evt.visual_query_used || undefined,
          }));
          break;
        }
        case "token": {
          const chunk = evt.content || "";
          if (!chunk) break;
          updateStreamingMessage((m) => ({
            ...m,
            content: (m.content || "") + chunk,
          }));
          break;
        }
        case "reset": {
          updateStreamingMessage((m) => ({ ...m, content: "" }));
          break;
        }
        case "done": {
          updateStreamingMessage((m) => ({ ...m, isStreaming: false }));
          setPhases((prev) => prev.map((p) => ({ ...p, status: "done" })));
          break;
        }
        case "error": {
          const message = evt.message || "Something went wrong.";
          updateStreamingMessage((m) => ({
            ...m,
            content: message,
            isError: true,
            errorType: "server",
            retryQuestion: textToSend,
            isStreaming: false,
          }));
          break;
        }
      }
    };

    let streamSucceeded = false;
    let receivedAnyEvent = false;

    try {
      const controller = new AbortController();
      const response = await fetch(`${API_BASE_URL}/api/chat/stream`, {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          Accept: "text/event-stream",
        },
        body: JSON.stringify({
          question: textToSend,
          video_hash: videoHash,
          provider: selectedProvider,
          n_results: 8,
          include_visuals: includeVisuals,
          n_images: includeVisuals ? 6 : undefined,
          custom_instructions: customInstructions || undefined,
          conversation_history: history.length > 0 ? history : undefined,
        }),
        signal: controller.signal,
      });

      if (!response.ok || !response.body) {
        throw new Error(`Stream failed with status ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        let sepIndex: number;
        while ((sepIndex = buffer.indexOf("\n\n")) !== -1) {
          const rawEvent = buffer.slice(0, sepIndex);
          buffer = buffer.slice(sepIndex + 2);
          const dataLines = rawEvent
            .split("\n")
            .filter((l) => l.startsWith("data:"))
            .map((l) => l.slice(5).trimStart());
          if (dataLines.length === 0) continue;
          const payload = dataLines.join("\n");
          try {
            const parsed = JSON.parse(payload);
            receivedAnyEvent = true;
            handleEvent(parsed);
          } catch (e) {
            console.warn("Failed to parse SSE event:", payload, e);
          }
        }
      }

      streamSucceeded = true;
    } catch (error: any) {
      console.error("Stream error:", error);
      if (!receivedAnyEvent) {
        await sendViaLegacy(textToSend, history);
        streamSucceeded = true;
      } else {
        const { message, errorType } = getFriendlyErrorMessage(error);
        updateStreamingMessage((m) => ({
          ...m,
          content: m.content
            ? `${m.content}\n\n${message}`
            : message,
          isError: !m.content,
          errorType,
          retryQuestion: textToSend,
          isStreaming: false,
        }));
      }
    }

    if (!streamSucceeded) {
      updateStreamingMessage((m) => ({ ...m, isStreaming: false }));
    }

    setRetryCount(0);
    setLoading(false);
    setPhases([]);
  };

  // Fetch speakers for @mention autocomplete
  useEffect(() => {
    if (!videoHash) return;
    const fetchSpeakers = async () => {
      try {
        const [enrolled, faceTags] = await Promise.all([
          listSpeakers().catch(() => ({ speakers: [] })),
          getFaceTagSpeakers(videoHash).catch(() => ({ speakers: [] })),
        ]);
        const enrolledNames = enrolled.speakers.map((s) => s.name);
        const faceNames = faceTags.speakers.map((s) => s.speaker_name);
        setSpeakers(
          [...new Set([...enrolledNames, ...faceNames])]
            .filter(Boolean)
            .sort()
        );
      } catch (e) {
        console.error("Failed to fetch speakers:", e);
      }
    };
    fetchSpeakers();
  }, [videoHash]);

  const filteredSpeakers = useMemo(() => {
    if (!mentionFilter) return speakers;
    const lower = mentionFilter.toLowerCase();
    return speakers.filter((s) => s.toLowerCase().includes(lower));
  }, [speakers, mentionFilter]);

  const getMentionContext = (value: string, cursorPos: number) => {
    // Look backwards from cursor for @ not preceded by a non-space char
    const before = value.slice(0, cursorPos);
    const match = before.match(/@(\S*)$/);
    if (match) {
      return { start: cursorPos - match[0].length, filter: match[1] };
    }
    return null;
  };

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value;
    setInput(value);
    const cursorPos = e.target.selectionStart || value.length;
    const ctx = getMentionContext(value, cursorPos);
    if (ctx) {
      setShowMentions(true);
      setMentionFilter(ctx.filter);
      setMentionIndex(0);
    } else {
      setShowMentions(false);
    }
  };

  const selectMention = (speaker: string) => {
    const el = inputRef.current;
    const cursorPos = el?.selectionStart || input.length;
    const ctx = getMentionContext(input, cursorPos);
    if (ctx) {
      const before = input.slice(0, ctx.start);
      const after = input.slice(cursorPos);
      const newValue = before + speaker + " " + after;
      setInput(newValue);
      setShowMentions(false);
      // Focus and set cursor after inserted name
      setTimeout(() => {
        el?.focus();
        const pos = before.length + speaker.length + 1;
        el?.setSelectionRange(pos, pos);
      }, 0);
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (showMentions && filteredSpeakers.length > 0) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setMentionIndex((i) => Math.min(i + 1, filteredSpeakers.length - 1));
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setMentionIndex((i) => Math.max(i - 1, 0));
        return;
      }
      if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        selectMention(filteredSpeakers[mentionIndex]);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setShowMentions(false);
        return;
      }
    }
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
        <div className="text-center" style={{ color: "var(--text-secondary)" }}>
          <svg
            className="w-16 h-16 mx-auto mb-4"
            style={{ color: "var(--text-tertiary)" }}
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
    <div className="flex flex-col h-full" style={{ background: "var(--bg-subtle)" }}>
      {/* Header */}
      <div className="px-4 py-3" style={{ background: "var(--bg-subtle)" }}>
          {/* Controls Row */}
          <div className="flex items-center gap-3 flex-wrap">
            {/* Model Selector */}
            <div className="flex items-center gap-2">
              <label className="text-xs font-medium" style={{ color: "var(--text-secondary)" }}>
                Model:
              </label>
              <div className="relative">
                {loadingProviders ? (
                  <div className="flex items-center gap-2 px-4 py-2 text-sm rounded-lg min-w-[200px] input-base" style={{ color: "var(--text-secondary)" }}>
                    <svg
                      className="w-4 h-4 animate-spin"
                      style={{ color: "var(--text-secondary)" }}
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
                    <span>Loading models...</span>
                  </div>
                ) : (
                  <select
                    value={selectedProvider}
                    onChange={(e) => {
                      const newProvider = e.target.value;
                      setSelectedProvider(newProvider);
                      // Reset visual search if switching to non-vision provider
                      if (!VISION_SUPPORTED_PROVIDERS.includes(newProvider)) {
                        setIncludeVisuals(false);
                      }
                    }}
                    className="input-base appearance-none text-sm pl-4 pr-10 py-2 transition-all cursor-pointer font-medium min-w-[200px]"
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
                )}
                {/* Custom chevron icon */}
                {!loadingProviders && (
                  <div className="absolute inset-y-0 right-0 flex items-center pr-3 pointer-events-none">
                    <svg
                      className="w-4 h-4"
                      style={{ color: "var(--text-secondary)" }}
                      fill="none"
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M19 9l-7 7-7-7"
                      />
                    </svg>
                  </div>
                )}
              </div>
            </div>

            {/* Divider - only show if vision supported */}
            {VISION_SUPPORTED_PROVIDERS.includes(selectedProvider) && (
              <div className="h-6 w-px" style={{ background: "var(--border-default)" }}></div>
            )}

            {/* Visual Search Toggle - only show for vision-capable models */}
            {VISION_SUPPORTED_PROVIDERS.includes(selectedProvider) && (
              <div className="relative group flex items-center gap-2">
                <button
                  onClick={() => setIncludeVisuals(!includeVisuals)}
                  className="btn-ghost flex items-center gap-2 px-3 py-1.5 text-sm font-medium"
                  style={includeVisuals ? { background: "var(--accent-dim)", color: "var(--accent)" } : {}}
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
                    <span className="ml-1 px-1.5 py-0.5 text-xs rounded-full font-semibold" style={{ background: "var(--accent)", color: "var(--accent-text)" }}>
                      ON
                    </span>
                  )}
                </button>

                {/* Info tooltip */}
                <div className="relative">
                  <button
                    className="w-4 h-4 rounded-full flex items-center justify-center text-xs font-bold transition-colors"
                    style={{ background: "var(--bg-overlay)", color: "var(--text-secondary)" }}
                    title="Scene Search finds visual moments (actions, objects, settings). Cannot identify specific people by name - use transcript for speaker queries."
                    aria-label="Scene search information"
                  >
                    ?
                  </button>
                  {/* Tooltip on hover */}
                  <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 px-3 py-2 text-xs rounded-lg opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none w-64 z-10 shadow-lg" style={{ background: "var(--bg-overlay)", color: "var(--text-primary)", border: "1px solid var(--border-subtle)" }}>
                    <div className="font-medium mb-1.5" style={{ color: "var(--text-primary)" }}>Scene Search</div>
                    <div className="mb-1" style={{ color: "var(--text-secondary)" }}>
                      Finds visual moments (actions, objects, settings).
                    </div>
                    <div style={{ color: "var(--text-secondary)" }}>
                      Cannot identify specific people by name - use transcript
                      for speaker queries.
                    </div>
                    <svg
                      className="absolute top-full left-1/2 -translate-x-1/2"
                      style={{ color: "var(--bg-overlay)" }}
                      width="8"
                      height="4"
                      viewBox="0 0 8 4"
                    >
                      <path fill="currentColor" d="M0 0l4 4 4-4z" />
                    </svg>
                  </div>
                </div>

                {/* Re-index button */}
                <button
                  onClick={handleReindex}
                  disabled={reindexing || !videoHash}
                  className="btn-ghost !p-0 w-6 h-6 rounded-full flex items-center justify-center transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  title="Re-index images (fixes visual search)"
                  aria-label="Re-index images"
                >
                  {reindexing ? (
                    <svg className="animate-spin w-3.5 h-3.5" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                    </svg>
                  ) : (
                    <svg className="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor">
                      <path fillRule="evenodd" d="M4 2a1 1 0 011 1v2.101a7.002 7.002 0 0111.601 2.566 1 1 0 11-1.885.666A5.002 5.002 0 005.999 7H9a1 1 0 010 2H4a1 1 0 01-1-1V3a1 1 0 011-1zm.008 9.057a1 1 0 011.276.61A5.002 5.002 0 0014.001 13H11a1 1 0 110-2h5a1 1 0 011 1v5a1 1 0 11-2 0v-2.101a7.002 7.002 0 01-11.601-2.566 1 1 0 01.61-1.276z" clipRule="evenodd" />
                    </svg>
                  )}
                </button>
              </div>
            )}
          </div>

        {/* Re-index Status */}
        {reindexStatus && (
          <div
            className="mt-2 px-3 py-2 rounded-lg flex items-center gap-2 text-sm border"
            style={
              reindexStatus.includes("failed")
                ? { background: "oklch(65% 0.20 25 / 0.08)", borderColor: "oklch(65% 0.20 25 / 0.25)", color: "oklch(65% 0.20 25)" }
                : { background: "oklch(70% 0.15 145 / 0.08)", borderColor: "oklch(70% 0.15 145 / 0.25)", color: "oklch(70% 0.15 145)" }
            }
          >
            <span>{reindexStatus}</span>
          </div>
        )}

        {/* Indexing Status */}
        {indexingStatus && (
          <div className="mt-3 px-3 py-2 rounded-lg flex items-center gap-2 border" style={{ background: "var(--bg-overlay)", borderColor: "var(--border-subtle)" }}>
            {indexingStatus.includes("Indexing") && (
              <svg
                className="w-4 h-4 animate-spin"
                style={{ color: "var(--text-secondary)" }}
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
                className="w-4 h-4"
                style={{ color: "var(--c-success)" }}
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
                className="w-4 h-4"
                style={{ color: "var(--c-error)" }}
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
            <p
              className="text-sm"
              style={{
                color: indexingStatus.includes("successfully")
                  ? "var(--c-success)"
                  : indexingStatus.includes("failed")
                    ? "var(--c-error)"
                    : "var(--text-secondary)",
              }}
            >
              {indexingStatus}
            </p>
          </div>
        )}
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-6 space-y-4">
        {messages.length === 0 && (
          <div className="text-center py-8">
            <p className="mb-4" style={{ color: "var(--text-secondary)" }}>Start a conversation!</p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-w-2xl mx-auto">
              {quickQuestions.map((question, index) => (
                <button
                  key={index}
                  onClick={() => sendMessage(question)}
                  className="px-4 py-2 text-sm text-left rounded-lg transition-colors"
                  style={{ background: "var(--bg-overlay)", color: "var(--text-secondary)" }}
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
                <div
                  className="max-w-3xl px-3 py-2 rounded-lg text-xs flex items-start gap-2 border"
                  style={{ background: "var(--bg-overlay)", borderColor: "var(--border-subtle)", color: "var(--text-secondary)" }}
                >
                  <svg className="w-4 h-4 flex-shrink-0 mt-px" style={{ color: "var(--accent)" }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
                  </svg>
                  <div>
                    <span className="font-medium" style={{ color: "var(--text-primary)" }}>Scene search:</span> "
                    {message.visual_query_used}"
                  </div>
                </div>
              )}

            <div
              className="max-w-3xl rounded-xl"
              style={
                message.role === "user"
                  ? { padding: "0.75rem 1rem", background: "var(--accent)", color: "var(--accent-text)" }
                  : message.isError
                  ? { padding: "1rem 1.25rem", background: "oklch(65% 0.20 25 / 0.08)", border: "1px solid oklch(65% 0.20 25 / 0.25)", color: "var(--text-primary)" }
                  : { padding: "1rem 1.25rem", background: "var(--bg-surface)", border: "1px solid var(--border-subtle)", color: "var(--text-primary)" }
              }
            >
              {message.isError ? (
                <div>
                  <div className="flex items-center gap-2 mb-2">
                    <svg className="w-5 h-5 flex-shrink-0" style={{ color: "var(--c-error)" }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
                    </svg>
                    <span className="font-medium text-sm" style={{ color: "var(--c-error)" }}>Something went wrong</span>
                  </div>
                  <p className="text-sm mb-3" style={{ color: "var(--text-secondary)" }}>{message.content}</p>
                  {message.retryQuestion && (
                    <button
                      onClick={() => sendMessage(message.retryQuestion)}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md transition-colors"
                      style={{ color: "var(--c-error)", background: "oklch(65% 0.20 25 / 0.12)" }}
                    >
                      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                      </svg>
                      Retry
                    </button>
                  )}
                </div>
              ) : (
                <>
                  {message.role === "assistant" && message.isStreaming && (
                    <PhaseIndicator phases={phases} />
                  )}
                  {message.content && (
                    <AssistantMessageContent
                      content={message.content}
                      role={message.role}
                      onTimestampClick={onTimestampClick}
                    />
                  )}
                  {message.role === "assistant" &&
                    message.isStreaming &&
                    message.content && (
                      <span
                        aria-hidden="true"
                        className="inline-block align-middle ml-0.5 animate-pulse"
                        style={{
                          width: "0.55rem",
                          height: "1em",
                          background: "var(--accent)",
                          borderRadius: "1px",
                          marginBottom: "-0.1em",
                        }}
                      />
                    )}
                </>
              )}

              {/* Sources */}
              {!message.isError && message.sources && message.sources.length > 0 && (
                <div className="mt-4 space-y-3">
                  {/* Visual Sources (Screenshots) */}
                  {message.sources.filter((s) => s.screenshot_url).length >
                    0 && (
                    <div className="rounded-lg p-3 border" style={{ background: "var(--bg-surface)", borderColor: "var(--border-subtle)" }}>
                      <div className="flex items-center gap-2 mb-3">
                        <svg className="w-4 h-4" style={{ color: "var(--accent)" }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
                        </svg>
                        <p className="text-xs font-bold uppercase tracking-wide" style={{ color: "var(--text-secondary)" }}>
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
                                  const visualSources = message.sources!.filter(
                                    (s) => s.screenshot_url,
                                  );
                                  const screenshots = visualSources.map((s) =>
                                    formatScreenshotUrl(s.screenshot_url),
                                  );
                                  setScreenshotModal({
                                    screenshots,
                                    currentIndex: idx,
                                    sources: visualSources,
                                  });
                                }
                              }}
                              className="group relative aspect-video rounded-lg overflow-hidden border-2 transition-all hover:shadow-lg cursor-pointer"
                              style={{ background: "var(--bg-overlay)", borderColor: "var(--border-default)" }}
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
                                <svg
                                  className="w-8 h-8 text-white opacity-0 group-hover:opacity-100 transition-opacity"
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
                                    if (e.key === "Enter" || e.key === " ") {
                                      e.stopPropagation();
                                      onTimestampClick?.(source.start_time);
                                    }
                                  }}
                                  className="text-white text-xs font-mono font-bold transition-colors cursor-pointer block mb-0.5"
                                >
                                  {source.start_time}
                                </span>
                                {(source as any).likely_speakers &&
                                (source as any).likely_speakers.length > 0 ? (
                                  <p className="text-white/90 text-xs truncate">
                                    Likely:{" "}
                                    {(source as any).likely_speakers.join(", ")}
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
                  {message.sources.filter(
                    (s) => !s.screenshot_url && s.type !== "audio",
                  ).length > 0 && (
                    <div className="rounded-lg p-3 border" style={{ background: "var(--bg-surface)", borderColor: "var(--border-subtle)" }}>
                      <div className="flex items-center gap-2 mb-2">
                        <span className="text-base">📝</span>
                        <p className="text-xs font-bold uppercase tracking-wide" style={{ color: "var(--text-secondary)" }}>
                          From Transcript
                        </p>
                      </div>
                      <div className="space-y-1.5">
                        {message.sources
                          .filter(
                            (s) => !s.screenshot_url && s.type !== "audio",
                          )
                          .map((source, idx) => (
                            <button
                              key={idx}
                              onClick={() =>
                                onTimestampClick?.(source.start_time)
                              }
                              className="block w-full text-left text-xs px-3 py-2 rounded-lg border transition-all hover:shadow-sm group"
                              style={{ background: "var(--bg-overlay)", borderColor: "var(--border-subtle)", color: "var(--text-primary)" }}
                            >
                              <div className="flex items-center justify-between mb-1">
                                <span className="font-mono font-bold" style={{ color: "var(--accent)" }}>
                                  {source.start_time} - {source.end_time}
                                </span>
                                <span className="font-medium" style={{ color: "var(--text-secondary)" }}>
                                  {source.speaker}
                                </span>
                              </div>
                              {source.text && (
                                <p className="line-clamp-2 leading-relaxed" style={{ color: "var(--text-secondary)" }}>
                                  {source.text}
                                </p>
                              )}
                            </button>
                          ))}
                      </div>
                    </div>
                  )}

                  {/* Audio Events */}
                  {message.sources.filter((s) => s.type === "audio").length >
                    0 && (
                    <div className="rounded-lg p-3 border" style={{ background: "var(--bg-surface)", borderColor: "var(--border-subtle)" }}>
                      <div className="flex items-center gap-2 mb-2">
                        <svg
                          className="w-4 h-4"
                          style={{ color: "var(--text-tertiary)" }}
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
                        <p className="text-xs font-bold uppercase tracking-wide" style={{ color: "var(--text-secondary)" }}>
                          Audio Events
                        </p>
                        <span className="text-xs" style={{ color: "var(--text-tertiary)" }}>
                          {message.sources.filter((s) => s.type === "audio").length} found
                        </span>
                      </div>
                      <div className="space-y-1">
                        {message.sources
                          .filter((s) => s.type === "audio")
                          .map((source, idx) => {
                            const eventDetails = getEventDetails(
                              source.event_type || "unknown",
                            );
                            const confidence = source.confidence || 0;
                            const duration =
                              source.end && source.start
                                ? `${(source.end - source.start).toFixed(1)}s`
                                : null;

                            return (
                              <button
                                key={idx}
                                onClick={() => onTimestampClick?.(source.start_time)}
                                className="block w-full text-left rounded-md transition-colors"
                                style={{ background: "var(--bg-overlay)", border: "1px solid var(--border-subtle)", padding: "8px 10px" }}
                                onMouseEnter={e => (e.currentTarget as HTMLButtonElement).style.borderColor = 'var(--border-default)'}
                                onMouseLeave={e => (e.currentTarget as HTMLButtonElement).style.borderColor = 'var(--border-subtle)'}
                                title={`${eventDetails.label} at ${source.start_time}${duration ? ` (${duration})` : ""} — click to jump`}
                                aria-label={`Jump to ${eventDetails.label} event at ${source.start_time}`}
                              >
                                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px' }}>
                                  {/* Left: emoji + label */}
                                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0 }}>
                                    <span style={{ fontSize: '16px', lineHeight: 1, flexShrink: 0 }}>{eventDetails.emoji}</span>
                                    <span style={{ fontSize: '13px', fontWeight: 500, color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                      {eventDetails.label}
                                    </span>
                                    {source.speaker && source.speaker !== "Unknown" && (
                                      <span style={{ fontSize: '11px', color: 'var(--text-tertiary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                        {source.speaker}
                                      </span>
                                    )}
                                  </div>
                                  {/* Right: timestamp + meta */}
                                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexShrink: 0 }}>
                                    {confidence > 0 && (
                                      <span style={{ fontSize: '10px', fontWeight: 600, color: 'var(--text-tertiary)', fontVariantNumeric: 'tabular-nums' }}>
                                        {Math.round(confidence * 100)}%
                                      </span>
                                    )}
                                    {duration && (
                                      <span style={{ fontSize: '11px', color: 'var(--text-tertiary)' }}>
                                        {duration}
                                      </span>
                                    )}
                                    <span
                                      className="inline-flex items-center gap-0.5 px-1.5 py-0.5 text-xs font-mono font-semibold rounded"
                                      style={{ background: "var(--accent-dim)", color: "var(--accent)" }}
                                    >
                                      {source.start_time}
                                    </span>
                                  </div>
                                </div>
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

        {retryCount > 0 && loading && (
          <div className="flex justify-start">
            <div
              className="px-3 py-1.5 rounded-md text-xs font-medium"
              style={{
                background: "var(--bg-surface)",
                color: "var(--accent)",
              }}
            >
              Retrying... (attempt {retryCount + 1})
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="px-6 py-4 border-t" style={{ background: "var(--bg-subtle)", borderColor: "var(--border-subtle)" }}>
        {/* Custom Instructions Section */}
        <div className="mb-3">
          <button
            onClick={() => setShowCustomInstructions(!showCustomInstructions)}
            className="flex items-center gap-2 text-sm font-medium transition-colors"
            style={{ color: "var(--text-secondary)" }}
            aria-expanded={showCustomInstructions}
            aria-label="Toggle custom instructions"
          >
            <svg
              className={`w-4 h-4 transition-transform ${showCustomInstructions ? "rotate-90" : ""}`}
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
              <span className="ml-1 px-2 py-0.5 text-xs rounded-full font-semibold" style={{ background: "var(--accent-dim)", color: "var(--accent)" }}>
                Active
              </span>
            )}
          </button>

          {showCustomInstructions && (
            <div className="mt-3 rounded-lg border p-3" style={{ background: "var(--bg-surface)", borderColor: "var(--border-default)" }}>
              <textarea
                value={customInstructions}
                onChange={(e) => setCustomInstructions(e.target.value)}
                placeholder="Add custom instructions for the AI (e.g., 'Respond in Spanish', 'Be brief and casual', 'Focus on technical details')..."
                className="input-base w-full px-3 py-2 resize-none text-sm"
                rows={3}
                disabled={loading}
              />
              <p className="mt-2 text-xs" style={{ color: "var(--text-tertiary)" }}>
                These instructions will be applied to all your questions. They
                persist across messages.
              </p>
            </div>
          )}
        </div>

        {/* Chat Input */}
        <div className="relative flex gap-2">
          {showMentions && filteredSpeakers.length > 0 && (
            <div className="absolute bottom-full mb-1 left-0 w-64 rounded-lg shadow-lg max-h-48 overflow-y-auto z-50 border" style={{ background: "var(--bg-overlay)", borderColor: "var(--border-default)" }}>
              {filteredSpeakers.map((speaker, i) => (
                <button
                  key={speaker}
                  className="w-full text-left px-3 py-2 text-sm transition-colors"
                  style={
                    i === mentionIndex
                      ? { background: "var(--accent-dim)", color: "var(--accent)" }
                      : { color: "var(--text-primary)" }
                  }
                  onMouseDown={(e) => {
                    e.preventDefault();
                    selectMention(speaker);
                  }}
                >
                  <span className="mr-1" style={{ color: "var(--text-tertiary)" }}>@</span>
                  {speaker}
                </button>
              ))}
            </div>
          )}
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={handleInputChange}
            onKeyDown={handleKeyPress}
            placeholder="Ask about the video... (type @ to mention a speaker)"
            className="input-base flex-1 px-4 py-3"
            disabled={loading}
          />
          {speech.isSupported && (
            <button
              type="button"
              onClick={() => (speech.status === 'listening' ? speech.stop() : speech.start())}
              disabled={loading}
              aria-label={speech.status === 'listening' ? 'Stop dictation' : 'Start dictation'}
              title={speech.status === 'denied' ? 'Microphone permission denied' : 'Voice input'}
              className={`relative px-3 py-3 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
                speech.status === 'listening' ? 'bg-red-500/15 text-red-500' : 'btn-ghost'
              }`}
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M19 10v2a7 7 0 0 1-14 0v-2M12 19v4M8 23h8" />
              </svg>
              {speech.status === 'listening' && (
                <span className="absolute top-1.5 right-1.5 w-2 h-2 rounded-full bg-red-500 animate-pulse" />
              )}
            </button>
          )}
          <button
            onClick={sendMessage}
            disabled={loading || !input.trim()}
            className="px-6 py-3 rounded-lg disabled:opacity-50 disabled:cursor-not-allowed transition-colors font-medium"
            style={{ background: "var(--accent)", color: "var(--accent-text)" }}
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
        {speech.status === 'listening' && (
          <div className="px-2 pt-2 text-xs flex items-center gap-2" style={{ color: 'var(--text-tertiary)' }}>
            <span className="inline-flex w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse" />
            <span>
              Listening — click mic to stop
              {speech.interim ? ` · "${speech.interim}"` : '…'}
            </span>
          </div>
        )}
      </div>

      {/* Screenshot Modal with Slideshow */}
      {screenshotModal && (
        <div
          className="fixed inset-0 bg-black bg-opacity-90 z-50 flex items-center justify-center p-4"
          onClick={() => setScreenshotModal(null)}
        >
          <div
            className="relative max-w-6xl max-h-full"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Close Button */}
            <button
              onClick={() => setScreenshotModal(null)}
              className="absolute top-2 right-2 z-10 w-10 h-10 rounded-full flex items-center justify-center transition-colors border"
              style={{
                background: 'var(--bg-overlay)',
                color: 'var(--text-primary)',
                borderColor: 'var(--border-subtle)',
              }}
              aria-label="Close screenshot"
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

            {/* Image Counter */}
            <div
              className="absolute top-2 left-2 z-10 px-3 py-1.5 text-xs font-mono tabular-nums rounded-full border"
              style={{
                background: 'var(--bg-overlay)',
                color: 'var(--text-primary)',
                borderColor: 'var(--border-subtle)',
              }}
            >
              {screenshotModal.currentIndex + 1} / {screenshotModal.screenshots.length}
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
                className="absolute left-2 top-1/2 -translate-y-1/2 w-12 h-12 rounded-full flex items-center justify-center transition-all opacity-60 hover:opacity-100 border"
                style={{
                  background: 'var(--bg-overlay)',
                  color: 'var(--text-primary)',
                  borderColor: 'var(--border-subtle)',
                }}
                aria-label="Previous image"
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
                    strokeWidth={2.5}
                    d="M15 19l-7-7 7-7"
                  />
                </svg>
              </button>
            )}

            {/* Next Button */}
            {screenshotModal.currentIndex <
              screenshotModal.screenshots.length - 1 && (
              <button
                onClick={handleNextScreenshot}
                className="absolute right-2 top-1/2 -translate-y-1/2 w-12 h-12 rounded-full flex items-center justify-center transition-all opacity-60 hover:opacity-100 border"
                style={{
                  background: 'var(--bg-overlay)',
                  color: 'var(--text-primary)',
                  borderColor: 'var(--border-subtle)',
                }}
                aria-label="Next image"
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
                    strokeWidth={2.5}
                    d="M9 5l7 7-7 7"
                  />
                </svg>
              </button>
            )}

            {/* Timestamp and Speaker Info */}
            {screenshotModal.sources[screenshotModal.currentIndex] && (
              <div className="absolute bottom-2 left-1/2 -translate-x-1/2 px-4 py-2 bg-black bg-opacity-60 text-white rounded-lg backdrop-blur-sm text-center">
                <button
                  onClick={() =>
                    onTimestampClick?.(
                      screenshotModal.sources[screenshotModal.currentIndex]
                        .start_time,
                    )
                  }
                  className="text-sm font-mono font-bold transition-colors" style={{ color: 'var(--accent)' }}
                  title="Click to jump to this timestamp"
                >
                  {
                    screenshotModal.sources[screenshotModal.currentIndex]
                      .start_time
                  }
                </button>
                {(screenshotModal.sources[screenshotModal.currentIndex] as any)
                  .likely_speakers?.length > 0 && (
                  <p className="text-xs text-white/90 mt-1">
                    Likely:{" "}
                    {(
                      screenshotModal.sources[
                        screenshotModal.currentIndex
                      ] as any
                    ).likely_speakers.join(", ")}
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
