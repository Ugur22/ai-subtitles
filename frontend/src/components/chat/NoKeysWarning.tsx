/**
 * NoKeysWarning - Warning message when no valid API keys are configured
 */

import React from 'react';
import { useSettings } from '../../hooks/useSettings';

export const NoKeysWarning: React.FC = () => {
  const { openSettings } = useSettings();

  return (
    <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
      <div className="flex">
        <div className="flex-shrink-0">
          <svg
            className="h-5 w-5 text-yellow-400"
            fill="currentColor"
            viewBox="0 0 20 20"
          >
            <path
              fillRule="evenodd"
              d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z"
              clipRule="evenodd"
            />
          </svg>
        </div>
        <div className="ml-3 flex-1">
          <h3 className="text-sm font-medium text-yellow-800">Chat is disabled</h3>
          <div className="mt-2 text-sm text-yellow-700">
            <p>
              You need to add at least one valid API key to enable chat features.
            </p>
          </div>
          <div className="mt-4">
            <button
              onClick={() => openSettings('api-keys')}
              className="inline-flex items-center px-3 py-2 border border-transparent text-sm leading-4 font-medium rounded-md text-yellow-700 bg-yellow-100 hover:bg-yellow-200 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-yellow-500"
            >
              Configure API Keys
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
