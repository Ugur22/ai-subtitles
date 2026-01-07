/**
 * ChatProviderSelector - Dropdown to select LLM provider
 */

import React from 'react';
import { useAPIKeys } from '../../hooks/useAPIKeys';
import { useAuth } from '../../hooks/useAuth';
import type { LLMProvider } from '../../services/keys';

interface ChatProviderSelectorProps {
  value?: LLMProvider;
  onChange: (provider: LLMProvider) => void;
  disabled?: boolean;
}

const PROVIDER_NAMES: Record<LLMProvider, string> = {
  groq: 'Groq',
  xai: 'xAI (Grok)',
  openai: 'OpenAI',
  anthropic: 'Anthropic',
};

export const ChatProviderSelector: React.FC<ChatProviderSelectorProps> = ({
  value,
  onChange,
  disabled,
}) => {
  const { keys } = useAPIKeys();
  const { user } = useAuth();

  // Get valid providers (those with valid keys)
  const validProviders = keys
    .filter((k) => k.is_valid === true)
    .map((k) => k.provider);

  // Use provided value, or fall back to user's default, or first valid provider
  const currentProvider =
    value ||
    (user?.default_llm_provider as LLMProvider) ||
    validProviders[0] ||
    'groq';

  if (validProviders.length === 0) {
    return null; // Parent should show NoKeysWarning
  }

  return (
    <div className="flex items-center gap-2">
      <label htmlFor="provider" className="text-sm font-medium text-gray-700">
        Provider:
      </label>
      <select
        id="provider"
        value={currentProvider}
        onChange={(e) => onChange(e.target.value as LLMProvider)}
        disabled={disabled || validProviders.length === 1}
        className="input-base text-sm py-1 px-2"
      >
        {validProviders.map((provider) => (
          <option key={provider} value={provider}>
            {PROVIDER_NAMES[provider]}
          </option>
        ))}
      </select>
    </div>
  );
};
