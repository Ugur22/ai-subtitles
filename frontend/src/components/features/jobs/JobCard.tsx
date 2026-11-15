/**
 * JobCard - Individual job card component with status badge and actions
 * Displays job information, progress, and available actions based on status
 */

import { useState, Fragment } from "react";
import { Menu, Transition } from "@headlessui/react";
import { formatDuration, formatRelativeTime } from "../../../utils/time";
import { Job, JobStatus, isActiveJobStatus } from "../../../types/job";
import { cancelJob, retryJob } from "../../../services/api";

interface JobCardProps {
  job: Job;
  onViewTranscript?: (job: Job) => void;
  onCancel?: (jobId: string) => void;
  onDelete?: (job: Job) => void;
  estimatedRemaining?: number;
}

const statusConfig: Record<JobStatus, { label: string; color: string; bg: string; border: string }> = {
  pending:    { label: 'Queued',    color: 'var(--text-tertiary)', bg: 'var(--bg-overlay)',             border: 'var(--border-subtle)' },
  processing: { label: 'Processing', color: 'var(--accent)',         bg: 'var(--accent-dim)',              border: 'var(--accent-border)' },
  finalizing: { label: 'Finalizing', color: 'var(--accent)',         bg: 'var(--accent-dim)',              border: 'var(--accent-border)' },
  completed:  { label: 'Completed',  color: 'var(--c-success)',      bg: 'oklch(70% 0.15 145 / 0.12)',    border: 'oklch(70% 0.15 145 / 0.3)' },
  failed:     { label: 'Failed',     color: 'var(--c-error)',        bg: 'oklch(65% 0.20 25 / 0.10)',     border: 'oklch(65% 0.20 25 / 0.25)' },
  cancelled:  { label: 'Cancelled',  color: 'var(--text-tertiary)',  bg: 'var(--bg-overlay)',             border: 'var(--border-subtle)' },
};

// Failures the user can act on get a fixed explanation instead of the raw backend message.
const FAILURE_MESSAGES: Record<string, string> = {
  worker_timeout:
    "Processing ran out of time before this file was finished. Your progress is saved. We retry once automatically; if this still shows as failed, press Retry to continue from where it stopped.",
  connection_lost:
    "Lost the connection while saving your results. Your progress is saved; press Retry to finish.",
  max_continuations_reached:
    "This file needed more processing runs than allowed. Your progress is saved; press Retry to continue from where it stopped.",
};

