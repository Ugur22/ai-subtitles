/**
 * useSupabaseRealtime - Custom hook for real-time job status updates
 * Subscribes to Supabase real-time changes for a specific job
 */

import { useEffect, useState } from 'react';
import { supabase } from '../lib/supabase';
import { Job } from '../types/job';
import { getJob } from '../services/api';

interface UseJobRealtimeOptions {
  jobId: string | null;
  accessToken: string | null;
  enabled?: boolean;
}

export const useJobRealtime = ({ jobId, accessToken, enabled = true }: UseJobRealtimeOptions) => {
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    if (!jobId || !accessToken || !enabled) {
      setIsLoading(false);
      return;
    }

    let subscription: ReturnType<typeof supabase.channel> | null = null;

    // Initial fetch from API
    const fetchInitialJob = async () => {
      try {
        setIsLoading(true);
        setError(null);

        const data = await getJob(jobId, accessToken);
        setJob(data);
      } catch (err) {
        // Handle 404 - job no longer exists (expired or deleted)
        if (err instanceof Error) {
          if (err.message.includes('404') || err.message.toLowerCase().includes('not found')) {
            setError('expired');
            return;
          }
          setError(err.message);
        } else {
          setError('Failed to load job status');
        }
      } finally {
        setIsLoading(false);
      }
    };

    fetchInitialJob();

    // Subscribe to real-time updates via Supabase
    subscription = supabase
      .channel(`job:${jobId}`)
      .on(
        'postgres_changes',
        {
          event: 'UPDATE',
          schema: 'public',
          table: 'jobs',
          filter: `job_id=eq.${jobId}`,
        },
        (payload: { new: Record<string, unknown> }) => {
          // Update job state with real-time data
          setJob(payload.new as unknown as Job);
          setError(null);
        }
      )
      .subscribe();

    // Cleanup subscription on unmount
    return () => {
      if (subscription) {
        subscription.unsubscribe();
      }
    };
  }, [jobId, accessToken, enabled]);

  return {
    job,
    error,
    isLoading,
  };
};
