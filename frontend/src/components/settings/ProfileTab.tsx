/**
 * ProfileTab - User profile settings (display name, default provider)
 */

import React, { useState, useEffect } from 'react';
import { useAuth } from '../../hooks/useAuth';
import { useSettings } from '../../hooks/useSettings';
import { useAPIKeys } from '../../hooks/useAPIKeys';
import type { LLMProvider } from '../../services/keys';

const PROVIDER_OPTIONS = [
  { value: 'groq', label: 'Groq' },
  { value: 'xai', label: 'xAI (Grok)' },
  { value: 'openai', label: 'OpenAI' },
  { value: 'anthropic', label: 'Anthropic' },
];

export const ProfileTab: React.FC = () => {
  const { user } = useAuth();
  const { updateUserSettings, isUpdating } = useSettings();
  const { keys } = useAPIKeys();
  const [displayName, setDisplayName] = useState('');
  const [defaultProvider, setDefaultProvider] = useState<string>('groq');
  const [hasChanges, setHasChanges] = useState(false);

  // Initialize form with user data
  useEffect(() => {
    if (user) {
      setDisplayName(user.display_name || '');
      setDefaultProvider(user.default_llm_provider || 'groq');
    }
  }, [user]);

  // Check for changes
  useEffect(() => {
    if (!user) return;
    const changed =
      displayName !== (user.display_name || '') ||
      defaultProvider !== (user.default_llm_provider || 'groq');
    setHasChanges(changed);
  }, [displayName, defaultProvider, user]);

  const handleSave = async () => {
    const updates: { display_name?: string; default_llm_provider?: string } = {};

    if (displayName !== (user?.display_name || '')) {
      updates.display_name = displayName;
    }

    if (defaultProvider !== (user?.default_llm_provider || 'groq')) {
      updates.default_llm_provider = defaultProvider;
    }

    await updateUserSettings(updates);
    setHasChanges(false);
  };

  // Get valid providers (those with valid keys)
  const validProviders = keys
    .filter((k) => k.is_valid === true)
    .map((k) => k.provider);

  return (
    <div className="space-y-6 p-4">
      <div>
        <h3 className="text-lg font-medium text-gray-900 mb-4">Profile Settings</h3>

        <div className="space-y-4">
          <div>
            <label htmlFor="email" className="block text-sm font-medium text-gray-700 mb-1">
              Email
            </label>
            <input
              id="email"
              type="email"
              value={user?.email || ''}
              disabled
              className="input-base w-full bg-gray-50 text-gray-500 cursor-not-allowed"
            />
            <p className="text-xs text-gray-500 mt-1">Email cannot be changed</p>
          </div>

          <div>
            <label htmlFor="displayName" className="block text-sm font-medium text-gray-700 mb-1">
              Display Name
            </label>
            <input
              id="displayName"
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="Your name"
              className="input-base w-full"
              disabled={isUpdating}
            />
          </div>

          <div>
            <label
              htmlFor="defaultProvider"
              className="block text-sm font-medium text-gray-700 mb-1"
            >
              Default LLM Provider
            </label>
            <select
              id="defaultProvider"
              value={defaultProvider}
              onChange={(e) => setDefaultProvider(e.target.value)}
              className="input-base w-full"
              disabled={isUpdating}
            >
              {PROVIDER_OPTIONS.map((option) => {
                const isValid = validProviders.includes(option.value as LLMProvider);
                return (
                  <option key={option.value} value={option.value} disabled={!isValid}>
                    {option.label} {!isValid && '(No valid key)'}
                  </option>
                );
              })}
            </select>
            <p className="text-xs text-gray-500 mt-1">
              The default provider to use for chat features
            </p>
          </div>

          {hasChanges && (
            <button
              onClick={handleSave}
              disabled={isUpdating}
              className="btn-primary w-full"
            >
              {isUpdating ? 'Saving...' : 'Save Changes'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
};
