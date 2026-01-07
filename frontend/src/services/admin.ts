/**
 * Admin Service - API calls for admin operations
 */

import { API_BASE_URL } from '../config';

export interface AdminUser {
  id: string;
  email: string;
  display_name: string | null;
  created_at: string;
  last_login: string | null;
  upload_count: number;
  has_groq: boolean;
  has_xai: boolean;
  has_openai: boolean;
  has_anthropic: boolean;
}

export interface InviteCode {
  id: string;
  code: string;
  created_at: string;
  created_by: string | null;
  used_by: string | null;
  used_at: string | null;
}

export interface AdminStats {
  total_users: number;
  active_today: number;
  uploads_today: number;
  chat_messages_today: number;
}

/**
 * Get all users (admin only)
 */
export const getUsers = async (): Promise<AdminUser[]> => {
  const response = await fetch(`${API_BASE_URL}/api/admin/users`, {
    method: 'GET',
    credentials: 'include',
  });

  if (!response.ok) {
    throw new Error('Failed to fetch users');
  }

  return response.json();
};

/**
 * Create a new invite code (admin only)
 */
export const createInviteCode = async (): Promise<{ code: string }> => {
  const response = await fetch(`${API_BASE_URL}/api/admin/invite-codes`, {
    method: 'POST',
    credentials: 'include',
  });

  if (!response.ok) {
    throw new Error('Failed to create invite code');
  }

  return response.json();
};

/**
 * Get all invite codes (admin only)
 */
export const getInviteCodes = async (): Promise<InviteCode[]> => {
  const response = await fetch(`${API_BASE_URL}/api/admin/invite-codes`, {
    method: 'GET',
    credentials: 'include',
  });

  if (!response.ok) {
    throw new Error('Failed to fetch invite codes');
  }

  return response.json();
};

/**
 * Delete an invite code (admin only)
 */
export const deleteInviteCode = async (code: string): Promise<void> => {
  const response = await fetch(`${API_BASE_URL}/api/admin/invite-codes/${code}`, {
    method: 'DELETE',
    credentials: 'include',
  });

  if (!response.ok) {
    throw new Error('Failed to delete invite code');
  }
};

/**
 * Delete a user (admin only)
 */
export const deleteUser = async (userId: string): Promise<void> => {
  const response = await fetch(`${API_BASE_URL}/api/admin/users/${userId}`, {
    method: 'DELETE',
    credentials: 'include',
  });

  if (!response.ok) {
    throw new Error('Failed to delete user');
  }
};

/**
 * Invalidate all API keys for a user (admin only)
 */
export const invalidateUserKeys = async (userId: string): Promise<void> => {
  const response = await fetch(
    `${API_BASE_URL}/api/admin/users/${userId}/invalidate-keys`,
    {
      method: 'POST',
      credentials: 'include',
    }
  );

  if (!response.ok) {
    throw new Error('Failed to invalidate keys');
  }
};

/**
 * Get admin statistics (admin only)
 */
export const getAdminStats = async (): Promise<AdminStats> => {
  const response = await fetch(`${API_BASE_URL}/api/admin/stats`, {
    method: 'GET',
    credentials: 'include',
  });

  if (!response.ok) {
    throw new Error('Failed to fetch stats');
  }

  return response.json();
};

/**
 * Update user settings
 */
export const updateSettings = async (settings: {
  display_name?: string;
  default_llm_provider?: string;
}): Promise<{ success: boolean }> => {
  const response = await fetch(`${API_BASE_URL}/api/settings`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(settings),
  });

  if (!response.ok) {
    throw new Error('Failed to update settings');
  }

  return response.json();
};

/**
 * Delete current user's account
 */
export const deleteAccount = async (): Promise<void> => {
  const response = await fetch(`${API_BASE_URL}/api/account`, {
    method: 'DELETE',
    credentials: 'include',
  });

  if (!response.ok) {
    throw new Error('Failed to delete account');
  }
};
