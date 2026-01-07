/**
 * API Keys Service - Manage user API keys for LLM providers
 */

import { API_BASE_URL } from '../config';

export type LLMProvider = 'groq' | 'xai' | 'openai' | 'anthropic';

export interface APIKey {
  id: string;
  provider: LLMProvider;
  key_suffix: string;
  is_valid: boolean | null; // null = pending validation
  validation_error: string | null;
  validated_at: string | null;
  created_at: string;
}

export interface AddKeyResponse {
  id: string;
  provider: LLMProvider;
  key_suffix: string;
  is_valid: null; // Always null on creation (async validation)
}

export interface TestKeyResponse {
  valid: boolean;
  error?: string;
}

/**
 * Get all API keys for the current user
 */
export const getAPIKeys = async (): Promise<APIKey[]> => {
  const response = await fetch(`${API_BASE_URL}/api/keys`, {
    method: 'GET',
    credentials: 'include',
  });

  if (!response.ok) {
    throw new Error('Failed to fetch API keys');
  }

  return response.json();
};

/**
 * Add a new API key
 * Triggers async validation in the background
 */
export const addAPIKey = async (
  provider: LLMProvider,
  apiKey: string
): Promise<AddKeyResponse> => {
  const response = await fetch(`${API_BASE_URL}/api/keys`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ provider, api_key: apiKey }),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to add API key');
  }

  return response.json();
};

/**
 * Delete an API key
 */
export const deleteAPIKey = async (provider: LLMProvider): Promise<void> => {
  const response = await fetch(`${API_BASE_URL}/api/keys/${provider}`, {
    method: 'DELETE',
    credentials: 'include',
  });

  if (!response.ok) {
    throw new Error('Failed to delete API key');
  }
};

/**
 * Test an API key immediately (synchronous validation)
 */
export const testAPIKey = async (provider: LLMProvider): Promise<TestKeyResponse> => {
  const response = await fetch(`${API_BASE_URL}/api/keys/${provider}/test`, {
    method: 'POST',
    credentials: 'include',
  });

  if (!response.ok) {
    throw new Error('Failed to test API key');
  }

  return response.json();
};
