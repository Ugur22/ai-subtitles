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
  { value: 'deepseek', label: 'DeepSeek' },
];

export const ProfileTab: React.FC = () => {
  const { user } = useAuth();
  const { updateUserSettings, isUpdating } = useSettings();
  const { keys } = useAPIKeys();
  const [displayName, setDisplayName] = useState('');
  const [defaultProvider, setDefaultProvider] = useState<string>('groq');
  const [visualSearchTerms, setVisualSearchTerms] = useState('');
  const [visualSearchPhrases, setVisualSearchPhrases] = useState('');
  const [hasChanges, setHasChanges] = useState(false);

  // Initialize form with user data
  useEffect(() => {
    if (user) {
      setDisplayName(user.display_name || '');
      setDefaultProvider(user.default_llm_provider || 'groq');
      setVisualSearchTerms(user.visual_search_terms || '');
      setVisualSearchPhrases(user.visual_search_phrases || '');
    }
  }, [user]);

  // Check for changes
  useEffect(() => {
    if (!user) return;
    const changed =
      displayName !== (user.display_name || '') ||
      defaultProvider !== (user.default_llm_provider || 'groq') ||
      visualSearchTerms !== (user.visual_search_terms || '') ||
      visualSearchPhrases !== (user.visual_search_phrases || '');
    setHasChanges(changed);
  }, [displayName, defaultProvider, visualSearchTerms, visualSearchPhrases, user]);

  const handleSave = async () => {
    const updates: {
      display_name?: string;
      default_llm_provider?: string;
      visual_search_terms?: string;
      visual_search_phrases?: string;
    } = {};

    if (displayName !== (user?.display_name || '')) {
      updates.display_name = displayName;
    }

    if (defaultProvider !== (user?.default_llm_provider || 'groq')) {
      updates.default_llm_provider = defaultProvider;
    }

    if (visualSearchTerms !== (user?.visual_search_terms || '')) {
      updates.visual_search_terms = visualSearchTerms;
    }

    if (visualSearchPhrases !== (user?.visual_search_phrases || '')) {
      updates.visual_search_phrases = visualSearchPhrases;
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
        <h3 className="text-sm font-semibold mb-4" style={{ color: 'var(--text-primary)' }}>Profile Settings</h3>

        <div className="space-y-4">
          <div>
            <label htmlFor="email" className="block text-xs font-medium mb-1" style={{ color: 'var(--text-secondary)' }}>
              Email
            </label>
            <input
              id="email"
              type="email"
              value={user?.email || ''}
              disabled
              className="input-base w-full"
            />
            <p className="text-xs mt-1" style={{ color: 'var(--text-tertiary)' }}>Email cannot be changed</p>
          </div>

          <div>
            <label htmlFor="displayName" className="block text-xs font-medium mb-1" style={{ color: 'var(--text-secondary)' }}>
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
              className="block text-xs font-medium mb-1"
              style={{ color: 'var(--text-secondary)' }}
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
            <p className="text-xs mt-1" style={{ color: 'var(--text-tertiary)' }}>
              The default provider to use for chat features
            </p>
          </div>

          <div className="rounded-lg border p-3" style={{ borderColor: 'var(--border)', background: 'var(--bg-secondary)' }}>
            <h4 className="text-xs font-semibold mb-2" style={{ color: 'var(--text-primary)' }}>
              Visual Search Rewrites
            </h4>
            <p className="text-xs mb-3" style={{ color: 'var(--text-tertiary)' }}>
              Add private trigger terms and image-search phrases for your own retrieval needs. These are stored in your profile and used only when your query matches a trigger.
            </p>

            <div className="space-y-3">
              <div>
                <label
                  htmlFor="visualSearchTerms"
                  className="block text-xs font-medium mb-1"
                  style={{ color: 'var(--text-secondary)' }}
                >
                  Trigger terms
                </label>
                <textarea
                  id="visualSearchTerms"
                  value={visualSearchTerms}
                  onChange={(e) => setVisualSearchTerms(e.target.value)}
                  placeholder="One term per line, or comma-separated"
                  className="input-base w-full min-h-[88px] resize-y"
                  disabled={isUpdating}
                />
              </div>

              <div>
                <label
                  htmlFor="visualSearchPhrases"
                  className="block text-xs font-medium mb-1"
                  style={{ color: 'var(--text-secondary)' }}
                >
                  Search phrases
                </label>
                <textarea
                  id="visualSearchPhrases"
                  value={visualSearchPhrases}
                  onChange={(e) => setVisualSearchPhrases(e.target.value)}
                  placeholder="One visual phrase per line"
                  className="input-base w-full min-h-[112px] resize-y"
                  disabled={isUpdating}
                />
              </div>
            </div>
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
