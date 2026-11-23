/**
 * useAPIKeys - Manage user API keys for LLM providers
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import toast from 'react-hot-toast';
import type { LLMProvider, APIKey } from '../services/keys';
import * as keysService from '../services/keys';
import { queryKeys } from '../lib/queryKeys';

export const useAPIKeys = () => {
  const queryClient = useQueryClient();

  const invalidateKeyDependents = () => {
    queryClient.invalidateQueries({ queryKey: queryKeys.apiKeys });
    queryClient.invalidateQueries({ queryKey: queryKeys.llmProviders });
    queryClient.invalidateQueries({ queryKey: queryKeys.llmModelsAll });
  };

  const {
    data: keys = [],
    isLoading,
    error,
  } = useQuery<APIKey[]>({
    queryKey: queryKeys.apiKeys,
    queryFn: keysService.getAPIKeys,
    retry: 1,
  });

  const addKeyMutation = useMutation({
    mutationFn: ({ provider, apiKey }: { provider: LLMProvider; apiKey: string }) =>
      keysService.addAPIKey(provider, apiKey),
    onSuccess: () => {
      invalidateKeyDependents();
      toast.success('API key verified and saved');
    },
  });

  const deleteKeyMutation = useMutation({
    mutationFn: (provider: LLMProvider) => keysService.deleteAPIKey(provider),
    onSuccess: () => {
      invalidateKeyDependents();
      toast.success('API key removed');
    },
    onError: (error: Error) => {
      toast.error(error.message || 'Failed to remove API key');
    },
  });

  const testKeyMutation = useMutation({
    mutationFn: (provider: LLMProvider) => keysService.testAPIKey(provider),
    onSuccess: (data) => {
      if (data.valid) {
        toast.success('API key is valid!');
      } else {
        toast.error(data.error || 'API key is invalid');
      }
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
