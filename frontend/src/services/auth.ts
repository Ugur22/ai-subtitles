/**
 * Auth Service - API calls for authentication
 * Uses HttpOnly cookies for session management
 */

import { API_BASE_URL } from '../config';

export interface User {
  id: string;
  email: string;
  display_name: string | null;
  default_llm_provider: string;
  is_admin: boolean;
  email_verified: boolean;
}

export interface LoginResponse {
  success: boolean;
  user: User;
}

export interface RegisterResponse {
  user_id: string;
  message: string;
}

export interface VerifyEmailResponse {
  success: boolean;
  user: User;
}

/**
 * Register a new user with email, password, and invite code
 */
export const register = async (
  email: string,
  password: string,
  inviteCode: string
): Promise<RegisterResponse> => {
  const response = await fetch(`${API_BASE_URL}/api/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ email, password, invite_code: inviteCode }),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Registration failed');
  }

  return response.json();
};

/**
 * Verify email with 6-digit code
 */
export const verifyEmail = async (
  userId: string,
  code: string
): Promise<VerifyEmailResponse> => {
  const response = await fetch(`${API_BASE_URL}/api/auth/verify-email`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ user_id: userId, code }),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Verification failed');
  }

  return response.json();
};

/**
 * Login with email and password
 * Sets HttpOnly cookie on success
 */
export const login = async (
  email: string,
  password: string
): Promise<LoginResponse> => {
  const response = await fetch(`${API_BASE_URL}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ email, password }),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Invalid credentials');
  }

  return response.json();
};

/**
 * Logout - clears HttpOnly cookie
 */
export const logout = async (): Promise<void> => {
  const response = await fetch(`${API_BASE_URL}/api/auth/logout`, {
    method: 'POST',
    credentials: 'include',
  });

  if (!response.ok) {
    throw new Error('Logout failed');
  }
};

/**
 * Get current user info
 */
export const getCurrentUser = async (): Promise<User> => {
  const response = await fetch(`${API_BASE_URL}/api/auth/me`, {
    method: 'GET',
    credentials: 'include',
  });

  if (!response.ok) {
    throw new Error('Not authenticated');
  }

  return response.json();
};

/**
 * Request password reset code via email
 */
export const forgotPassword = async (email: string): Promise<{ message: string }> => {
  const response = await fetch(`${API_BASE_URL}/api/auth/forgot-password`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ email }),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Request failed');
  }

  return response.json();
};

/**
 * Reset password with code and new password
 */
export const resetPassword = async (
  email: string,
  code: string,
  newPassword: string
): Promise<{ success: boolean }> => {
  const response = await fetch(`${API_BASE_URL}/api/auth/reset-password`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ email, code, new_password: newPassword }),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Reset failed');
  }

  return response.json();
};

/**
 * Resend verification code to email
 */
export const resendVerificationCode = async (email: string): Promise<{ message: string }> => {
  const response = await fetch(`${API_BASE_URL}/api/auth/resend-verification`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ email }),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to resend code');
  }

  return response.json();
};
