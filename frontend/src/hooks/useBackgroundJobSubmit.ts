/**
 * useBackgroundJobSubmit - Hook for submitting files as background jobs
 *
 * Handles the complete submission flow:
 * 1. File hashing (for deduplication)
 * 2. GCS upload
 * 3. Job submission
 * 4. Storage in localStorage
 * 5. Triggering refetch of job list
 */

import { useState, useCallback } from 'react';
import { useJobStorage } from './useJobStorage';
import { submitBackgroundJob, type SubmissionProgress } from '../services/api';
import type { JobSubmitResponse } from '../types/job';

export interface SubmissionState {
  isSubmitting: boolean;
  progress: SubmissionProgress | null;
  error: string | null;
  lastSubmittedJob: JobSubmitResponse | null;
}

export interface SubmitOptions {
  language?: string;
  forceLanguage?: boolean;
  numSpeakers?: number;
  minSpeakers?: number;
  maxSpeakers?: number;
}

export const useBackgroundJobSubmit = (onJobSubmitted?: () => void) => {
  const [state, setState] = useState<SubmissionState>({
    isSubmitting: false,
    progress: null,
    error: null,
    lastSubmittedJob: null,
  });

  const { addJob } = useJobStorage();

  /**
   * Submit a file for background processing
   */
  const submit = useCallback(async (
    file: File,
    options: SubmitOptions = {}
  ): Promise<JobSubmitResponse | null> => {
    setState({
      isSubmitting: true,
      progress: { stage: 'hashing', progress: 0, message: 'Starting...' },
      error: null,
      lastSubmittedJob: null,
    });

    try {
      const result = await submitBackgroundJob({
        file,
        language: options.language,
        forceLanguage: options.forceLanguage,
        numSpeakers: options.numSpeakers,
        minSpeakers: options.minSpeakers,
        maxSpeakers: options.maxSpeakers,
        onProgress: (progress) => {
          setState(prev => ({
            ...prev,
            progress,
          }));
        },
      });

      // Store job in localStorage
      addJob({
        job_id: result.job_id,
        access_token: result.access_token,
      });

      setState({
        isSubmitting: false,
        progress: { stage: 'complete', progress: 100, message: 'Job submitted!' },
        error: null,
        lastSubmittedJob: result,
      });

      // Trigger refetch of job list
      if (onJobSubmitted) {
        onJobSubmitted();
      }

      return result;
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Failed to submit job';
      console.error('Job submission failed:', error);

      setState({
        isSubmitting: false,
        progress: null,
        error: errorMessage,
        lastSubmittedJob: null,
      });

      return null;
    }
  }, [addJob, onJobSubmitted]);

  /**
   * Reset submission state
   */
  const reset = useCallback(() => {
    setState({
      isSubmitting: false,
      progress: null,
      error: null,
      lastSubmittedJob: null,
    });
  }, []);

  return {
    ...state,
    submit,
    reset,
  };
};
