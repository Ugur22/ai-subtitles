import React, { useState } from "react";
import { Job } from "../../../types/job";
import { formatRelativeTime } from "../../../utils/time";
import { getFileExtension } from "../../../utils/file";

interface RecentTranscriptionsProps {
  jobs: Job[];
  onViewJob: (job: Job) => void | Promise<void>;
  onViewAll: () => void;
  isLoading?: boolean;
}

const languageNames = (() => {
  try {
    return new Intl.DisplayNames(["en"], { type: "language" });
  } catch {
    return null;
  }
})();

const languageLabel = (code: string | null): string | null => {
  if (!code) return null;
  try {
    return languageNames?.of(code) ?? null;
  } catch {
    return null;
  }
};

const ChevronIcon: React.FC<{ className?: string }> = ({ className }) => (
  <svg
    className={className}
    fill="none"
    stroke="currentColor"
    viewBox="0 0 24 24"
    strokeWidth={2}
    aria-hidden="true"
  >
    <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
  </svg>
);

const SkeletonRow: React.FC = () => (
  <div className="flex items-center gap-4 px-4 py-3" aria-hidden="true">
    <div className="recent-skeleton h-3 w-9 rounded-xs" />
    <div className="min-w-0 flex-1">
      <div className="recent-skeleton mb-2 h-3 w-[55%] rounded-xs" />
      <div className="recent-skeleton h-2.5 w-1/4 rounded-xs" />
    </div>
  </div>
);

export const RecentTranscriptions: React.FC<RecentTranscriptionsProps> = ({
  jobs,
  onViewJob,
  onViewAll,
  isLoading = false,
}) => {
  // Cached rows have no result_json, so opening one fetches the job first; without
  // feedback a slow (cold-start) fetch reads as a dead click.
  const [openingId, setOpeningId] = useState<string | null>(null);

  const recent = jobs
    .filter((j) => j.status === "completed")
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    .slice(0, 5);

  if (!isLoading && recent.length === 0) return null;

  const open = async (job: Job) => {
    if (openingId) return;
    setOpeningId(job.job_id);
    try {
      await onViewJob(job);
    } finally {
      setOpeningId(null);
    }
  };

  return (
    <section className="mx-auto mt-10 max-w-[720px]" aria-labelledby="recent-heading">
      <div className="mx-1 mb-2.5 flex items-baseline justify-between">
        <h2 id="recent-heading" className="m-0 text-sm font-semibold text-text-secondary">
          Recent
        </h2>
        {!isLoading && (
          <button
            type="button"
            onClick={onViewAll}
            className="btn-ghost inline-flex items-center gap-1 px-2 py-1 text-[12.5px] font-medium"
          >
            View all
            <ChevronIcon className="h-3 w-3" />
          </button>
        )}
      </div>

      <div className="divide-y divide-border-subtle overflow-hidden rounded-lg border border-border-subtle bg-surface">
        {isLoading && recent.length === 0 && (
          <>
            <SkeletonRow />
            <SkeletonRow />
            <SkeletonRow />
          </>
        )}
        {recent.map((job) => {
          const title = job.display_title?.trim() || job.filename.replace(/\.[^./]+$/, "");
          const duration = job.result_json?.transcription?.duration;
          const lead = duration || getFileExtension(job.filename).toUpperCase();
          const language = languageLabel(job.language);
          const isOpening = openingId === job.job_id;

          return (
            <button
              key={job.job_id}
              type="button"
              onClick={() => open(job)}
              title={job.filename}
              aria-label={`Open ${job.filename}`}
              aria-busy={isOpening}
              disabled={openingId !== null && !isOpening}
              className="group flex w-full items-center gap-4 bg-transparent px-4 py-3 text-left transition-colors duration-100 enabled:hover:bg-subtle focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent disabled:cursor-default disabled:opacity-55"
            >
              <span className="w-[52px] shrink-0 truncate font-mono text-[11.5px] tabular-nums text-text-tertiary">
                {lead}
              </span>
              <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                <span className="truncate text-sm font-medium text-text-primary">{title}</span>
                <span className="text-xs text-text-tertiary">
                  {formatRelativeTime(job.created_at)}
                  {language ? ` · ${language}` : ""}
                </span>
              </span>
              {isOpening ? (
                <span
                  className="h-3.5 w-3.5 shrink-0 animate-spin rounded-full border-2 border-border-subtle border-t-accent"
                  aria-hidden="true"
                />
              ) : (
                <ChevronIcon className="h-3.5 w-3.5 shrink-0 text-text-quaternary transition-transform duration-100 group-enabled:group-hover:translate-x-0.5 group-enabled:group-hover:text-text-secondary motion-reduce:transform-none" />
              )}
            </button>
          );
        })}
      </div>
    </section>
  );
};
