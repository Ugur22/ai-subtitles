/**
 * JobPanel - Slide-out panel from the right for managing background jobs
 * Features: Active jobs, Completed jobs, Failed jobs, Pagination, Offline warning
 */

import { useCallback } from "react";
import { useJobTracker } from "../../../hooks/useJobTracker";
import { useJobStorage } from "../../../hooks/useJobStorage";
import { JobList } from "./JobList";
import { Job } from "../../../types/job";
import { deleteJobPermanent } from "../../../services/api";
import toast from "react-hot-toast";

interface JobPanelProps {
  isOpen: boolean;
  onClose: () => void;
  onViewTranscript?: (job: Job) => void;
}

export const JobPanel: React.FC<JobPanelProps> = ({
  isOpen,
  onClose,
  onViewTranscript,
}) => {
  const { jobs, isLoading, isOffline, page, totalPages, setPage, refetch } =
    useJobTracker();
  const { removeJob } = useJobStorage();

  const handleCancelJob = useCallback((jobId: string) => {
    removeJob(jobId);
    refetch();
  }, [removeJob, refetch]);

  const handleDeleteJob = useCallback(async (jobId: string, token: string) => {
    try {
      await deleteJobPermanent(jobId, token);
      removeJob(jobId);
      refetch();
      toast.success("Job deleted successfully");
    } catch (error) {
      console.error("Failed to delete job:", error);
      toast.error(error instanceof Error ? error.message : "Failed to delete job");
    }
  }, [removeJob, refetch]);

  const activeJobs = jobs.filter(j => j.status === "pending" || j.status === "processing");
  const completedJobs = jobs.filter(j => j.status === "completed");
  const failedJobs = jobs.filter(j => j.status === "failed");
  const cancelledJobs = jobs.filter(j => j.status === "cancelled");

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") onClose();
  };

  const sectionChip = (variant: 'accent' | 'success' | 'error' | 'default', label: number) => {
    const styleMap: Record<typeof variant, React.CSSProperties> = {
      accent:  { background: 'var(--accent-dim)', color: 'var(--accent)', borderColor: 'var(--accent-border)' },
      success: { background: 'oklch(70% 0.15 145 / 0.12)', color: 'var(--c-success)', borderColor: 'oklch(70% 0.15 145 / 0.30)' },
      error:   { background: 'oklch(65% 0.20 25 / 0.10)', color: 'var(--c-error)', borderColor: 'oklch(65% 0.20 25 / 0.25)' },
      default: { background: 'var(--bg-subtle)', color: 'var(--text-quaternary)', borderColor: 'var(--border-subtle)' },
    };
    return (
      <span className="chip mono" style={{ ...styleMap[variant], padding: '1px 7px' }}>{label}</span>
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
        className={`fixed right-0 top-0 h-full w-full sm:w-96 transform transition-transform duration-300 ease-in-out z-50 flex flex-col`}
        style={{
          backgroundColor: 'var(--bg-app)',
          borderLeft: '1px solid var(--border-subtle)',
          boxShadow: 'var(--shadow-lg)',
          transform: isOpen ? 'translateX(0)' : 'translateX(100%)',
        }}
        onKeyDown={handleKeyDown}
        role="dialog"
        aria-modal="true"
        aria-labelledby="job-panel-title"
      >
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '16px 18px 14px', borderBottom: '1px solid var(--border-subtle)', flexShrink: 0, background: 'var(--bg-surface)' }}>
          <div style={{ minWidth: 0 }}>
            <h2 id="job-panel-title" style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text-primary)', margin: 0, letterSpacing: '-0.01em' }}>
              Library
            </h2>
            {!isLoading && jobs.length > 0 && (
              <p style={{ fontSize: '12px', color: 'var(--text-tertiary)', marginTop: '2px', margin: 0 }}>
                {jobs.length} {jobs.length === 1 ? 'transcript' : 'transcripts'}{activeJobs.length > 0 ? ` · ${activeJobs.length} processing` : ''}
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
            <div style={{ padding: '48px 16px', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '12px' }}>
              <div className="animate-spin rounded-full h-8 w-8" style={{ border: '2px solid var(--border-default)', borderTopColor: 'var(--accent)' }} />
              <p style={{ fontSize: '13px', color: 'var(--text-tertiary)' }}>Loading jobs…</p>
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
                <section style={{ padding: '16px', borderBottom: '1px solid var(--border-subtle)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
                    <span style={{ fontSize: '10.5px', fontWeight: 600, color: 'var(--text-quaternary)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>Active</span>
                    {sectionChip('accent', activeJobs.length)}
                  </div>
                  <JobList jobs={activeJobs} onViewTranscript={onViewTranscript} onCancel={handleCancelJob} />
                </section>
              )}

              {completedJobs.length > 0 && (
                <section style={{ padding: '16px', borderBottom: '1px solid var(--border-subtle)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
                    <span style={{ fontSize: '10.5px', fontWeight: 600, color: 'var(--text-quaternary)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>Completed</span>
                    {sectionChip('success', completedJobs.length)}
                  </div>
                  <JobList jobs={completedJobs} onViewTranscript={onViewTranscript} onDelete={handleDeleteJob} />
                </section>
              )}

              {failedJobs.length > 0 && (
                <section style={{ padding: '16px', borderBottom: '1px solid var(--border-subtle)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
                    <span style={{ fontSize: '10.5px', fontWeight: 600, color: 'var(--text-quaternary)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>Failed</span>
                    {sectionChip('error', failedJobs.length)}
                  </div>
                  <JobList jobs={failedJobs} onViewTranscript={onViewTranscript} onDelete={handleDeleteJob} />
                </section>
              )}

              {cancelledJobs.length > 0 && (
                <section style={{ padding: '16px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
                    <span style={{ fontSize: '10.5px', fontWeight: 600, color: 'var(--text-quaternary)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>Cancelled</span>
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
