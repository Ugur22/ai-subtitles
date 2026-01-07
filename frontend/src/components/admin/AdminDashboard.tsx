/**
 * AdminDashboard - Main admin view
 */

import React from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from '../../hooks/useAuth';
import { useAdmin } from '../../hooks/useAdmin';
import { StatsCards } from './StatsCards';
import { UsersList } from './UsersList';
import { InviteCodesList } from './InviteCodesList';

export const AdminDashboard: React.FC = () => {
  const { user } = useAuth();
  const {
    users,
    inviteCodes,
    stats,
    isLoading,
    createInviteCode,
    deleteInviteCode,
    deleteUser,
    invalidateUserKeys,
  } = useAdmin();

  // Redirect if not admin
  if (user && !user.is_admin) {
    return <Navigate to="/" replace />;
  }

  return (
    <div className="min-h-screen bg-gray-100">
      {/* Header */}
      <div className="bg-white shadow">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-3xl font-bold text-gray-900">Admin Dashboard</h1>
              <p className="text-sm text-gray-500 mt-1">Manage users, invite codes, and view statistics</p>
            </div>
            <a
              href="/"
              className="btn-secondary"
            >
              Back to App
            </a>
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="space-y-8">
          {/* Stats */}
          <StatsCards stats={stats} isLoading={isLoading} />

          {/* Invite Codes */}
          <InviteCodesList
            inviteCodes={inviteCodes}
            isLoading={isLoading}
            onCreate={createInviteCode}
            onDelete={deleteInviteCode}
          />

          {/* Users */}
          <UsersList
            users={users}
            isLoading={isLoading}
            onDeleteUser={deleteUser}
            onInvalidateKeys={invalidateUserKeys}
          />
        </div>
      </div>
    </div>
  );
};
