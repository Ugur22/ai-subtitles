/**
 * APIKeysTab - Manage API keys for LLM providers
 */

import React from 'react';
import { useAPIKeys } from '../../hooks/useAPIKeys';
import { ProviderCard } from './ProviderCard';
import type { LLMProvider } from '../../services/keys';

const PROVIDERS = [
  { id: 'groq' as LLMProvider, name: 'Groq', placeholder: 'gsk_...' },
  { id: 'xai' as LLMProvider, name: 'xAI (Grok)', placeholder: 'xai-...' },
  { id: 'openai' as LLMProvider, name: 'OpenAI', placeholder: 'sk-...' },
  { id: 'anthropic' as LLMProvider, name: 'Anthropic', placeholder: 'sk-ant-...' },
];

export const APIKeysTab: React.FC = () => {
  const { keys, addKey, deleteKey, isLoading } = useAPIKeys();

  return (
    <div className="space-y-4 p-4">
      <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
        <div className="flex">
          <div className="flex-shrink-0">
            <svg
              className="h-5 w-5 text-blue-400"
              fill="currentColor"
              viewBox="0 0 20 20"
            >
              <path
                fillRule="evenodd"
                d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z"
                clipRule="evenodd"
              />
            </svg>
          </div>
          <div className="ml-3">
            <p className="text-sm text-blue-700">
              Add your API keys to enable chat features. Keys are encrypted and stored securely.
              Validation happens in the background.
            </p>
          </div>
        </div>
      </div>

      <div className="space-y-3">
        {PROVIDERS.map((provider) => {
          const savedKey = keys.find((k) => k.provider === provider.id);
          return (
            <ProviderCard
              key={provider.id}
              provider={provider}
              savedKey={savedKey}
              onSave={(key) => addKey(provider.id, key)}
              onDelete={() => deleteKey(provider.id)}
              isLoading={isLoading}
            />
          );
        })}
      </div>
    </div>
  );
};
