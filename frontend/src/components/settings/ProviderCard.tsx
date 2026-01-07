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
    <div className="border border-gray-200 rounded-lg p-4 bg-white">
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-medium text-gray-900">{provider.name}</h3>
        {savedKey && <KeyStatusIndicator status={savedKey.is_valid} />}
      </div>

      {savedKey ? (
        <div>
          <div className="flex items-center justify-between mb-2">
            <code className="text-sm bg-gray-100 px-3 py-1.5 rounded font-mono text-gray-700">
              ••••••••{savedKey.key_suffix}
            </code>
            <button
              onClick={handleDelete}
              disabled={isDeleting || isLoading}
              className="text-sm text-red-600 hover:text-red-700 font-medium disabled:opacity-50"
            >
              {isDeleting ? 'Removing...' : 'Remove'}
            </button>
          </div>

          {savedKey.validation_error && (
            <p className="text-xs text-red-600 mt-2">{savedKey.validation_error}</p>
          )}

          {savedKey.validated_at && (
            <p className="text-xs text-gray-500 mt-1">
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
            className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
            disabled={isSaving || isLoading}
          />
          <button
            onClick={handleSave}
            disabled={!inputValue.trim() || isSaving || isLoading}
            className="btn-primary px-4 py-2 text-sm"
          >
            {isSaving ? 'Saving...' : 'Save'}
          </button>
        </div>
      )}
    </div>
  );
};
