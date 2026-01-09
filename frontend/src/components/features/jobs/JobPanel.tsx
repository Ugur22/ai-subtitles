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

  // Handle job cancellation - remove from storage and refresh list
  const handleCancelJob = useCallback((jobId: string) => {
    removeJob(jobId);
    refetch();
  }, [removeJob, refetch]);

  // Handle permanent job deletion - delete from database/GCS, then remove from storage
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

  // Split jobs by status
  const activeJobs = jobs.filter(
    (j) => j.status === "pending" || j.status === "processing"
  );
  const completedJobs = jobs.filter((j) => j.status === "completed");
  const failedJobs = jobs.filter((j) => j.status === "failed");
  const cancelledJobs = jobs.filter((j) => j.status === "cancelled");

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      onClose();
    }
  };

  return (
    <>
      {/* Backdrop */}
      {isOpen && (
        <div
          className="fixed inset-0 bg-black bg-opacity-25 z-40 transition-opacity"
          onClick={onClose}
          aria-hidden="true"
        />
      )}

      {/* Panel */}
      <div
        className={`fixed right-0 top-0 h-full w-full sm:w-96 bg-white shadow-xl transform transition-transform duration-300 ease-in-out z-50 flex flex-col ${
          isOpen ? "translate-x-0" : "translate-x-full"
        }`}
        onKeyDown={handleKeyDown}
        role="dialog"
        aria-modal="true"
        aria-labelledby="job-panel-title"
      >
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-gray-200 bg-gradient-to-r from-gray-50 to-white flex-shrink-0">
          <div>
            <h2
              id="job-panel-title"
              className="text-lg font-semibold text-gray-900"
            >
              My Transcriptions
            </h2>
            {!isLoading && jobs.length > 0 && (
              <p className="text-xs text-gray-500 mt-0.5">
                {activeJobs.length} active, {completedJobs.length} completed
              </p>
            )}
          </div>
          <button
            onClick={onClose}
            className="p-2 hover:bg-gray-100 rounded-md transition-colors"
            aria-label="Close panel"
          >
            <svg
              className="w-5 h-5 text-gray-600"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M6 18L18 6M6 6l12 12"
              />
            </svg>
          </button>
        </div>

        {/* Offline Warning Banner */}
        {isOffline && (
          <div className="bg-yellow-50 border-b border-yellow-200 p-3 text-sm text-yellow-800 flex items-center gap-2 flex-shrink-0">
            <svg
              className="w-5 h-5 flex-shrink-0"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
              />
            </svg>
            <span>Offline - data may be stale</span>
          </div>
        )}

        {/* Content */}
        <div className="flex-1 overflow-y-auto">
          {isLoading ? (
            <div className="p-8 flex flex-col items-center justify-center text-gray-500">
              <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-gray-900 mb-4"></div>
              <p className="text-sm">Loading jobs...</p>
            </div>
          ) : jobs.length === 0 ? (
            <div className="p-8 text-center">
              <svg
                className="w-16 h-16 mx-auto text-gray-300 mb-4"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={1.5}
                  d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                />
              </svg>
              <h3 className="text-lg font-medium text-gray-900 mb-2">
                No transcription jobs yet
              </h3>
              <p className="text-sm text-gray-500">
                Upload a video to start your first transcription
              </p>
            </div>
          ) : (
            <>
              {/* Active Jobs */}
              {activeJobs.length > 0 && (
                <section className="p-4 border-b border-gray-100">
                  <div className="flex items-center gap-2 mb-3">
                    <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">
                      Active
                    </h3>
                    <span className="px-2 py-0.5 bg-blue-100 text-blue-700 text-xs font-medium rounded-full">
                      {activeJobs.length}
                    </span>
                  </div>
                  <JobList jobs={activeJobs} onViewTranscript={onViewTranscript} onCancel={handleCancelJob} />
                </section>
              )}

              {/* Completed Jobs */}
              {completedJobs.length > 0 && (
                <section className="p-4 border-b border-gray-100">
                  <div className="flex items-center gap-2 mb-3">
                    <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">
                      Completed
                    </h3>
                    <span className="px-2 py-0.5 bg-green-100 text-green-700 text-xs font-medium rounded-full">
                      {completedJobs.length}
                    </span>
                  </div>
                  <JobList
                    jobs={completedJobs}
                    onViewTranscript={onViewTranscript}
                    onDelete={handleDeleteJob}
                  />
                </section>
              )}

              {/* Failed Jobs */}
              {failedJobs.length > 0 && (
                <section className="p-4 border-b border-gray-100">
                  <div className="flex items-center gap-2 mb-3">
                    <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">
                      Failed
                    </h3>
                    <span className="px-2 py-0.5 bg-red-100 text-red-700 text-xs font-medium rounded-full">
                      {failedJobs.length}
                    </span>
                  </div>
                  <JobList
                    jobs={failedJobs}
                    onViewTranscript={onViewTranscript}
                    onDelete={handleDeleteJob}
                  />
                </section>
              )}

              {/* Cancelled Jobs */}
              {cancelledJobs.length > 0 && (
                <section className="p-4">
                  <div className="flex items-center gap-2 mb-3">
                    <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">
                      Cancelled
                    </h3>
                    <span className="px-2 py-0.5 bg-gray-100 text-gray-600 text-xs font-medium rounded-full">
                      {cancelledJobs.length}
                    </span>
                  </div>
                  <JobList
                    jobs={cancelledJobs}
                    onViewTranscript={onViewTranscript}
                    onDelete={handleDeleteJob}
                  />
                </section>
              )}
            </>
          )}
        </div>

        {/* Footer with Pagination */}
        {!isLoading && totalPages > 1 && (
          <div className="border-t border-gray-200 p-4 bg-gray-50 flex-shrink-0">
            <div className="flex items-center justify-between">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page === 1}
                className="px-3 py-2 text-sm font-medium rounded-md border border-gray-300 bg-white text-gray-700 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                aria-label="Previous page"
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
                    d="M15 19l-7-7 7-7"
                  />
                </svg>
              </button>
              <span className="text-sm text-gray-600 font-medium">
                Page {page} of {totalPages}
              </span>
              <button
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page === totalPages}
                className="px-3 py-2 text-sm font-medium rounded-md border border-gray-300 bg-white text-gray-700 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                aria-label="Next page"
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
                    d="M9 5l7 7-7 7"
                  />
                </svg>
              </button>
            </div>
          </div>
        )}

        {/* Refresh Button */}
        {!isLoading && jobs.length > 0 && (
          <div className="border-t border-gray-200 p-3 bg-white flex-shrink-0">
            <button
              onClick={refetch}
              className="w-full py-2 text-sm border border-gray-300 rounded-md bg-white text-gray-700 hover:bg-gray-50 transition-colors flex items-center justify-center gap-2"
              aria-label="Refresh job list"
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
              Refresh
            </button>
          </div>
        )}
      </div>
    </>
  );
};
