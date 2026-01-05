/**
 * URL utility functions for handling screenshot URLs
 */

import { API_BASE_URL } from "../config";

/**
 * Format screenshot URL to handle various formats:
 * - Full GCS signed URLs (https://storage.googleapis.com/...)
 * - Malformed URLs with missing colon (https//... or http//...)
 * - Relative paths (/static/screenshots/...)
 * - URLs with invisible characters at the start
 *
 * @param url - The screenshot URL from the API
 * @returns Properly formatted URL or undefined if no valid URL
 */
export const formatScreenshotUrl = (
  url: string | null | undefined
): string | undefined => {
  if (!url) return undefined;

  // Trim whitespace and remove common invisible characters
  let cleanUrl = url
    .trim()
    // Remove BOM (Byte Order Mark)
    .replace(/^\uFEFF/, "")
    // Remove zero-width spaces
    .replace(/^\u200B/, "")
    // Remove zero-width non-joiner
    .replace(/^\u200C/, "")
    // Remove zero-width joiner
    .replace(/^\u200D/, "");

  // If empty after cleaning, return undefined
  if (!cleanUrl) return undefined;

  // Fix malformed URLs that have https// or http// (missing colon)
  // This handles cases where the colon might have been stripped
  if (cleanUrl.match(/^https?\/\//i)) {
    cleanUrl = cleanUrl.replace(/^(https?)(\/\/)/i, "$1:$2");
  }

  // If URL starts with a valid HTTP/HTTPS protocol, return as-is
  if (cleanUrl.match(/^https?:\/\//i)) {
    return cleanUrl;
  }

  // Otherwise, prepend the API base URL (for relative paths like /static/...)
  // Ensure we don't double-up slashes
  const base = API_BASE_URL.endsWith("/")
    ? API_BASE_URL.slice(0, -1)
    : API_BASE_URL;
  const path = cleanUrl.startsWith("/") ? cleanUrl : `/${cleanUrl}`;

  return `${base}${path}`;
};

/**
 * Same as formatScreenshotUrl but returns empty string instead of undefined
 * Useful for img src attributes where undefined might cause issues
 */
export const formatScreenshotUrlSafe = (
  url: string | null | undefined
): string => {
  return formatScreenshotUrl(url) || "";
};
