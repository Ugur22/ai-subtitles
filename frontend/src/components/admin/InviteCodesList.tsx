/**
 * InviteCodesList - Invite code management
 */

import React, { useState } from 'react';
import toast from 'react-hot-toast';
import type { InviteCode } from '../../services/admin';

interface InviteCodesListProps {
  inviteCodes: InviteCode[];
  isLoading: boolean;
  onCreate: () => Promise<{ code: string }>;
  onDelete: (code: string) => Promise<void>;
}

export const InviteCodesList: React.FC<InviteCodesListProps> = ({
  inviteCodes,
  isLoading,
  onCreate,
  onDelete,
}) => {
  const [isCreating, setIsCreating] = useState(false);

  const handleCreate = async () => {
    setIsCreating(true);
    try {
      await onCreate();
    } finally {
      setIsCreating(false);
    }
  };

  const handleDelete = async (code: string) => {
    if (!confirm('Delete this invite code?')) return;
    await onDelete(code);
  };

  const handleCopy = (code: string) => {
    navigator.clipboard.writeText(code);
    toast.success('Code copied to clipboard');
  };

  if (isLoading) {
    return (
      <div className="bg-white shadow rounded-lg p-6">
        <div className="animate-pulse space-y-4">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-16 bg-gray-200 rounded"></div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white shadow rounded-lg overflow-hidden">
      <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
        <div>
          <h3 className="text-lg font-medium text-gray-900">Invite Codes</h3>
          <p className="text-sm text-gray-500 mt-1">
            Total: {inviteCodes.length} ({inviteCodes.filter((c) => !c.used_at).length} unused)
          </p>
        </div>
        <button
          onClick={handleCreate}
          disabled={isCreating}
          className="btn-primary"
        >
          {isCreating ? 'Creating...' : 'Create Code'}
        </button>
      </div>

      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Code
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Status
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Created
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Used
              </th>
              <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                Actions
              </th>
            </tr>
          </thead>
          <tbody className="bg-white divide-y divide-gray-200">
            {inviteCodes.map((code) => (
              <tr key={code.id} className="hover:bg-gray-50">
                <td className="px-6 py-4 whitespace-nowrap">
                  <code className="text-sm font-mono text-gray-900">{code.code}</code>
                </td>
                <td className="px-6 py-4 whitespace-nowrap">
                  {code.used_at ? (
                    <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-800">
                      Used
                    </span>
                  ) : (
                    <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800">
                      Available
                    </span>
                  )}
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                  {new Date(code.created_at).toLocaleDateString()}
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                  {code.used_at ? new Date(code.used_at).toLocaleDateString() : '-'}
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                  <button
                    onClick={() => handleCopy(code.code)}
                    className="text-indigo-600 hover:text-indigo-900 mr-3"
                  >
                    Copy
                  </button>
                  {!code.used_at && (
                    <button
                      onClick={() => handleDelete(code.code)}
                      className="text-red-600 hover:text-red-900"
                    >
                      Delete
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {inviteCodes.length === 0 && (
        <div className="text-center py-12">
          <p className="text-gray-500">No invite codes yet</p>
        </div>
      )}
    </div>
  );
};
