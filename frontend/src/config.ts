/**
 * Application configuration
 * Uses Vite environment variables for deployment flexibility
 */

// API base URL - defaults to localhost for development
// Force https:// if the env var has http://
const rawApiUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';
export const API_BASE_URL = rawApiUrl.replace(/^http:\/\/(?!localhost)/, 'https://');

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
