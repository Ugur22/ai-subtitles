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
    // Note: Database column is 'id', but frontend uses 'job_id' for the same value
    // We don't trust the raw payload because it contains stale GCS signed URLs
    // (7-day max IAM expiry). Re-fetch via the API so the backend can refresh
    // screenshot URLs before they reach the UI.
    subscription = supabase
      .channel(`job:${jobId}`)
      .on(
        'postgres_changes',
        {
          event: 'UPDATE',
          schema: 'public',
          table: 'jobs',
          filter: `id=eq.${jobId}`,
        },
        async (payload: { new: Record<string, unknown> }) => {
          const incomingStatus = (payload.new as { status?: string } | undefined)?.status;
          // For terminal/completion transitions, fetch through the API so the
          // response has freshly-signed screenshot URLs.
          if (incomingStatus === 'completed' || incomingStatus === 'failed') {
            try {
              const data = await getJob(jobId, accessToken);
              setJob(data);
              setError(null);
              return;
            } catch (err) {
              // Fall through to using the raw payload as a fallback so the UI
              // still updates if the API call fails.
              console.warn('Realtime refetch failed, using raw payload:', err);
            }
          }
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
