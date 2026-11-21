import { useMemo } from "react";
import ReactMarkdown from "react-markdown";
import { Disclosure, DisclosureButton, DisclosurePanel } from "@headlessui/react";
import { PersonComparisonSection } from "./PersonComparisonSection";
import { splitIntoSections } from "./answerSections";
import { buildMarkdownComponents, getSectionIcon } from "./markdown";
import type { PersonComparisonData, Source, TimelineFrame } from "./types";

export const AssistantMessageContent: React.FC<{
  content: string;
  role: "user" | "assistant";
  onTimestampClick?: (ts: string) => void;
  onOpenScreenshots?: (sources: Source[], index: number) => void;
  isSwapping?: boolean;
  pendingBSeconds?: number | null;
  pendingSwapTarget?: "a" | "b" | null;
  swapError?: string;
  onSwapFrame?: (meta: PersonComparisonData, frame: TimelineFrame, target: "a" | "b") => void;
  onDismissSwapError?: () => void;
}> = ({
  content,
  role,
  onTimestampClick,
  onOpenScreenshots,
  isSwapping,
  pendingBSeconds,
  pendingSwapTarget,
  swapError,
  onSwapFrame,
  onDismissSwapError,
}) => {
  const components = useMemo(
    () => buildMarkdownComponents(onTimestampClick),
    [onTimestampClick],
  );

  const sections = useMemo(() => {
    const raw = splitIntoSections(content);
    const hasDirectAnswer = raw.some((s) =>
      s.heading.toLowerCase().includes("direct answer"),
    );
    if (hasDirectAnswer) return raw;
    const firstProseIdx = raw.findIndex(
      (s) => !s.heading && s.body.trim().length > 0,
    );
    if (firstProseIdx === -1) return raw;
    return raw.map((s, i) =>
      i === firstProseIdx ? { ...s, heading: "Direct answer" } : s,
    );
  }, [content]);

  if (role === "user") {
    return (
      <div className="prose prose-sm prose-invert max-w-none text-white">
        <ReactMarkdown>{content}</ReactMarkdown>
      </div>
    );
  }

  const hasMultipleSections = sections.filter((s) => s.heading).length >= 2;
  const totalLength = content.length;
  const shouldCollapse = hasMultipleSections && totalLength > 1500;

  const directAnswerIdx = sections.findIndex((s) =>
    s.heading.toLowerCase().includes("direct answer"),
  );

  return (
    <div className="space-y-1">
      {sections.map((section, idx) => {
        const isDirectAnswer = idx === directAnswerIdx;
        const isPreHeading = !section.heading;
        const shouldStartCollapsed =
          shouldCollapse && !isDirectAnswer && !isPreHeading;
        const isPersonComparison = section.heading
          .toLowerCase()
          .includes("person comparison");

        if (isPersonComparison) {
          return (
            <PersonComparisonSection
              key={idx}
              body={section.body}
              components={components}
              onTimestampClick={onTimestampClick}
              onOpenScreenshots={onOpenScreenshots}
              isSwapping={isSwapping}
              pendingBSeconds={pendingBSeconds}
              pendingSwapTarget={pendingSwapTarget}
              swapError={swapError}
              onSwapFrame={onSwapFrame}
              onDismissSwapError={onDismissSwapError}
            />
          );
        }

        if (isDirectAnswer) {
          return (
            <div key={idx} className="my-2">
              <div className="mb-1 text-xs font-medium" style={{ color: "var(--accent)" }}>
                Direct answer
              </div>
              <div className="prose prose-sm max-w-none">
                <ReactMarkdown components={components}>
                  {section.body}
                </ReactMarkdown>
              </div>
            </div>
          );
        }

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
                      className="text-sm font-medium transition-colors"
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
