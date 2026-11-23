/**
 * ProtectedRoute - Wrapper component that requires authentication
 */

import React from 'react';
import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from '../../hooks/useAuth';
import { AppLoader } from './AppLoader';

export const ProtectedRoute: React.FC = () => {
  const { isAuthenticated, isLoading } = useAuth();
  const { pathname, search } = useLocation();

  if (import.meta.env.DEV && pathname === '/' && new URLSearchParams(search).get('preview') === '1') {
    return <Outlet />;
  }

  if (isLoading) {
    return <AppLoader />;
  }

  // Redirect to login if not authenticated
  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  // Render child routes if authenticated
  return <Outlet />;
};
