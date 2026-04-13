/**
 * ProviderCard - Individual provider API key card
 */

import React, { useState } from 'react';
import type { LLMProvider, APIKey } from '../../services/keys';
import { KeyStatusIndicator } from './KeyStatusIndicator';

interface ProviderCardProps {
  provider: {
    id: LLMProvider;
    name: string;
    placeholder: string;
  };
  savedKey?: APIKey;
  onSave: (key: string) => Promise<void>;
  onDelete: () => Promise<void>;
  isLoading?: boolean;
}

export const ProviderCard: React.FC<ProviderCardProps> = ({
  provider,
  savedKey,
  onSave,
  onDelete,
  isLoading,
}) => {
  const [inputValue, setInputValue] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);

  const handleSave = async () => {
    if (!inputValue.trim()) return;

    setIsSaving(true);
    try {
      await onSave(inputValue);
      setInputValue('');
    } catch (error) {
      // Error handled by parent
    } finally {
      setIsSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!confirm(`Remove ${provider.name} API key?`)) return;

    setIsDeleting(true);
    try {
      await onDelete();
    } catch (error) {
      // Error handled by parent
    } finally {
      setIsDeleting(false);
    }
  };

  return (
    <div
      className="rounded-md p-3"
      style={{ border: '1px solid var(--border-subtle)', backgroundColor: 'var(--bg-surface)' }}
    >
      <div className="flex items-center justify-between mb-2.5">
        <h3 className="text-sm font-medium" style={{ color: 'var(--text-primary)' }}>{provider.name}</h3>
        {savedKey && <KeyStatusIndicator status={savedKey.is_valid} />}
      </div>

      {savedKey ? (
        <div>
          <div className="flex items-center justify-between mb-2">
            <code
              className="text-xs px-2.5 py-1 rounded font-mono"
              style={{
                backgroundColor: 'var(--bg-overlay)',
                color: 'var(--text-secondary)',
                border: '1px solid var(--border-subtle)',
              }}
            >
              ••••••••{savedKey.key_suffix}
            </code>
            <button
              onClick={handleDelete}
              disabled={isDeleting || isLoading}
              className="text-xs font-medium transition-colors duration-150 disabled:opacity-40"
              style={{ color: 'var(--c-error)' }}
            >
              {isDeleting ? 'Removing...' : 'Remove'}
            </button>
          </div>

          {savedKey.validation_error && (
            <p className="text-xs mt-2" style={{ color: 'var(--c-error)' }}>{savedKey.validation_error}</p>
          )}

          {savedKey.validated_at && (
            <p className="text-xs mt-1" style={{ color: 'var(--text-tertiary)' }}>
              Last validated: {new Date(savedKey.validated_at).toLocaleString()}
            </p>
          )}
        </div>
      ) : (
        <div className="flex gap-2">
          <input
            type="password"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            placeholder={provider.placeholder}
            className="input-base flex-1"
            disabled={isSaving || isLoading}
          />
          <button
            onClick={handleSave}
            disabled={!inputValue.trim() || isSaving || isLoading}
            className="btn-primary"
          >
            {isSaving ? 'Saving...' : 'Save'}
          </button>
        </div>
      )}
    </div>
  );
};
