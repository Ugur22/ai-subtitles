import { Components } from "react-markdown";
import { TIMESTAMP_REGEX, displayTimestamp } from "./timestamps";

export const SECTION_ICONS: Record<string, string> = {
  "person comparison": "user",
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

export function getSectionIcon(heading: string): React.ReactNode {
  const lower = heading.toLowerCase();
  for (const [key, icon] of Object.entries(SECTION_ICONS)) {
    if (lower.includes(key)) {
      const iconMap: Record<string, React.ReactNode> = {
        "magnifying-glass": (
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
              strokeWidth={1.5}
              d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
            />
          </svg>
        ),
        eye: (
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
              strokeWidth={1.5}
              d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"
            />
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={1.5}
              d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"
            />
          </svg>
        ),
        "document-text": (
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
              strokeWidth={1.5}
              d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
            />
          </svg>
        ),
        "information-circle": (
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
              strokeWidth={1.5}
              d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
            />
          </svg>
        ),
        user: (
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
              strokeWidth={1.5}
              d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"
            />
          </svg>
        ),
        clock: (
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
              strokeWidth={1.5}
              d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"
            />
          </svg>
        ),
        "speaker-wave": (
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
              strokeWidth={1.5}
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

export function renderWithTimestamps(
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
    const label = endTs
      ? `${displayTimestamp(startTs)} - ${displayTimestamp(endTs)}`
      : displayTimestamp(startTs);
    parts.push(
      <button
        key={`ts-${match.index}`}
        onClick={() => onTimestampClick?.(startTs)}
        className="tc mx-0.5"
      >
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

export function processChildren(
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

export function buildMarkdownComponents(
  onTimestampClick?: (ts: string) => void,
): Components {
  return {
    h2({ children }) {
      const text = typeof children === "string" ? children : String(children);
      const icon = getSectionIcon(text);
      return (
        <h2
          className="flex items-center gap-2 text-base font-medium mt-5 mb-2 pb-2 border-b"
          style={{ color: "var(--text-primary)", borderColor: "var(--border-subtle)" }}
        >
          {icon}
          <span>{children}</span>
        </h2>
      );
    },
    h3({ children }) {
      return (
        <h3 className="text-sm font-medium mt-3 mb-1" style={{ color: "var(--text-primary)" }}>
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
          className="border-l-2 px-4 py-2 my-3 not-italic"
          style={{ borderLeftColor: "var(--accent)", background: "var(--bg-subtle)" }}
        >
          {children}
        </blockquote>
      );
    },
    strong({ children }) {
      return (
        <strong className="font-medium" style={{ color: "var(--text-primary)" }}>{children}</strong>
      );
    },
  };
}
