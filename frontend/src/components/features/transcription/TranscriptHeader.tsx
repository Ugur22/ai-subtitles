import { useState } from "react";
import { ChevronLeftIcon, ChevronRightIcon } from "@heroicons/react/24/outline";
import type { TranscriptionResponse } from "../../../services/api";
import { formatProcessingTime } from "../../../utils/time";
import { SubtitleControls } from "./SubtitleControls";

interface TranscriptHeaderProps {
  transcription: TranscriptionResponse;
  onClose: () => void;
  displayDuration: string;
  languageLabel: string | undefined;
}

export const TranscriptHeader: React.FC<TranscriptHeaderProps> = ({
  transcription,
  onClose,
  displayDuration,
  languageLabel,
}) => {
  const [isHeaderExpanded, setIsHeaderExpanded] = useState(false);

  return (
    <div className="flex-shrink-0" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
      <div className="flex h-12 items-center justify-between gap-3 px-1">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <button
            type="button"
            onClick={onClose}
            className="btn-ghost inline-flex shrink-0 items-center gap-1 px-2 py-1 text-[13px]"
            style={{ color: 'var(--text-secondary)' }}
          >
            <ChevronLeftIcon className="h-4 w-4" strokeWidth={1.5} aria-hidden="true" />
            All videos
          </button>
          <ChevronRightIcon className="h-4 w-4 shrink-0" strokeWidth={1.5} style={{ color: 'var(--text-tertiary)' }} aria-hidden="true" />
          <h2
            className="min-w-0 max-w-[360px] truncate text-sm font-medium"
            style={{ color: 'var(--text-primary)' }}
            title={transcription.filename}
          >
            {transcription.filename}
          </h2>
          {!isHeaderExpanded && (
            <span className="shrink-0 font-mono text-xs tabular-nums" style={{ color: 'var(--text-tertiary)' }}>
              {[displayDuration, languageLabel]
                .filter(Boolean)
                .join(' · ')}
            </span>
          )}
        </div>

        <div className="flex shrink-0 items-center gap-1">
          <SubtitleControls
            filename={transcription.filename}
            videoHash={transcription.video_hash}
          />

          <div className="mx-1 h-4 w-px" style={{ backgroundColor: 'var(--border-subtle)' }} />

          <button
            onClick={() => setIsHeaderExpanded(!isHeaderExpanded)}
            className="btn-ghost p-2"
            style={{ color: 'var(--text-secondary)' }}
            title={isHeaderExpanded ? "Hide details" : "Show details"}
            aria-expanded={isHeaderExpanded}
          >
            <svg
              className={`w-4 h-4 transition-transform duration-200 motion-reduce:transition-none${isHeaderExpanded ? ' rotate-180' : ''}`}
              fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19 9l-7 7-7-7" />
            </svg>
          </button>
        </div>
      </div>

      {isHeaderExpanded && (
        <dl className="animate-fade-in flex h-9 flex-wrap items-center gap-x-6 px-3">
          {[
            { label: 'Duration', value: displayDuration, mono: true },
            { label: 'Language', value: languageLabel, mono: true },
            { label: 'Processing', value: formatProcessingTime(transcription.transcription.processing_time), mono: false },
          ]
            .filter(({ value }) => value)
            .map(({ label, value, mono }) => (
              <div key={label} className="flex items-baseline gap-2">
                <dt className="text-xs" style={{ color: 'var(--text-tertiary)' }}>{label}</dt>
                <dd className={`text-[13px]${mono ? ' font-mono tabular-nums' : ''}`} style={{ color: 'var(--text-primary)' }}>
                  {value}
                </dd>
              </div>
            ))}
        </dl>
      )}
    </div>
  );
};
