import type { Dispatch, SetStateAction } from "react";
import { LuAudioLines, LuFileText, LuImage } from "react-icons/lu";
import { getJobScreenshotUrl } from "../../../services/api";
import { extractGcsPathFromSignedUrl, formatScreenshotUrlSafe } from "../../../utils/url";
import { EvidenceDisclosure } from "./EvidenceDisclosure";
import { EVENT_CATEGORY_ICON, getEventDetails } from "./audioEvents";
import { imagePlaceholderSrc } from "./screenshots";
import type { Message, ScreenshotModalState } from "./types";

interface MessageSourcesProps {
  message: Message;
  setScreenshotModal: Dispatch<SetStateAction<ScreenshotModalState | null>>;
  onTimestampClick?: (timeString: string) => void;
  jobId?: string | null;
  accessToken?: string;
}

export const MessageSources: React.FC<MessageSourcesProps> = ({
  message,
  setScreenshotModal,
  onTimestampClick,
  jobId,
  accessToken,
}) => {
  if (!message.sources || message.sources.length === 0) return null;
  const visualSources = message.sources.filter((s) => s.screenshot_url);
  const transcriptSources = message.sources.filter((s) => !s.screenshot_url && s.type !== "audio");
  const audioSources = message.sources.filter((s) => s.type === "audio");

  return (
    <div className="mt-4">
      {visualSources.length > 0 && (
        <EvidenceDisclosure
          title="Scene matches"
          count={visualSources.length}
          defaultOpen
          icon={<span className="inline-flex" style={{ color: "var(--text-tertiary)" }}><LuImage size={16} strokeWidth={1.5} /></span>}
        >
          <div className="scene-grid">
            {visualSources.map((source, idx) => {
                const openScreenshot = () => {
                  setScreenshotModal({ currentIndex: idx, sources: visualSources });
                };
                const evidenceLabel =
                  source.evidence_label ||
                  source.visual_query_variant ||
                  (source.likely_speakers?.length
                    ? "Scene + identity"
                    : "Scene match");
                const evidenceTitle =
                  source.source_kind === "face_tag"
                    ? `${evidenceLabel} · matched by face tag`
                    : evidenceLabel;

                return (
                  <div
                    key={idx}
                    role="button"
                    tabIndex={0}
                    onClick={openScreenshot}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        openScreenshot();
                      }
                    }}
                    className="scene-item"
                    title={`Open screenshot at ${source.start_time}. ${evidenceTitle}`}
                    aria-label={`Open screenshot at ${source.start_time}. ${evidenceTitle}`}
                  >
                    <div className="scene-frame">
                      <img
                      src={formatScreenshotUrlSafe(source.screenshot_url)}
                      alt={`Screenshot at ${source.start_time}`}
                      loading="lazy"
                      decoding="async"
                      onError={async (e) => {
                        const img = e.currentTarget;
                        if (img.dataset.retry === "1" || !jobId) {
                          img.src = imagePlaceholderSrc;
                          return;
                        }

                        const gcsPath =
                          extractGcsPathFromSignedUrl(img.currentSrc || img.src) ||
                          extractGcsPathFromSignedUrl(formatScreenshotUrlSafe(source.screenshot_url));

                        if (!gcsPath) {
                          img.src = imagePlaceholderSrc;
                          return;
                        }

                        img.dataset.retry = "1";
                        try {
                          const { download_url } = await getJobScreenshotUrl(
                            jobId,
                            gcsPath,
                            accessToken,
                          );
                          img.src = download_url;
                        } catch (err) {
                          console.error("Failed to refresh screenshot URL", err);
                          img.src = imagePlaceholderSrc;
                        }
                      }}
                    />
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          onTimestampClick?.(source.start_time);
                        }}
                        className="tc tc-on-image scene-tc"
                        title={`Jump to ${source.start_time}`}
                        aria-label={`Jump video to ${source.start_time}`}
                      >
                        {source.start_time}
                      </button>
                    </div>
                    <p className="scene-cap">{evidenceLabel}</p>
                  </div>
                );
              })}
          </div>
        </EvidenceDisclosure>
      )}

      {transcriptSources.length > 0 && (
        <EvidenceDisclosure
          title="From transcript"
          count={transcriptSources.length}
          icon={<span className="inline-flex" style={{ color: "var(--text-tertiary)" }}><LuFileText size={16} strokeWidth={1.5} /></span>}
        >
          <div className="space-y-1.5">
            {transcriptSources.map((source, idx) => (
                <button
                  key={idx}
                  onClick={() =>
                    onTimestampClick?.(source.start_time)
                  }
                  className="block w-full text-left text-xs px-3 py-2 rounded-lg border transition-colors hover:border-[var(--border-default)] group"
                  style={{ background: "var(--bg-overlay)", borderColor: "var(--border-subtle)", color: "var(--text-primary)" }}
                >
                  <div className="flex items-center justify-between mb-1">
                    <span className="tc group-hover:text-[var(--accent)]">
                      {source.start_time} – {source.end_time}
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
        </EvidenceDisclosure>
      )}

      {audioSources.length > 0 && (
        <EvidenceDisclosure
          title="Audio events"
          count={audioSources.length}
          icon={<span className="inline-flex" style={{ color: "var(--text-tertiary)" }}><LuAudioLines size={16} strokeWidth={1.5} /></span>}
        >
          <div className="space-y-1">
            {audioSources.map((source, idx) => {
                const eventDetails = getEventDetails(
                  source.event_type || "unknown",
                );
                const EventIcon = EVENT_CATEGORY_ICON[eventDetails.category];
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
                      
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0 }}>
                        <span style={{ display: 'inline-flex', flexShrink: 0, color: 'var(--text-tertiary)' }} aria-hidden="true">
                          <EventIcon size={16} strokeWidth={1.5} />
                        </span>
                        <span style={{ fontSize: '13px', fontWeight: 500, color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {eventDetails.label}
                        </span>
                        {source.speaker && source.speaker !== "Unknown" && (
                          <span style={{ fontSize: '11px', color: 'var(--text-tertiary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {source.speaker}
                          </span>
                        )}
                      </div>
                      
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexShrink: 0 }}>
                        {confidence > 0 && (
                          <span className="mono" style={{ fontSize: '11px', color: 'var(--text-tertiary)' }}>
                            {Math.round(confidence * 100)}%
                          </span>
                        )}
                        {duration && (
                          <span className="mono" style={{ fontSize: '11px', color: 'var(--text-tertiary)' }}>
                            {duration}
                          </span>
                        )}
                        <span
                          className="tc"
                        >
                          {source.start_time}
                        </span>
                      </div>
                    </div>
                  </button>
                );
              })}
          </div>
        </EvidenceDisclosure>
      )}
    </div>
  );
};
