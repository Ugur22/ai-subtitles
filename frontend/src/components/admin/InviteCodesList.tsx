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
      <div className="rounded-md p-5" style={{ backgroundColor: 'var(--bg-surface)', border: '1px solid var(--border-subtle)' }}>
        <div className="animate-pulse space-y-3">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-12 rounded" style={{ backgroundColor: 'var(--bg-overlay)' }}></div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-md overflow-hidden" style={{ backgroundColor: 'var(--bg-surface)', border: '1px solid var(--border-subtle)' }}>
      <div className="px-5 py-4 flex items-center justify-between" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
        <div>
          <h3 className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>Invite Codes</h3>
          <p className="text-xs mt-0.5" style={{ color: 'var(--text-secondary)' }}>
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
        <table className="min-w-full" style={{ borderCollapse: 'collapse' }}>
          <thead style={{ backgroundColor: 'var(--bg-subtle)' }}>
            <tr>
              {['Code', 'Status', 'Created', 'Used', ''].map((col, i) => (
                <th
                  key={i}
                  className={`px-5 py-2.5 text-xs font-medium uppercase tracking-wider ${i === 4 ? 'text-right' : 'text-left'}`}
                  style={{ color: 'var(--text-tertiary)', borderBottom: '1px solid var(--border-subtle)' }}
                >
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {inviteCodes.map((code, idx) => (
              <tr
                key={code.id}
                style={{ borderTop: idx > 0 ? '1px solid var(--border-subtle)' : undefined }}
                onMouseEnter={e => (e.currentTarget.style.backgroundColor = 'var(--bg-overlay)')}
                onMouseLeave={e => (e.currentTarget.style.backgroundColor = 'transparent')}
              >
                <td className="px-5 py-3 whitespace-nowrap">
                  <code className="text-xs font-mono" style={{ color: 'var(--text-primary)' }}>{code.code}</code>
                </td>
                <td className="px-5 py-3 whitespace-nowrap">
                  {code.used_at ? (
                    <span className="badge badge-default">Used</span>
                  ) : (
                    <span className="badge badge-success">Available</span>
                  )}
                </td>
                <td className="px-5 py-3 whitespace-nowrap text-xs" style={{ color: 'var(--text-secondary)' }}>
                  {new Date(code.created_at).toLocaleDateString()}
                </td>
                <td className="px-5 py-3 whitespace-nowrap text-xs" style={{ color: 'var(--text-secondary)' }}>
                  {code.used_at ? new Date(code.used_at).toLocaleDateString() : '—'}
                </td>
                <td className="px-5 py-3 whitespace-nowrap text-right text-xs font-medium">
                  <button
                    onClick={() => handleCopy(code.code)}
                    className="mr-3 transition-colors duration-150"
                    style={{ color: 'var(--accent)' }}
                  >
                    Copy
                  </button>
                  {!code.used_at && (
                    <button
                      onClick={() => handleDelete(code.code)}
                      className="transition-colors duration-150"
                      style={{ color: 'var(--c-error)' }}
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
        <div className="text-center py-10">
          <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>No invite codes yet</p>
        </div>
      )}
    </div>
  );
};
