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
    .replace(/\u200B/g, "")
    // Remove zero-width non-joiner
    .replace(/\u200C/g, "")
    // Remove zero-width joiner
    .replace(/\u200D/g, "")
    // Remove null characters
    .replace(/\u0000/g, "")
    // Remove any other control characters at the start
    .replace(/^[\x00-\x1F\x7F]+/, "")
    .trim();

  // If empty after cleaning, return undefined
  if (!cleanUrl) return undefined;

  // Fix malformed URLs that have https// or http// (missing colon)
  // This handles cases where the colon might have been stripped
  // Check various patterns that might indicate a malformed protocol
  if (cleanUrl.match(/^https?\/\//i)) {
    cleanUrl = cleanUrl.replace(/^(https?)(\/\/)/i, "$1:$2");
  }
  // Also handle case where URL might have extra characters before https
  // e.g., some invisible char followed by https//
  else if (cleanUrl.includes("https//") || cleanUrl.includes("http//")) {
    // Find and fix the malformed protocol
    cleanUrl = cleanUrl
      .replace(/https\/\//gi, "https://")
      .replace(/http\/\//gi, "http://");
  }

  // If URL starts with a valid HTTP/HTTPS protocol, return as-is
  if (cleanUrl.match(/^https?:\/\//i)) {
    return cleanUrl;
  }

  // Debug: Log when we're about to prepend API_BASE_URL
  // This helps identify URLs that weren't caught by the above checks
  if (process.env.NODE_ENV === "development" || cleanUrl.includes("storage.googleapis.com")) {
    console.warn("[formatScreenshotUrl] Prepending API_BASE_URL to:", cleanUrl.substring(0, 100));
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
