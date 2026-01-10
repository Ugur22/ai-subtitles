/**
 * useAuth - Authentication hook with Supabase Auth + HttpOnly cookies
 * Manages user authentication state and operations
 */

import React, { useState, useCallback, useEffect, createContext, useContext } from 'react';
import toast from 'react-hot-toast';
import type { User } from '../services/auth';
import * as authService from '../services/auth';

interface AuthContextType {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  error: string | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  register: (email: string, password: string, inviteCode: string) => Promise<string>;
  verifyEmail: (userId: string, code: string) => Promise<void>;
  refetchUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider = ({ children }: { children: React.ReactNode }) => {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Fetch current user from cookie session
  const fetchUser = useCallback(async (retries = 3) => {
    for (let attempt = 0; attempt < retries; attempt++) {
      try {
        const userData = await authService.getCurrentUser();
        setUser(userData);
        setError(null);
        setIsLoading(false);
        return;
      } catch (err: unknown) {
        // Extract status code from error
        const status = (err as { status?: number; response?: { status?: number } })?.status
          || (err as { response?: { status?: number } })?.response?.status;

        // Only logout on actual auth failures (401/403)
        if (status === 401 || status === 403) {
          setUser(null);
          setIsLoading(false);
          return;
        }

        // For 5xx errors or network errors, retry with exponential backoff
        if (attempt < retries - 1) {
          await new Promise(r => setTimeout(r, 1000 * (attempt + 1)));
          continue;
        }
        // After all retries fail with server error, keep existing user state
        // Don't logout - the session token is still valid, server is just having issues
      }
    }
    setIsLoading(false);
  }, []);

  // Check auth on mount
  useEffect(() => {
    fetchUser();
  }, [fetchUser]);

  const login = useCallback(
    async (email: string, password: string) => {
      setIsLoading(true);
      setError(null);
      try {
        await authService.login(email, password);
        // Fetch user data from /api/auth/me after successful login
        await fetchUser();
        toast.success('Logged in successfully!');
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Login failed';
        setError(message);
        toast.error(message);
        throw err;
      } finally {
        setIsLoading(false);
      }
    },
    [fetchUser]
  );

  const logout = useCallback(async () => {
    try {
      await authService.logout();
      setUser(null);
      toast.success('Logged out successfully');
    } catch (err) {
      toast.error('Logout failed');
    }
  }, []);

  const register = useCallback(
    async (email: string, password: string, inviteCode: string): Promise<string> => {
      setIsLoading(true);
      setError(null);
      try {
        const response = await authService.register(email, password, inviteCode);
        toast.success(response.message);
        return response.user_id;
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Registration failed';
        setError(message);
        toast.error(message);
        throw err;
      } finally {
        setIsLoading(false);
      }
    },
    []
  );

  const verifyEmail = useCallback(async (userId: string, code: string) => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await authService.verifyEmail(userId, code);
      setUser(response.user);
      toast.success('Email verified successfully!');
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Verification failed';
      setError(message);
      toast.error(message);
      throw err;
    } finally {
      setIsLoading(false);
    }
  }, []);

  const refetchUser = useCallback(async () => {
    await fetchUser();
  }, [fetchUser]);

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated: !!user,
        isLoading,
        error,
        login,
        logout,
        register,
        verifyEmail,
        refetchUser,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = (): AuthContextType => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return context;
};
