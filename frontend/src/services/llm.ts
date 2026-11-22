import { api } from './api';

export type ReasoningEffort = 'low' | 'medium' | 'high' | 'xhigh';

export interface ChatProviderStatus {
  name: string;
  available: boolean;
  model: string;
}

export interface ProviderModels {
  models: string[];
  default: string | null;
  error?: string | null;
  reasoning_efforts?: Record<string, ReasoningEffort[]>;
}

export const getProviders = async (): Promise<ChatProviderStatus[]> => {
  const response = await api.get<{ providers: ChatProviderStatus[] }>('/api/llm/providers');
  return response.data.providers;
};

export const getProviderModels = async (provider: string): Promise<ProviderModels> => {
  const response = await api.get<ProviderModels>(`/api/llm/providers/${provider}/models`);
  return response.data;
};
