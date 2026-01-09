/**
 * JobList - Simple list wrapper that maps jobs to JobCard components
 * Provides a clean layout for displaying multiple job cards
 */

import { JobCard } from "./JobCard";
import { Job } from "../../../types/job";

interface JobListProps {
  jobs: Job[];
  onViewTranscript?: (job: Job) => void;
  onCancel?: (jobId: string) => void;
  onDelete?: (jobId: string, token: string) => void;
}

export const JobList: React.FC<JobListProps> = ({ jobs, onViewTranscript, onCancel, onDelete }) => {
  if (jobs.length === 0) {
    return null;
  }

  return (
    <div className="space-y-3">
      {jobs.map((job) => (
        <JobCard
          key={job.job_id}
          job={job}
          onViewTranscript={onViewTranscript}
          onCancel={onCancel}
          onDelete={onDelete}
        />
      ))}
    </div>
  );
};