export const JobCard: React.FC<JobCardProps> = ({
  job,
  onViewTranscript,
  onCancel,
  onDelete,
  estimatedRemaining,
}) => {
  const [isRetrying, setIsRetrying] = useState(false);
  const [isCancelling, setIsCancelling] = useState(false);

  const status = statusConfig[job.status];
  const progress = Math.min(100, Math.max(0, job.progress || 0));

  const handleRetry = async () => {
    setIsRetrying(true);
    try {
      // Must go through the shared client: the auth cookie belongs to the API
      // host, so a same-origin fetch to /api reaches the backend without it.
      await retryJob(job.job_id, job.access_token);
    } catch (error) {
      console.error("Failed to retry job:", error);
    } finally {
      setIsRetrying(false);
    }
  };

  const handleCancel = async () => {
    setIsCancelling(true);
    try {
      await cancelJob(job.job_id, job.access_token);
      onCancel?.(job.job_id);
    } catch (error) {
      console.error("Failed to cancel job:", error);
      setIsCancelling(false);
    }
  };

  // The card disappears on click (the tracker hides the job), so it keeps
  // no "deleting" state of its own.
  const handleDelete = () => onDelete?.(job);

  return (
    <>
      <div style={{
        backgroundColor: 'var(--bg-surface)',
        border: '1px solid var(--border-subtle)',
        borderRadius: '12px',
        padding: '16px',
      }}>
        {/* Title + badge */}
        <div style={{ display: 'flex', alignItems: 'flex-start', flexDirection: 'column', gap: '10px', marginBottom: '14px' }}>
          <span style={{ fontSize: '13px', fontWeight: 500, color: 'var(--text-primary)', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden', overflowWrap: 'anywhere', lineHeight: 1.5 }} title={job.filename}>
            {job.filename}
          </span>
          <span style={{
            padding: '2px 7px', borderRadius: '9999px', fontSize: '11px', fontWeight: 500, flexShrink: 0,
            color: status.color, backgroundColor: status.bg, border: `1px solid ${status.border}`,
          }}>
            {status.label}
          </span>
        </div>

        {/* Cached notice */}
        {job.cached && job.cached_at && (
          <div style={{ fontSize: '12px', color: 'var(--text-secondary)', backgroundColor: 'var(--bg-overlay)', border: '1px solid var(--border-subtle)', borderRadius: '4px', padding: '6px 10px', marginBottom: '10px', display: 'flex', alignItems: 'center', gap: '6px' }}>
            <svg style={{ width: '13px', height: '13px', flexShrink: 0 }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            Result from {new Date(job.cached_at).toLocaleDateString()}
          </div>
        )}

        {/* Processing */}
        {isActiveJobStatus(job.status) && job.status !== "pending" && (
          <>
            <div className="mb-2 flex items-baseline justify-between gap-3">
              <span className="text-xs font-medium" style={{ color: 'var(--text-secondary)' }}>{job.status === 'finalizing' ? 'Saving transcript' : 'Transcribing'}</span>
              <span className="text-sm font-medium tabular-nums" style={{ color: 'var(--accent)' }}>{progress > 0 ? `${Math.round(progress)}%` : 'Starting…'}</span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full" style={{ backgroundColor: 'var(--bg-subtle)' }} role="progressbar" aria-label={`Transcription progress for ${job.filename}`} aria-valuenow={progress > 0 ? progress : undefined} aria-valuemin={0} aria-valuemax={100}>
              <div className={progress > 0 ? 'h-full rounded-full transition-[width] duration-500 motion-reduce:transition-none' : 'job-progress-indeterminate h-full rounded-full'} style={{ backgroundColor: 'var(--accent)', width: progress > 0 ? `${progress}%` : '35%' }} />
            </div>
            <p className="mt-3 text-xs leading-relaxed" style={{ color: 'var(--text-secondary)', overflowWrap: 'anywhere' }}>
              {job.progress_message || (job.status === 'finalizing' ? 'Saving your transcript and finishing up…' : 'Working through your file. You can close this panel.')}
            </p>
            {estimatedRemaining !== undefined && estimatedRemaining > 0 && (
              <p className="mt-1 text-xs tabular-nums" style={{ color: 'var(--text-tertiary)' }}>About {formatDuration(estimatedRemaining)} remaining</p>
            )}
          </>
        )}

        {/* Pending */}
        {job.status === "pending" && (
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '4px 0' }}>
            <span style={{ fontSize: '12px', color: 'var(--text-tertiary)', display: 'flex', alignItems: 'center', gap: '5px' }}>
              <svg style={{ width: '13px', height: '13px' }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              {job.progress_stage === "continuing"
                ? job.progress_message || "Continuing in a new worker…"
                : "Waiting to start…"}
            </span>
            <button
              onClick={handleCancel}
              disabled={isCancelling}
              style={{ fontSize: '12px', color: 'var(--c-error)', background: 'none', border: 'none', cursor: 'pointer', opacity: isCancelling ? 0.5 : 1 }}
            >
              {isCancelling ? "Cancelling…" : "Cancel"}
            </button>
          </div>
        )}

        {/* Completed */}
        {job.status === "completed" && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '10px' }}>
            <button
              onClick={() => onViewTranscript?.(job)}
              className="btn-ghost"
              style={{ flex: 1, minHeight: '36px', justifyContent: 'center', padding: '8px 10px', fontSize: '12px', color: 'var(--accent)', backgroundColor: 'var(--accent-dim)', borderRadius: '8px' }}
            >
              View transcript
            </button>
            <Menu as="div" className="relative flex shrink-0">
              <Menu.Button className="btn-ghost" style={{ width: '36px', height: '36px', padding: 0, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, borderRadius: '8px' }} title="Download" aria-label="Download transcript">
                <svg style={{ width: '14px', height: '14px' }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                </svg>
              </Menu.Button>
              <Transition
                as={Fragment}
                enter="transition ease-out duration-100"
                enterFrom="transform opacity-0 scale-95"
                enterTo="transform opacity-100 scale-100"
                leave="transition ease-in duration-75"
                leaveFrom="transform opacity-100 scale-100"
                leaveTo="transform opacity-0 scale-95"
              >
                <Menu.Items
                  className="absolute right-0 mt-1 py-1 z-20"
                  style={{
                    minWidth: '140px',
                    backgroundColor: 'var(--bg-overlay)',
                    border: '1px solid var(--border-subtle)',
                    borderRadius: '6px',
                    boxShadow: '0 8px 24px oklch(0% 0 0 / 0.5)',
                    top: '100%',
                  }}
                >
                  {job.access_token ? (
                    <>
                      <Menu.Item>
                        {({ active }) => (
                          <a
                            href={`/api/jobs/${job.job_id}/download/srt?token=${job.access_token}`}
                            download
                            style={{ display: 'block', padding: '8px 14px', fontSize: '13px', textDecoration: 'none', color: active ? 'var(--text-primary)' : 'var(--text-secondary)', backgroundColor: active ? 'var(--bg-surface)' : 'transparent' }}
                          >
                            SRT
                          </a>
                        )}
                      </Menu.Item>
                      <Menu.Item>
                        {({ active }) => (
                          <a
                            href={`/api/jobs/${job.job_id}/download/vtt?token=${job.access_token}`}
                            download
                            style={{ display: 'block', padding: '8px 14px', fontSize: '13px', textDecoration: 'none', borderTop: '1px solid var(--border-subtle)', color: active ? 'var(--text-primary)' : 'var(--text-secondary)', backgroundColor: active ? 'var(--bg-surface)' : 'transparent' }}
                          >
                            VTT
                          </a>
                        )}
                      </Menu.Item>
                      <Menu.Item>
                        {({ active }) => (
                          <a
                            href={`/api/jobs/${job.job_id}/download/json?token=${job.access_token}`}
                            download
                            style={{ display: 'block', padding: '8px 14px', fontSize: '13px', textDecoration: 'none', borderTop: '1px solid var(--border-subtle)', color: active ? 'var(--text-primary)' : 'var(--text-secondary)', backgroundColor: active ? 'var(--bg-surface)' : 'transparent' }}
                          >
                            JSON
                          </a>
                        )}
                      </Menu.Item>
                    </>
                  ) : (
                    <div style={{ padding: '8px 14px', fontSize: '13px', color: 'var(--text-tertiary)' }}>Unavailable</div>
                  )}
                </Menu.Items>
              </Transition>
            </Menu>
            <button
              onClick={handleDelete}
              className="btn-ghost"
              style={{ width: '36px', height: '36px', padding: 0, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, borderRadius: '8px' }}
              title="Delete"
              aria-label="Delete transcript"
            >
              <svg style={{ width: '14px', height: '14px', color: 'var(--text-tertiary)' }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
            </button>
          </div>
        )}

        {/* Failed */}
        {job.status === "failed" && (
          <div style={{ marginTop: '8px' }}>
            <div style={{ backgroundColor: 'oklch(65% 0.20 25 / 0.08)', border: '1px solid oklch(65% 0.20 25 / 0.25)', borderRadius: '4px', padding: '8px 12px', marginBottom: '10px', display: 'flex', gap: '8px', alignItems: 'flex-start' }}>
              <svg style={{ width: '14px', height: '14px', color: 'var(--c-error)', flexShrink: 0, marginTop: '1px' }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <p style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                {(job.error_code && FAILURE_MESSAGES[job.error_code]) || job.error_message || "An error occurred during processing"}
              </p>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <button
                onClick={handleRetry}
                disabled={isRetrying}
                style={{ fontSize: '12px', color: 'var(--accent)', background: 'none', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '4px', opacity: isRetrying ? 0.5 : 1 }}
              >
                <svg style={{ width: '12px', height: '12px' }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
                {isRetrying ? "Retrying…" : "Retry"}
              </button>
              <button
                onClick={handleDelete}
                style={{ fontSize: '12px', color: 'var(--text-tertiary)', background: 'none', border: 'none', cursor: 'pointer' }}
              >
                Delete
              </button>
            </div>
          </div>
        )}

        {/* Timestamp */}
        <div style={{ fontSize: '12px', lineHeight: '20px', color: 'var(--text-secondary)', marginTop: '16px', paddingTop: '12px', borderTop: '1px solid var(--border-subtle)', display: 'flex', alignItems: 'center', gap: '7px', fontVariantNumeric: 'tabular-nums' }}>
          <svg style={{ width: '14px', height: '14px', flexShrink: 0 }} aria-hidden="true" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <time dateTime={job.created_at} title={new Date(job.created_at).toLocaleString()}>{formatRelativeTime(job.created_at)}</time>
        </div>
      </div>

    </>
  );
};
