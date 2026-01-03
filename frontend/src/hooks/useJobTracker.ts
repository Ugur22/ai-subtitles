/**
 * useJobTracker - Main hook for managing job state and real-time updates
 * Coordinates job fetching, pagination, real-time subscriptions, and notifications
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { Job } from '../types/job';
import { useJobStorage } from './useJobStorage';
import { useJobNotifications } from './useJobNotifications';
import { supabase } from '../lib/supabase';
import { getJobs } from '../services/api';

const JOBS_CACHE_KEY = 'ai-subs-jobs-cache';
const JOBS_PER_PAGE = 10;

export const useJobTracker = () => {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isOffline, setIsOffline] = useState(false);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [total, setTotal] = useState(0);

  const { getStoredJobs, removeInvalidJobs } = useJobStorage();
  const { notifyJobComplete, notifyJobFailed } = useJobNotifications();

  // Track previously completed jobs to avoid duplicate notifications
  const previouslyCompletedRef = useRef<Set<string>>(new Set());

  /**
   * Fetch jobs from the API using stored access tokens
   */
  const fetchJobs = useCallback(async () => {
    const storedJobs = getStoredJobs();

    if (storedJobs.length === 0) {
      setJobs([]);
      setIsLoading(false);
      setTotal(0);
      setTotalPages(1);
      return;
    }

    try {
      setIsLoading(true);
      setIsOffline(false);

      // Call the API with all stored tokens
      const tokens = storedJobs.map(j => j.access_token);
      const response = await getJobs(tokens, page, JOBS_PER_PAGE);

      setJobs(response.jobs);
      setTotal(response.total);
      setTotalPages(Math.ceil(response.total / JOBS_PER_PAGE));

      // Cache jobs for offline fallback
      try {
        localStorage.setItem(JOBS_CACHE_KEY, JSON.stringify(response.jobs));
      } catch (e) {
        console.warn('Failed to cache jobs:', e);
      }

      // Silent cleanup of jobs that no longer exist (404s)
      const validIds = new Set(response.jobs.map((j: Job) => j.job_id));
      const invalidIds = storedJobs
        .filter(s => !validIds.has(s.job_id))
        .map(s => s.job_id);

      if (invalidIds.length > 0) {
        console.debug(`Cleaning up ${invalidIds.length} expired job(s)`);
        removeInvalidJobs(invalidIds);
      }

    } catch (error) {
      console.error('Failed to fetch jobs:', error);

      // Fallback to cached data if available
      setIsOffline(true);
      try {
        const cached = localStorage.getItem(JOBS_CACHE_KEY);
        if (cached) {
          const cachedJobs = JSON.parse(cached);
          setJobs(cachedJobs);
          setTotal(cachedJobs.length);
          setTotalPages(Math.ceil(cachedJobs.length / JOBS_PER_PAGE));
        }
      } catch (e) {
        console.error('Failed to load cached jobs:', e);
      }
    } finally {
      setIsLoading(false);
    }
  }, [page, getStoredJobs, removeInvalidJobs]);

  /**
   * Subscribe to real-time updates for active jobs
   */
  useEffect(() => {
    // Only subscribe to jobs that are pending or processing
    const activeJobIds = jobs
      .filter(j => j.status === 'pending' || j.status === 'processing')
      .map(j => j.job_id);

    if (activeJobIds.length === 0) {
      return;
    }

    console.debug(`Subscribing to real-time updates for ${activeJobIds.length} active job(s)`);

    // Create a real-time subscription for active jobs
    const subscription = supabase
      .channel('active-jobs-tracker')
      .on(
        'postgres_changes',
        {
          event: 'UPDATE',
          schema: 'public',
          table: 'transcription_jobs',
          filter: `job_id=in.(${activeJobIds.join(',')})`,
        },
        (payload: { new: Record<string, unknown> }) => {
          const updatedJob = payload.new as Job;

          // Update job in state
          setJobs(prev =>
            prev.map(j => j.job_id === updatedJob.job_id ? updatedJob : j)
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
   * Refetch jobs manually (useful after submission)
   */
  const refetch = useCallback(() => {
    fetchJobs();
  }, [fetchJobs]);

  return {
    jobs,
    isLoading,
    isOffline,
    page,
    totalPages,
    total,
    setPage,
    refetch,
  };
};
