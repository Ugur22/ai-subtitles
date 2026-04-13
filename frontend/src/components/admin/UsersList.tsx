/**
 * UsersList - User management table
 */

import React from 'react';
import type { AdminUser } from '../../services/admin';

interface UsersListProps {
  users: AdminUser[];
  isLoading: boolean;
  onDeleteUser: (userId: string) => Promise<void>;
  onInvalidateKeys: (userId: string) => Promise<void>;
}

export const UsersList: React.FC<UsersListProps> = ({
  users,
  isLoading,
  onDeleteUser,
  onInvalidateKeys,
}) => {
  const handleDelete = async (user: AdminUser) => {
    if (!confirm(`Delete user ${user.email}? This action cannot be undone.`)) return;
    await onDeleteUser(user.id);
  };

  const handleInvalidateKeys = async (user: AdminUser) => {
    if (!confirm(`Invalidate all API keys for ${user.email}?`)) return;
    await onInvalidateKeys(user.id);
  };

  if (isLoading) {
    return (
      <div className="rounded-md p-6" style={{ backgroundColor: 'var(--bg-surface)', border: '1px solid var(--border-subtle)' }}>
        <div className="animate-pulse space-y-3">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="h-12 rounded" style={{ backgroundColor: 'var(--bg-overlay)' }}></div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-md overflow-hidden" style={{ backgroundColor: 'var(--bg-surface)', border: '1px solid var(--border-subtle)' }}>
      <div className="px-5 py-4" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
        <h3 className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>Users</h3>
        <p className="text-xs mt-0.5" style={{ color: 'var(--text-secondary)' }}>Total: {users.length}</p>
      </div>

      <div className="overflow-x-auto">
        <table className="min-w-full" style={{ borderCollapse: 'collapse' }}>
          <thead style={{ backgroundColor: 'var(--bg-subtle)' }}>
            <tr>
              {['User', 'API Keys', 'Uploads', 'Joined', ''].map((col, i) => (
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
            {users.map((user, idx) => (
              <tr
                key={user.id}
                style={{
                  borderTop: idx > 0 ? '1px solid var(--border-subtle)' : undefined,
                }}
                onMouseEnter={e => (e.currentTarget.style.backgroundColor = 'var(--bg-overlay)')}
                onMouseLeave={e => (e.currentTarget.style.backgroundColor = 'transparent')}
              >
                <td className="px-5 py-3 whitespace-nowrap">
                  <div className="text-sm font-medium" style={{ color: 'var(--text-primary)' }}>
                    {user.display_name || 'No name'}
                  </div>
                  <div className="text-xs" style={{ color: 'var(--text-secondary)' }}>{user.email}</div>
                </td>
                <td className="px-5 py-3 whitespace-nowrap">
                  <div className="flex gap-1 flex-wrap">
                    {user.has_groq && <span className="badge badge-accent">Groq</span>}
                    {user.has_xai && <span className="badge badge-default">xAI</span>}
                    {user.has_openai && <span className="badge badge-default">OpenAI</span>}
                    {user.has_anthropic && <span className="badge badge-default">Anthropic</span>}
                  </div>
                </td>
                <td className="px-5 py-3 whitespace-nowrap text-sm" style={{ color: 'var(--text-secondary)' }}>
                  {user.upload_count}
                </td>
                <td className="px-5 py-3 whitespace-nowrap text-sm" style={{ color: 'var(--text-secondary)' }}>
                  {new Date(user.created_at).toLocaleDateString()}
                </td>
                <td className="px-5 py-3 whitespace-nowrap text-right text-sm font-medium">
                  <button
                    onClick={() => handleInvalidateKeys(user)}
                    className="text-xs mr-3 transition-colors duration-150"
                    style={{ color: 'var(--c-warning)' }}
                  >
                    Invalidate Keys
                  </button>
                  <button
                    onClick={() => handleDelete(user)}
                    className="text-xs transition-colors duration-150"
                    style={{ color: 'var(--c-error)' }}
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {users.length === 0 && (
        <div className="text-center py-10">
          <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>No users found</p>
        </div>
      )}
    </div>
  );
};
