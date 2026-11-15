/**
 * useJobTracker - Main hook for managing job state and real-time updates
 * Coordinates job fetching, pagination, real-time subscriptions, and notifications
 */

import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { Job, isActiveJobStatus } from '../types/job';
import { JOBS_CACHE_KEY, useJobStorage } from './useJobStorage';
import { useJobNotifications } from './useJobNotifications';
import { supabase } from '../lib/supabase';
import { deleteJobPermanent, getJobs } from '../services/api';

const JOBS_PER_PAGE = 10;

const pagesFor = (count: number) => Math.max(1, Math.ceil(count / JOBS_PER_PAGE));

// result_json: null marks a row whose transcript must be fetched before opening.
const toCachedJob = (job: Job): Job => ({ ...job, result_json: null });

const readCachedFirstPage = (): Job[] => {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(JOBS_CACHE_KEY) ?? '[]');
    return Array.isArray(parsed) ? (parsed as Job[]).map(toCachedJob) : [];
  } catch {
    return [];
  }
};

export const useJobTracker = () => {
  const [jobs, setJobs] = useState<Job[]>(readCachedFirstPage);
  const [isLoading, setIsLoading] = useState(jobs.length === 0);
  const [isFresh, setIsFresh] = useState(false);
  const [isOffline, setIsOffline] = useState(false);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(pagesFor(jobs.length));
  const [total, setTotal] = useState(jobs.length);
  const pageOnScreenRef = useRef<number | null>(jobs.length > 0 ? 1 : null);
  // Jobs hidden from every view while their DELETE request runs.
  const [hiddenIds, setHiddenIds] = useState<Set<string>>(new Set());

  const { getStoredJobs, removeInvalidJobs, removeJob } = useJobStorage();
  const { notifyJobComplete, notifyJobFailed } = useJobNotifications();

  // Track previously completed jobs to avoid duplicate notifications
  const previouslyCompletedRef = useRef<Set<string>>(new Set());

  /**
   * Fetch jobs from the API using stored access tokens
   */
  const fetchJobs = useCallback(async () => {
    const storedJobs = getStoredJobs();

    try {
      const needsSkeleton = pageOnScreenRef.current !== page;
      if (needsSkeleton) setIsLoading(true);
      setIsOffline(false);

      // Authenticated job lists are scoped by server-side user_id. Stored
      // access tokens are only used for direct shared-job actions.
      const response = await getJobs([], page, JOBS_PER_PAGE);

      // Create a map of job_id -> access_token from stored jobs
      const tokenMap = new Map(storedJobs.map(j => [j.job_id, j.access_token]));

      // Merge access_token into fetched jobs (backend doesn't return tokens for security)
      const jobsWithTokens = response.jobs.map(job => ({
        ...job,
        access_token: tokenMap.get(job.job_id) || '',
      }));

      setJobs(jobsWithTokens);
      pageOnScreenRef.current = page;
      setTotal(response.total);
      setTotalPages(pagesFor(response.total));

      try {
        localStorage.setItem(JOBS_CACHE_KEY, JSON.stringify(jobsWithTokens.map(toCachedJob)));
      } catch (e) {
        console.warn('Failed to cache jobs:', e);
      }

      // Silent cleanup of jobs that no longer exist (404s)
      // Only clean up when we can see ALL jobs to avoid removing tokens for jobs on other pages
      if (response.total <= JOBS_PER_PAGE) {
        const validIds = new Set(jobsWithTokens.map((j: Job) => j.job_id));
        const invalidIds = storedJobs
          .filter(s => !validIds.has(s.job_id))
          .map(s => s.job_id);

        if (invalidIds.length > 0) {
          console.debug(`Cleaning up ${invalidIds.length} expired job(s)`);
          removeInvalidJobs(invalidIds);
        }
      }

    } catch (error) {
      console.error('Failed to fetch jobs:', error);

      setIsOffline(true);
      const cachedJobs = readCachedFirstPage();
      if (cachedJobs.length > 0) {
        setJobs(cachedJobs);
        setTotal(cachedJobs.length);
        setTotalPages(pagesFor(cachedJobs.length));
      }
    } finally {
      setIsLoading(false);
      setIsFresh(true);
    }
  }, [page, getStoredJobs, removeInvalidJobs]);

  /**
   * Subscribe to real-time updates for active jobs
   */
  useEffect(() => {
    // Keep the subscription through final persistence so completion is observed.
    const activeJobIds = jobs
      .filter(j => isActiveJobStatus(j.status))
      .map(j => j.job_id);

    if (activeJobIds.length === 0) {
      return;
    }

    console.debug(`Subscribing to real-time updates for ${activeJobIds.length} active job(s)`);

    // Create a real-time subscription for active jobs
    // Note: Database column is 'id', but frontend uses 'job_id' for the same value
    const subscription = supabase
      .channel('active-jobs-tracker')
      .on(
        'postgres_changes',
        {
          event: 'UPDATE',
          schema: 'public',
          table: 'jobs',
          filter: `id=in.(${activeJobIds.join(',')})`,
        },
        (payload: { new: Record<string, unknown> }) => {
          const updatedJob = payload.new as unknown as Job;

          // Update job in state, preserving the access_token from the existing job
          setJobs(prev =>
            prev.map(j => j.job_id === updatedJob.job_id
              ? { ...updatedJob, access_token: j.access_token }
              : j)
          );

          // Send notification on completion (if not previously notified)
          if (
            updatedJob.status === 'completed' &&
            !previouslyCompletedRef.current.has(updatedJob.job_id)
          ) {
            previouslyCompletedRef.current.add(updatedJob.job_id);
            notifyJobComplete(updatedJob.filename);
          }

          // Send notification on failure
          if (
            updatedJob.status === 'failed' &&
            !previouslyCompletedRef.current.has(updatedJob.job_id)
          ) {
            previouslyCompletedRef.current.add(updatedJob.job_id);
            notifyJobFailed(updatedJob.filename);
          }
        }
      )
      .subscribe();

    // Cleanup subscription on unmount or when active jobs change
    return () => {
      subscription.unsubscribe();
    };
  }, [jobs, notifyJobComplete, notifyJobFailed]);

  /**
   * Track which jobs are already completed on initial load
   * to avoid notifying for jobs that completed in a previous session
   */
  useEffect(() => {
    jobs.forEach(job => {
      if (job.status === 'completed' || job.status === 'failed') {
        previouslyCompletedRef.current.add(job.job_id);
      }
    });
  }, [jobs]);

  /**
   * Fetch jobs when page changes or component mounts
   */
  useEffect(() => {
    fetchJobs();
  }, [fetchJobs]);

  /**
   * Poll jobs while work or final persistence is active.
   * Provides fallback when Supabase real-time fails
   *
   * Polling interval rationale:
   * - Backend progress updates happen at major milestones (5%, 10%, 15%, etc.)
   * - Backend heartbeat interval is 30 seconds
   * - Each processing stage (transcription, diarization) takes 30+ seconds
   * - Real-time subscription is the primary update mechanism (instant)
   * - Polling is just a fallback for when WebSocket fails
   * - 4 minutes = reduced to prevent server overload on Cloud Run
   */
  useEffect(() => {
    const hasActiveJobs = jobs.some(j => isActiveJobStatus(j.status));

    if (!hasActiveJobs) return;

    const intervalId = setInterval(() => {
      fetchJobs();
    }, 30000); // Poll every 30s to keep Cloud Run instance alive during processing

    return () => clearInterval(intervalId);
  }, [jobs, fetchJobs]);

  /**
   * Refetch jobs manually (useful after submission)
   */
  const refetch = useCallback(() => {
    fetchJobs();
  }, [fetchJobs]);

  /**
   * Permanently delete a job. It disappears from every view at once; the
   * request keeps running (up to a minute for a long video), and the job
   * comes back if it fails. Rejects with the request's error.
   */
  const deleteJob = useCallback(async (job: Job) => {
    setHiddenIds(prev => new Set(prev).add(job.job_id));
    try {
      await deleteJobPermanent(job.job_id, job.access_token);
    } catch (error) {
      setHiddenIds(prev => {
        const next = new Set(prev);
        next.delete(job.job_id);
        return next;
      });
      throw error;
    }
    // The id stays hidden on success: the refetch is async, and un-hiding
    // before it lands would flash the job back. Ids are unique, so the set
    // only grows by one entry per deleted job.
    removeJob(job.job_id);
    fetchJobs();
  }, [removeJob, fetchJobs]);

  const visibleJobs = useMemo(
    () => jobs.filter(j => !hiddenIds.has(j.job_id)),
    [jobs, hiddenIds],
  );

  return {
    jobs: visibleJobs,
    deleteJob,
    isLoading,
    isFresh,
    isOffline,
    page,
    totalPages,
    total,
    setPage,
    refetch,
  };
};

export type JobTracker = ReturnType<typeof useJobTracker>;
