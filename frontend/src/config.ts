/**
 * Application configuration
 * Uses Vite environment variables for deployment flexibility
 */

// API base URL - defaults to localhost for development
// Force https:// if the env var has http:// (except localhost)
const rawApiUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';

// Ensure HTTPS for production URLs
function ensureHttps(url: string): string {
  // Keep localhost as-is for development
  if (url.includes('localhost') || url.includes('127.0.0.1')) {
    return url;
  }
  // Force HTTPS for all production URLs
  return url.replace(/^http:\/\//i, 'https://');
}

export const API_BASE_URL = ensureHttps(rawApiUrl);

// Debug logging for URL configuration (will show in browser console)
if (typeof window !== 'undefined') {
  console.log('[Config] VITE_API_URL env:', import.meta.env.VITE_API_URL);
  console.log('[Config] Raw API URL:', rawApiUrl);
  console.log('[Config] Final API_BASE_URL:', API_BASE_URL);
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
