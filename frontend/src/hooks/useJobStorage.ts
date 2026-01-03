/**
 * useJobStorage - Custom hook for managing job IDs in localStorage
 * Provides persistent access to user's jobs across sessions
 */

import { useCallback } from 'react';
import { StoredJob } from '../types/job';

const STORAGE_KEY = 'ai-subs-jobs';

export const useJobStorage = () => {
  /**
   * Retrieve all stored job IDs and tokens from localStorage
   */
  const getStoredJobs = useCallback((): StoredJob[] => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      return stored ? JSON.parse(stored) : [];
    } catch (error) {
      console.error('Failed to read jobs from localStorage:', error);
      return [];
    }
  }, []);

  /**
   * Add a new job to localStorage
   * Prevents duplicates and adds to the beginning of the list
   */
  const addJob = useCallback((job: StoredJob) => {
    try {
      const jobs = getStoredJobs();

      // Prevent duplicates
      if (jobs.find(j => j.job_id === job.job_id)) {
        return;
      }

      // Add to beginning (most recent first)
      jobs.unshift(job);
      localStorage.setItem(STORAGE_KEY, JSON.stringify(jobs));
    } catch (error) {
      console.error('Failed to add job to localStorage:', error);
    }
  }, [getStoredJobs]);

  /**
   * Remove a specific job from localStorage
   * Used when user explicitly deletes a job
   */
  const removeJob = useCallback((jobId: string) => {
    try {
      const jobs = getStoredJobs().filter(j => j.job_id !== jobId);
      localStorage.setItem(STORAGE_KEY, JSON.stringify(jobs));
    } catch (error) {
      console.error('Failed to remove job from localStorage:', error);
    }
  }, [getStoredJobs]);

  /**
   * Silent cleanup of orphan job IDs that no longer exist in the database
   * Called automatically when jobs return 404
   */
  const removeInvalidJobs = useCallback((invalidIds: string[]) => {
    if (invalidIds.length === 0) return;

    try {
      const jobs = getStoredJobs().filter(j => !invalidIds.includes(j.job_id));
      localStorage.setItem(STORAGE_KEY, JSON.stringify(jobs));
    } catch (error) {
      console.error('Failed to clean up invalid jobs:', error);
    }
  }, [getStoredJobs]);

  /**
   * Clear all stored jobs
   * Useful for testing or explicit user action
   */
  const clearAllJobs = useCallback(() => {
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch (error) {
      console.error('Failed to clear jobs from localStorage:', error);
    }
  }, []);

  return {
    getStoredJobs,
    addJob,
    removeJob,
    removeInvalidJobs,
    clearAllJobs,
  };
};
