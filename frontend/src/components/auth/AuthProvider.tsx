import { useState, useCallback, useEffect } from 'react';
import toast from 'react-hot-toast';
import type { User } from '../../services/auth';
import * as authService from '../../services/auth';
import { AuthContext } from '../../hooks/useAuth';

const JOBS_CACHE_KEY = 'ai-subs-jobs-cache';

const clearJobsCache = () => {
  try {
    localStorage.removeItem(JOBS_CACHE_KEY);
  } catch {
    // Ignore storage errors; auth should not fail because cache cleanup failed.
  }
};

export const AuthProvider = ({ children }: { children: React.ReactNode }) => {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchUser = useCallback(async (retries = 3) => {
    for (let attempt = 0; attempt < retries; attempt++) {
      try {
        const userData = await authService.getCurrentUser();
        setUser(userData);
        setError(null);
        setIsLoading(false);
        return;
      } catch (error: unknown) {
        const status = (error as { status?: number; response?: { status?: number } })?.status
          || (error as { response?: { status?: number } })?.response?.status;

        if (status === 401 || status === 403) {
          setUser(null);
          setIsLoading(false);
          return;
        }
        if (attempt < retries - 1) {
          await new Promise(resolve => setTimeout(resolve, 1000 * (attempt + 1)));
        }
      }
    }
    setIsLoading(false);
  }, []);

  useEffect(() => {
    fetchUser();
  }, [fetchUser]);

  const login = useCallback(async (email: string, password: string) => {
    setIsLoading(true);
    setError(null);
    try {
      clearJobsCache();
      await authService.login(email, password);
      await fetchUser();
      toast.success('Logged in successfully!');
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Login failed';
      setError(message);
      toast.error(message);
      throw error;
    } finally {
      setIsLoading(false);
    }
  }, [fetchUser]);

  const logout = useCallback(async () => {
    try {
      await authService.logout();
      setUser(null);
      clearJobsCache();
      toast.success('Logged out successfully');
    } catch {
      toast.error('Logout failed');
    }
  }, []);

  const register = useCallback(async (email: string, password: string, inviteCode: string) => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await authService.register(email, password, inviteCode);
      toast.success(response.message);
      return response.user_id;
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Registration failed';
      setError(message);
      toast.error(message);
      throw error;
    } finally {
      setIsLoading(false);
    }
  }, []);

  const verifyEmail = useCallback(async (userId: string, code: string) => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await authService.verifyEmail(userId, code);
      setUser(response.user);
      toast.success('Email verified successfully!');
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Verification failed';
      setError(message);
      toast.error(message);
      throw error;
    } finally {
      setIsLoading(false);
    }
  }, []);

  const refetchUser = useCallback(async () => {
    await fetchUser();
  }, [fetchUser]);

  return (
    <AuthContext.Provider value={{
      user,
      isAuthenticated: !!user,
      isLoading,
      error,
      login,
      logout,
      register,
      verifyEmail,
      refetchUser,
    }}>
      {children}
    </AuthContext.Provider>
  );
};
