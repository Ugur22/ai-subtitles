/**
 * useAPIKeys - Manage user API keys for LLM providers
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import toast from 'react-hot-toast';
import type { LLMProvider, APIKey } from '../services/keys';
import * as keysService from '../services/keys';

export const useAPIKeys = () => {
  const queryClient = useQueryClient();

  // Fetch all API keys
  const {
    data: keys = [],
    isLoading,
    error,
  } = useQuery<APIKey[]>({
    queryKey: ['apiKeys'],
    queryFn: keysService.getAPIKeys,
    retry: 1,
  });

  // Add API key mutation
  const addKeyMutation = useMutation({
    mutationFn: ({ provider, apiKey }: { provider: LLMProvider; apiKey: string }) =>
      keysService.addAPIKey(provider, apiKey),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['apiKeys'] });
      toast.success('API key saved. Validating in background...');
    },
    onError: (error: Error) => {
      toast.error(error.message || 'Failed to save API key');
    },
  });

  // Delete API key mutation
  const deleteKeyMutation = useMutation({
    mutationFn: (provider: LLMProvider) => keysService.deleteAPIKey(provider),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['apiKeys'] });
      toast.success('API key removed');
    },
    onError: (error: Error) => {
      toast.error(error.message || 'Failed to remove API key');
    },
  });

  // Test API key mutation
  const testKeyMutation = useMutation({
    mutationFn: (provider: LLMProvider) => keysService.testAPIKey(provider),
    onSuccess: (data) => {
      if (data.valid) {
        toast.success('API key is valid!');
      } else {
        toast.error(data.error || 'API key is invalid');
      }
      queryClient.invalidateQueries({ queryKey: ['apiKeys'] });
    },
    onError: (error: Error) => {
      toast.error(error.message || 'Failed to test API key');
    },
  });

  return {
    keys,
    isLoading,
    error,
    addKey: async (provider: LLMProvider, apiKey: string) => {
      await addKeyMutation.mutateAsync({ provider, apiKey });
    },
    deleteKey: deleteKeyMutation.mutateAsync,
    testKey: testKeyMutation.mutateAsync,
    isAddingKey: addKeyMutation.isPending,
    isDeletingKey: deleteKeyMutation.isPending,
    isTestingKey: testKeyMutation.isPending,
  };
};
