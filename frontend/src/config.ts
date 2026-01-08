/**
 * Application configuration
 * Uses Vite environment variables for deployment flexibility
 */

// API base URL configuration
// In production (Netlify), use empty string so requests go to /api/* which gets proxied
// In development, use the full backend URL
const isProduction = import.meta.env.PROD;
const rawApiUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export const API_BASE_URL = isProduction ? '' : rawApiUrl;

// Debug logging for URL configuration (will show in browser console)
if (typeof window !== 'undefined') {
  console.log('[Config] Production mode:', isProduction);
  console.log('[Config] API_BASE_URL:', API_BASE_URL || '(empty - using Netlify proxy)');
}

// Helper to construct full API URLs
export const getApiUrl = (path: string): string => {
  const base = API_BASE_URL.endsWith('/') ? API_BASE_URL.slice(0, -1) : API_BASE_URL;
  const cleanPath = path.startsWith('/') ? path : `/${path}`;
  return `${base}${cleanPath}`;
};

// Helper for static asset URLs (screenshots, videos, etc.)
export const getStaticUrl = (path: string): string => {
  return getApiUrl(path);
};
