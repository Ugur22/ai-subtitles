/**
 * useAuth - Authentication hook with Supabase Auth + HttpOnly cookies
 * Exposes authentication state and operations from AuthProvider
 */

import { createContext, useContext } from 'react';
import type { User } from '../services/auth';

export interface AuthContextType {
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

export const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const useAuth = (): AuthContextType => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return context;
};
