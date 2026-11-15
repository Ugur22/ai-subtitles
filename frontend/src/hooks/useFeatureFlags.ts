import { useQuery } from '@tanstack/react-query';
import { getFeatureFlags, type FeatureFlags } from '../services/api';

// Fail closed: hidden while loading or on error, so unfinished tabs never flash.
const ALL_OFF: FeatureFlags = { chapters: false, summary: false };

export const useFeatureFlags = (): FeatureFlags => {
  const { data } = useQuery({
    queryKey: ['featureFlags'],
    queryFn: getFeatureFlags,
    // Flags change rarely; no polling, so no extra Cloud Run requests via the Netlify proxy.
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
    retry: 1,
  });
  return data ?? ALL_OFF;
};
