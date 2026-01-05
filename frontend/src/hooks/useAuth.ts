/**
 * useAuth - Custom hook for app-level password protection
 * Manages session tokens in localStorage with 7-day expiry
 */

import { useState, useCallback, useEffect } from 'react';
import { API_BASE_URL } from '../config';

const STORAGE_KEY = 'ai-subs-auth';

interface StoredSession {
  token: string;
  expiresAt: number; // Unix timestamp (seconds)
}

interface AuthState {
  isAuthenticated: boolean;
  isLoading: boolean;
  isProtectionEnabled: boolean | null; // null = checking, false = no protection
  error: string | null;
}

export const useAuth = () => {
  const [state, setState] = useState<AuthState>({
    isAuthenticated: false,
    isLoading: true,
    isProtectionEnabled: null,
    error: null,
  });

  // Check if stored session is valid (not expired locally)
  const getStoredSession = useCallback((): StoredSession | null => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (!stored) return null;

      const session: StoredSession = JSON.parse(stored);
      const now = Math.floor(Date.now() / 1000);

      // Check if expired
      if (session.expiresAt < now) {
        localStorage.removeItem(STORAGE_KEY);
        return null;
      }

      return session;
    } catch {
      localStorage.removeItem(STORAGE_KEY);
      return null;
    }
  }, []);

  // Check if password protection is enabled on the server
  const checkProtectionStatus = useCallback(async (): Promise<boolean> => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/auth/status`);
      if (!response.ok) return true; // Assume protected if can't reach
      const data = await response.json();
      return data.password_protection_enabled;
    } catch {
      // If we can't reach the server, assume protected
      return true;
    }
  }, []);

  // Validate session with backend
  const validateSession = useCallback(async (token: string): Promise<boolean> => {
    try {
      const response = await fetch(
        `${API_BASE_URL}/api/auth/validate?session_token=${encodeURIComponent(token)}`,
        { method: 'POST' }
      );
      if (!response.ok) return false;
      const data = await response.json();
      return data.valid;
    } catch {
      return false;
    }
  }, []);

  // Login with password
  const login = useCallback(async (password: string): Promise<boolean> => {
    setState(s => ({ ...s, isLoading: true, error: null }));

    try {
      const response = await fetch(`${API_BASE_URL}/api/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password }),
      });

      if (!response.ok) {
        const error = await response.json();
        setState(s => ({
          ...s,
          isLoading: false,
          error: error.detail || 'Invalid password',
        }));
        return false;
      }

      const data = await response.json();

      // Store session
      const session: StoredSession = {
        token: data.session_token,
        expiresAt: data.expires_at,
      };
      localStorage.setItem(STORAGE_KEY, JSON.stringify(session));

      setState({
        isAuthenticated: true,
        isLoading: false,
        isProtectionEnabled: true,
        error: null,
      });

      return true;
    } catch {
      setState(s => ({
        ...s,
        isLoading: false,
        error: 'Connection error. Please try again.',
      }));
      return false;
    }
  }, []);

  // Logout
  const logout = useCallback(async () => {
    const session = getStoredSession();
    if (session) {
      // Best effort logout on server
      try {
        await fetch(
          `${API_BASE_URL}/api/auth/logout?session_token=${encodeURIComponent(session.token)}`,
          { method: 'POST' }
        );
      } catch {
        // Ignore errors
      }
    }
    localStorage.removeItem(STORAGE_KEY);
    setState(s => ({
      ...s,
      isAuthenticated: false,
      isLoading: false,
      error: null,
    }));
  }, [getStoredSession]);

  // Check auth on mount
  useEffect(() => {
    const checkAuth = async () => {
      // First check if protection is even enabled
      const isProtected = await checkProtectionStatus();

      if (!isProtected) {
        // No protection - let everyone in
        setState({
          isAuthenticated: true,
          isLoading: false,
          isProtectionEnabled: false,
          error: null,
        });
        return;
      }

      // Protection enabled - check for valid session
      const session = getStoredSession();

      if (!session) {
        setState({
          isAuthenticated: false,
          isLoading: false,
          isProtectionEnabled: true,
          error: null,
        });
        return;
      }

      // Validate with backend
      const valid = await validateSession(session.token);

      if (valid) {
        setState({
          isAuthenticated: true,
          isLoading: false,
          isProtectionEnabled: true,
          error: null,
        });
      } else {
        localStorage.removeItem(STORAGE_KEY);
        setState({
          isAuthenticated: false,
          isLoading: false,
          isProtectionEnabled: true,
          error: null,
        });
      }
    };

    checkAuth();
  }, [checkProtectionStatus, getStoredSession, validateSession]);

  return {
    ...state,
    login,
    logout,
  };
};
