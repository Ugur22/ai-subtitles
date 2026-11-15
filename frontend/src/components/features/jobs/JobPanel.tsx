/**
 * JobPanel - Slide-out panel from the right for managing background jobs
 * Features: Active jobs, Completed jobs, Failed jobs, Pagination, Offline warning
 */

import { useCallback } from "react";
import type { JobTracker } from "../../../hooks/useJobTracker";
import { useJobStorage } from "../../../hooks/useJobStorage";
import { JobList } from "./JobList";
import { Job, isActiveJobStatus } from "../../../types/job";
import toast from "react-hot-toast";

interface JobPanelProps {
  isOpen: boolean;
  onClose: () => void;
  onViewTranscript?: (job: Job) => void;
  /** The page's job list, shared so uploads and deletes show everywhere at once. */
  tracker: JobTracker;
}

export const JobPanel: React.FC<JobPanelProps> = ({
  isOpen,
  onClose,
  onViewTranscript,
  tracker,
}) => {
  const {
    jobs, isLoading, isOffline, page, totalPages, setPage, refetch, deleteJob,
  } = tracker;
  const { removeJob } = useJobStorage();

  const handleCancelJob = useCallback((jobId: string) => {
    removeJob(jobId);
    refetch();
  }, [removeJob, refetch]);

  // Not awaited: the job is already gone from every list, and the request
  // stays open while the server deletes (Cloud Run only gives it CPU then).
  const handleDeleteJob = useCallback((job: Job) => {
    toast.success(`Deleted ${job.filename}`);
    deleteJob(job).catch((error) => {
      console.error("Failed to delete job:", error);
      toast.error(`Couldn't delete ${job.filename}. It's back in your library.`);
    });
  }, [deleteJob]);

  const activeJobs = jobs.filter(j => isActiveJobStatus(j.status));
  const completedJobs = jobs.filter(j => j.status === "completed");
  const failedJobs = jobs.filter(j => j.status === "failed");
  const cancelledJobs = jobs.filter(j => j.status === "cancelled");

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") onClose();
  };

  const sectionChip = (variant: 'accent' | 'success' | 'error' | 'default', label: number) => {
    return (
      <span className="rounded-full px-2 py-0.5 text-xs tabular-nums" style={{ backgroundColor: variant === 'error' ? 'oklch(65% 0.20 25 / 0.10)' : 'var(--bg-subtle)', color: variant === 'error' ? 'var(--c-error)' : 'var(--text-secondary)' }}>{label}</span>
    );
  };

  return (
    <>
      {/* Backdrop */}
      {isOpen && (
        <div
          className="fixed inset-0 z-40 transition-opacity"
          style={{ backgroundColor: 'oklch(11% 0.008 250 / 0.5)' }}
          onClick={onClose}
          aria-hidden="true"
        />
      )}

      {/* Panel */}
      <div
        className={`fixed right-0 top-0 h-full w-full sm:w-[420px] transform transition-transform duration-300 motion-reduce:transition-none ease-in-out z-50 flex flex-col`}
        style={{
          backgroundColor: 'var(--bg-app)',
          borderLeft: '1px solid var(--border-subtle)',
          boxShadow: 'var(--shadow-lg)',
          transform: isOpen ? 'translateX(0)' : 'translateX(100%)',
        }}
        inert={!isOpen}
        aria-hidden={!isOpen}
        onKeyDown={handleKeyDown}
        role="dialog"
        aria-modal="true"
        aria-labelledby="job-panel-title"
      >
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '24px', borderBottom: '1px solid var(--border-subtle)', flexShrink: 0, background: 'var(--bg-surface)' }}>
          <div style={{ minWidth: 0 }}>
            <h2 id="job-panel-title" style={{ fontSize: '20px', fontWeight: 600, color: 'var(--text-primary)', margin: 0, letterSpacing: '-0.01em' }}>
              Library
            </h2>
            {!isLoading && jobs.length > 0 && (
              <p style={{ fontSize: '12px', color: 'var(--text-tertiary)', margin: '4px 0 0' }}>
                {jobs.length} {jobs.length === 1 ? 'transcript' : 'transcripts'}{activeJobs.length > 0 ? ` · ${activeJobs.length} active` : ''}
              </p>
            )}
          </div>
          <button
            onClick={onClose}
            className="btn-ghost"
            style={{ padding: '6px', borderRadius: '6px' }}
            aria-label="Close panel"
          >
            <svg style={{ width: '16px', height: '16px', color: 'var(--text-secondary)' }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Offline Warning */}
        {isOffline && (
          <div style={{ backgroundColor: 'oklch(78% 0.17 75 / 0.08)', borderBottom: '1px solid oklch(78% 0.17 75 / 0.2)', padding: '10px 16px', display: 'flex', alignItems: 'center', gap: '8px', flexShrink: 0 }}>
            <svg style={{ width: '14px', height: '14px', color: 'var(--accent)', flexShrink: 0 }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            <span style={{ fontSize: '12px', color: 'var(--accent)' }}>Offline — data may be stale</span>
          </div>
        )}

        {/* Content */}
        <div className="flex-1 overflow-y-auto">
          {isLoading ? (
            <div className="space-y-4 p-5" role="status" aria-label="Loading jobs">
              <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>Loading your library…</p>
              {[0, 1, 2].map(item => (
                <div key={item} aria-hidden="true" className="space-y-4 rounded-xl border p-4 motion-safe:animate-pulse" style={{ backgroundColor: 'var(--bg-surface)', borderColor: 'var(--border-subtle)' }}>
                  <div className="h-3 w-4/5 rounded" style={{ backgroundColor: 'var(--bg-subtle)' }} />
                  <div className="h-3 w-1/2 rounded" style={{ backgroundColor: 'var(--bg-subtle)' }} />
                  <div className="h-7 w-full rounded-lg" style={{ backgroundColor: 'var(--bg-base)' }} />
                </div>
              ))}
            </div>
          ) : jobs.length === 0 ? (
            <div style={{ padding: '48px 24px', textAlign: 'center' }}>
              <svg style={{ width: '40px', height: '40px', margin: '0 auto 12px', color: 'var(--text-tertiary)' }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
              <p style={{ fontSize: '14px', fontWeight: 500, color: 'var(--text-primary)', marginBottom: '6px' }}>No jobs yet</p>
              <p style={{ fontSize: '13px', color: 'var(--text-tertiary)' }}>Upload a video to start transcribing</p>
            </div>
          ) : (
            <>
              {activeJobs.length > 0 && (
                <section style={{ padding: '20px', borderBottom: '1px solid var(--border-subtle)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
                    <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)' }}>Active</span>
                    {sectionChip('accent', activeJobs.length)}
                  </div>
                  <JobList jobs={activeJobs} onViewTranscript={onViewTranscript} onCancel={handleCancelJob} />
                </section>
              )}

              {completedJobs.length > 0 && (
                <section style={{ padding: '20px', borderBottom: '1px solid var(--border-subtle)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
                    <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)' }}>Completed</span>
                    {sectionChip('success', completedJobs.length)}
                  </div>
                  <JobList jobs={completedJobs} onViewTranscript={onViewTranscript} onDelete={handleDeleteJob} />
                </section>
              )}

              {failedJobs.length > 0 && (
                <section style={{ padding: '20px', borderBottom: '1px solid var(--border-subtle)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
                    <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)' }}>Failed</span>
                    {sectionChip('error', failedJobs.length)}
                  </div>
                  <JobList jobs={failedJobs} onViewTranscript={onViewTranscript} onDelete={handleDeleteJob} />
                </section>
              )}

              {cancelledJobs.length > 0 && (
                <section style={{ padding: '20px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
                    <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)' }}>Cancelled</span>
                    {sectionChip('default', cancelledJobs.length)}
                  </div>
                  <JobList jobs={cancelledJobs} onViewTranscript={onViewTranscript} onDelete={handleDeleteJob} />
                </section>
              )}
            </>
          )}
        </div>

        {/* Pagination */}
        {!isLoading && totalPages > 1 && (
          <div style={{ borderTop: '1px solid var(--border-subtle)', padding: '12px 16px', flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <button
              onClick={() => setPage(p => Math.max(1, p - 1))}
              disabled={page === 1}
              className="btn-ghost"
              style={{ padding: '4px 10px', fontSize: '12px' }}
              aria-label="Previous page"
            >
              <svg style={{ width: '14px', height: '14px' }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
              </svg>
            </button>
            <span style={{ fontSize: '12px', color: 'var(--text-tertiary)', fontVariantNumeric: 'tabular-nums' }}>
              {page} / {totalPages}
            </span>
            <button
              onClick={() => setPage(p => Math.min(totalPages, p + 1))}
              disabled={page === totalPages}
              className="btn-ghost"
              style={{ padding: '4px 10px', fontSize: '12px' }}
              aria-label="Next page"
            >
              <svg style={{ width: '14px', height: '14px' }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
              </svg>
            </button>
          </div>
        )}

        {/* Refresh */}
        {!isLoading && jobs.length > 0 && (
          <div style={{ borderTop: '1px solid var(--border-subtle)', padding: '10px 16px', flexShrink: 0 }}>
            <button
              onClick={refetch}
              className="btn-ghost"
              style={{ width: '100%', justifyContent: 'center', fontSize: '13px', padding: '6px' }}
              aria-label="Refresh job list"
            >
              <svg style={{ width: '13px', height: '13px', marginRight: '6px' }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
              Refresh
            </button>
          </div>
        )}
      </div>
    </>
  );
};
