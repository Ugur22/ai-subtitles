/**
 * JobCard - Individual job card component with status badge and actions
 * Displays job information, progress, and available actions based on status
 */

import { useState } from "react";
import { formatDuration, formatRelativeTime } from "../../../utils/time";
import { ShareJobDialog } from "./ShareJobDialog";
import { Job, JobStatus } from "../../../types/job";
import { cancelJob } from "../../../services/api";

interface JobCardProps {
  job: Job;
  onViewTranscript?: (job: Job) => void;
  onCancel?: (jobId: string) => void;
  estimatedRemaining?: number;
}

export const JobCard: React.FC<JobCardProps> = ({
  job,
  onViewTranscript,
  onCancel,
  estimatedRemaining,
}) => {
  const [showShare, setShowShare] = useState(false);
  const [isRetrying, setIsRetrying] = useState(false);
  const [isCancelling, setIsCancelling] = useState(false);

  const statusStyles: Record<JobStatus, string> = {
    pending: "bg-gray-100 text-gray-700",
    processing: "bg-blue-100 text-blue-700",
    completed: "bg-green-100 text-green-700",
    failed: "bg-red-100 text-red-700",
    cancelled: "bg-gray-100 text-gray-500",
  };

  const handleRetry = async () => {
    setIsRetrying(true);
    try {
      const response = await fetch(
        `/api/jobs/${job.job_id}/retry?token=${job.access_token}`,
        {
          method: "POST",
        }
      );

      if (!response.ok) {
        throw new Error("Failed to retry job");
      }
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
      // Successfully cancelled - notify parent to remove from list
      onCancel?.(job.job_id);
    } catch (error) {
      console.error("Failed to cancel job:", error);
      // Reset state so user can try again
      setIsCancelling(false);
    }
  };

  return (
    <>
      <div className="bg-white rounded-lg border border-gray-200 p-4 mb-3 hover:shadow-md transition-shadow">
        <div className="flex items-start justify-between mb-2">
          <span
            className="font-medium text-gray-900 truncate flex-1 text-sm"
            title={job.filename}
          >
            {job.filename}
          </span>
          <span
            className={`px-2 py-0.5 rounded text-xs font-medium ml-2 flex-shrink-0 ${
              statusStyles[job.status]
            }`}
          >
            {job.status.charAt(0).toUpperCase() + job.status.slice(1)}
          </span>
        </div>

        {/* Cached Result Notice */}
        {job.cached && job.cached_at && (
          <div className="text-xs text-blue-600 bg-blue-50 border border-blue-200 rounded px-2 py-1.5 mb-2 flex items-center gap-1.5">
            <svg
              className="w-3.5 h-3.5 flex-shrink-0"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
              />
            </svg>
            <span>
              Result from previous processing on{" "}
              {new Date(job.cached_at).toLocaleDateString()}
            </span>
          </div>
        )}

        {/* Processing State */}
        {job.status === "processing" && (
          <>
            <div className="w-full bg-gray-200 rounded-full h-2 mb-2">
              <div
                className="bg-blue-500 h-2 rounded-full transition-all duration-300"
                style={{ width: `${job.progress}%` }}
                role="progressbar"
                aria-valuenow={job.progress}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-label="Job progress"
              />
            </div>
            <div className="flex justify-between items-center text-xs text-gray-600">
              <span className="flex items-center gap-1">
                <svg
                  className="w-3 h-3 animate-spin"
                  fill="none"
                  viewBox="0 0 24 24"
                >
                  <circle
                    className="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="4"
                  />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                  />
                </svg>
                {job.progress_message || "Processing..."}
              </span>
              {estimatedRemaining && estimatedRemaining > 0 && (
                <span className="text-blue-600 font-medium">
                  ~{formatDuration(estimatedRemaining)} remaining
                </span>
              )}
            </div>
          </>
        )}

        {/* Pending State */}
        {job.status === "pending" && (
          <div className="flex justify-between items-center py-2">
            <span className="text-sm text-gray-500 flex items-center gap-1.5">
              <svg
                className="w-4 h-4 text-gray-400"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"
                />
              </svg>
              Waiting to start...
            </span>
            <button
              onClick={handleCancel}
              disabled={isCancelling}
              className="text-xs text-red-600 hover:text-red-700 hover:underline disabled:opacity-50 disabled:cursor-not-allowed"
              aria-label="Cancel job"
            >
              {isCancelling ? "Cancelling..." : "Cancel"}
            </button>
          </div>
        )}

        {/* Completed State */}
        {job.status === "completed" && (
          <div className="flex gap-2 mt-3">
            <button
              onClick={() => onViewTranscript?.(job)}
              className="flex-1 bg-blue-600 text-white py-2 px-3 rounded-md text-sm font-medium hover:bg-blue-700 transition-colors flex items-center justify-center gap-1.5"
              aria-label="View transcript"
            >
              <svg
                className="w-4 h-4"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M15 12a3 3 0 11-6 0 3 3 0 016 0z M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"
                />
              </svg>
              View Transcript
            </button>
            <button
              onClick={() => setShowShare(true)}
              className="p-2 border border-gray-300 rounded-md hover:bg-gray-50 transition-colors"
              title="Share job"
              aria-label="Share job"
            >
              <svg
                className="w-4 h-4 text-gray-600"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M8.684 13.342C8.886 12.938 9 12.482 9 12c0-.482-.114-.938-.316-1.342m0 2.684a3 3 0 110-2.684m0 2.684l6.632 3.316m-6.632-6l6.632-3.316m0 0a3 3 0 105.367-2.684 3 3 0 00-5.367 2.684zm0 9.316a3 3 0 105.368 2.684 3 3 0 00-5.368-2.684z"
                />
              </svg>
            </button>
            <div className="relative group">
              <button
                className="p-2 border border-gray-300 rounded-md hover:bg-gray-50 transition-colors"
                title="Download formats"
                aria-label="Download formats"
              >
                <svg
                  className="w-4 h-4 text-gray-600"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"
                  />
                </svg>
              </button>
              <div className="absolute right-0 top-full mt-1 bg-white border border-gray-200 rounded-md shadow-lg hidden group-hover:block z-10 min-w-[160px]">
                <a
                  href={`/api/jobs/${job.job_id}/download/srt?token=${job.access_token}`}
                  className="block px-4 py-2 hover:bg-gray-50 text-sm text-gray-700 transition-colors"
                  download
                >
                  Download SRT
                </a>
                <a
                  href={`/api/jobs/${job.job_id}/download/vtt?token=${job.access_token}`}
                  className="block px-4 py-2 hover:bg-gray-50 text-sm text-gray-700 transition-colors border-t border-gray-100"
                  download
                >
                  Download VTT
                </a>
                <a
                  href={`/api/jobs/${job.job_id}/download/json?token=${job.access_token}`}
                  className="block px-4 py-2 hover:bg-gray-50 text-sm text-gray-700 transition-colors border-t border-gray-100"
                  download
                >
                  Download JSON
                </a>
              </div>
            </div>
          </div>
        )}

        {/* Failed State */}
        {job.status === "failed" && (
          <div className="mt-2">
            <div className="bg-red-50 border border-red-200 rounded-md p-3 mb-2">
              <div className="flex gap-2">
                <svg
                  className="w-5 h-5 text-red-500 flex-shrink-0"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                  />
                </svg>
                <p className="text-sm text-red-700 flex-1">
                  {job.error_message || "An error occurred during processing"}
                </p>
              </div>
            </div>
            <button
              onClick={handleRetry}
              disabled={isRetrying}
              className="text-sm text-blue-600 hover:text-blue-700 hover:underline font-medium disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1.5"
              aria-label="Retry job"
            >
              <svg
                className="w-4 h-4"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
                />
              </svg>
              {isRetrying ? "Retrying..." : "Retry with same settings"}
            </button>
          </div>
        )}

        {/* Timestamp */}
        <div className="text-xs text-gray-400 mt-3 flex items-center gap-1">
          <svg
            className="w-3 h-3"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"
            />
          </svg>
          {formatRelativeTime(job.created_at)}
        </div>
      </div>

      {showShare && (
        <ShareJobDialog job={job} onClose={() => setShowShare(false)} />
      )}
    </>
  );
};
