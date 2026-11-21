import { isActiveJobStatus, type Job } from "../../../types/job";

interface ActiveJobsSectionProps {
  jobs: Job[];
  onOpenJobPanel: () => void;
}

export const ActiveJobsSection: React.FC<ActiveJobsSectionProps> = ({ jobs, onOpenJobPanel }) => {
  const activeJobs = jobs.filter(job => isActiveJobStatus(job.status));
  if (activeJobs.length === 0) return null;

  return (
    <section className="mb-6" aria-labelledby="active-jobs-heading">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h2 id="active-jobs-heading" className="text-[15px] font-medium text-text-primary">In progress</h2>
        <span className="text-xs text-text-tertiary">You can close this tab</span>
      </div>
      <div className="space-y-3">
        {activeJobs.map(job => (
          <button key={job.job_id} type="button" onClick={onOpenJobPanel} className="block w-full rounded-xl border p-4 text-left transition-colors hover:bg-subtle focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent" style={{ borderColor: 'var(--border-subtle)', backgroundColor: 'var(--bg-surface)' }} aria-label={`View progress for ${job.filename}`}>
            <span className="flex items-start justify-between gap-4">
              <span className="min-w-0 truncate text-sm font-medium" style={{ color: 'var(--text-primary)' }} title={job.filename}>{job.filename}</span>
              <span className="shrink-0 text-xs font-medium tabular-nums" style={{ color: 'var(--accent)' }}>{job.status === 'pending' ? 'Queued' : job.status === 'finalizing' ? 'Finishing up' : job.progress > 0 ? `${Math.round(job.progress)}%` : 'Starting…'}</span>
            </span>
            <span className="mt-2 block text-xs" style={{ color: 'var(--text-secondary)' }}>{job.progress_message || (job.status === 'pending' ? 'Waiting to start' : 'Transcription is running in the background')}</span>
            <span className="mt-3 block h-1 overflow-hidden rounded-full" style={{ backgroundColor: 'var(--bg-subtle)' }}>
              <span className={job.progress > 0 ? 'block h-full rounded-full transition-[width] motion-reduce:transition-none' : job.status === 'pending' ? 'block h-full' : 'job-progress-indeterminate block h-full rounded-full'} style={{ width: job.progress > 0 ? `${Math.min(100, job.progress)}%` : job.status === 'pending' ? '0%' : '35%', backgroundColor: 'var(--accent)' }} />
            </span>
          </button>
        ))}
      </div>
    </section>
  );
};
