/**
 * Application configuration
 * Uses Vite environment variables for deployment flexibility
 */

// API base URL configuration
// Prefer VITE_API_URL whenever it is configured. In production this avoids
// long-running chat requests being capped by the Netlify /api proxy.
const isProduction = import.meta.env.PROD;
const configuredApiUrl = import.meta.env.VITE_API_URL;

export const API_BASE_URL = configuredApiUrl || (isProduction ? '' : 'http://localhost:8000');

// Debug logging for URL configuration (will show in browser console)
if (typeof window !== 'undefined') {
  console.log('[Config] Production mode:', isProduction);
  console.log('[Config] API_BASE_URL:', API_BASE_URL || '(empty - using same-origin proxy)');
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
