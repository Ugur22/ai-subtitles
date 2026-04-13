/**
 * JobCard - Individual job card component with status badge and actions
 * Displays job information, progress, and available actions based on status
 */

import { useState, Fragment } from "react";
import { Menu, Transition } from "@headlessui/react";
import { formatDuration, formatRelativeTime } from "../../../utils/time";
import { ShareJobDialog } from "./ShareJobDialog";
import { Job, JobStatus } from "../../../types/job";
import { cancelJob } from "../../../services/api";

interface JobCardProps {
  job: Job;
  onViewTranscript?: (job: Job) => void;
  onCancel?: (jobId: string) => void;
  onDelete?: (jobId: string, token: string) => void;
  estimatedRemaining?: number;
}

const statusConfig: Record<JobStatus, { label: string; color: string; bg: string; border: string }> = {
  pending:    { label: 'Pending',    color: 'var(--text-tertiary)', bg: 'var(--bg-overlay)',             border: 'var(--border-subtle)' },
  processing: { label: 'Processing', color: 'var(--accent)',         bg: 'var(--accent-dim)',              border: 'oklch(78% 0.17 75 / 0.3)' },
  completed:  { label: 'Completed',  color: 'var(--c-success)',      bg: 'oklch(70% 0.15 145 / 0.12)',    border: 'oklch(70% 0.15 145 / 0.3)' },
  failed:     { label: 'Failed',     color: 'var(--c-error)',        bg: 'oklch(65% 0.20 25 / 0.10)',     border: 'oklch(65% 0.20 25 / 0.25)' },
  cancelled:  { label: 'Cancelled',  color: 'var(--text-tertiary)',  bg: 'var(--bg-overlay)',             border: 'var(--border-subtle)' },
};

export const JobCard: React.FC<JobCardProps> = ({
  job,
  onViewTranscript,
  onCancel,
  onDelete,
  estimatedRemaining,
}) => {
  const [showShare, setShowShare] = useState(false);
  const [isRetrying, setIsRetrying] = useState(false);
  const [isCancelling, setIsCancelling] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);

  const status = statusConfig[job.status];

  const handleRetry = async () => {
    setIsRetrying(true);
    try {
      const response = await fetch(`/api/jobs/${job.job_id}/retry?token=${job.access_token}`, { method: "POST" });
      if (!response.ok) throw new Error("Failed to retry job");
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

  const handleDelete = async () => {
    setIsDeleting(true);
    try {
      await onDelete?.(job.job_id, job.access_token);
    } catch (error) {
      console.error("Failed to delete job:", error);
      setIsDeleting(false);
    }
  };

  return (
    <>
      <div style={{
        backgroundColor: 'var(--bg-surface)',
        border: '1px solid var(--border-subtle)',
        borderRadius: '6px',
        padding: '12px 14px',
        marginBottom: '8px',
      }}>
        {/* Title + badge */}
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '8px', marginBottom: '8px' }}>
          <span style={{ fontSize: '13px', fontWeight: 500, color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }} title={job.filename}>
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
        {job.status === "processing" && (
          <>
            <div style={{ width: '100%', height: '3px', backgroundColor: 'var(--border-subtle)', borderRadius: '2px', overflow: 'hidden', marginBottom: '8px' }}>
              <div
                style={{ height: '100%', backgroundColor: 'var(--accent)', borderRadius: '2px', transition: 'width 300ms ease', width: `${job.progress}%` }}
                role="progressbar" aria-valuenow={job.progress} aria-valuemin={0} aria-valuemax={100}
              />
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: '12px', color: 'var(--text-tertiary)', display: 'flex', alignItems: 'center', gap: '5px' }}>
                <svg style={{ width: '12px', height: '12px', animation: 'spin 1s linear infinite' }} fill="none" viewBox="0 0 24 24">
                  <circle style={{ opacity: 0.25 }} cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path style={{ opacity: 0.75 }} fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                {job.progress_message || "Processing…"}
              </span>
              {estimatedRemaining && estimatedRemaining > 0 && (
                <span style={{ fontSize: '12px', color: 'var(--accent)', fontVariantNumeric: 'tabular-nums' }}>
                  ~{formatDuration(estimatedRemaining)} left
                </span>
              )}
            </div>
          </>
        )}

        {/* Pending */}
        {job.status === "pending" && (
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '4px 0' }}>
            <span style={{ fontSize: '12px', color: 'var(--text-tertiary)', display: 'flex', alignItems: 'center', gap: '5px' }}>
              <svg style={{ width: '13px', height: '13px' }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              Waiting to start…
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
          <div style={{ display: 'flex', gap: '6px', marginTop: '10px' }}>
            <button
              onClick={() => onViewTranscript?.(job)}
              className="btn-primary"
              style={{ flex: 1, justifyContent: 'center', padding: '6px 12px', fontSize: '12px' }}
            >
              View transcript
            </button>
            <button
              onClick={() => setShowShare(true)}
              className="btn-ghost"
              style={{ padding: '6px 8px' }}
              title="Share"
            >
              <svg style={{ width: '14px', height: '14px' }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8.684 13.342C8.886 12.938 9 12.482 9 12c0-.482-.114-.938-.316-1.342m0 2.684a3 3 0 110-2.684m0 2.684l6.632 3.316m-6.632-6l6.632-3.316m0 0a3 3 0 105.367-2.684 3 3 0 00-5.367 2.684zm0 9.316a3 3 0 105.368 2.684 3 3 0 00-5.368-2.684z" />
              </svg>
            </button>
            <Menu as="div" className="relative">
              <Menu.Button className="btn-ghost" style={{ padding: '6px 8px' }} title="Download">
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
              disabled={isDeleting}
              className="btn-ghost"
              style={{ padding: '6px 8px', opacity: isDeleting ? 0.5 : 1 }}
              title="Delete"
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
                {job.error_message || "An error occurred during processing"}
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
                disabled={isDeleting}
                style={{ fontSize: '12px', color: 'var(--text-tertiary)', background: 'none', border: 'none', cursor: 'pointer', opacity: isDeleting ? 0.5 : 1 }}
              >
                {isDeleting ? "Deleting…" : "Delete"}
              </button>
            </div>
          </div>
        )}

        {/* Timestamp */}
        <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', marginTop: '10px', display: 'flex', alignItems: 'center', gap: '4px' }}>
          <svg style={{ width: '11px', height: '11px' }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          {formatRelativeTime(job.created_at)}
        </div>
      </div>

      {showShare && <ShareJobDialog job={job} onClose={() => setShowShare(false)} />}
    </>
  );
};
