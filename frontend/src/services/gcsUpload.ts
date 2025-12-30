/**
 * GCS Upload Service
 *
 * Handles direct-to-GCS uploads for large files that exceed Cloud Run's 32MB limit.
 * Uses signed URLs to upload directly to Google Cloud Storage, bypassing the backend.
 */

import { API_BASE_URL } from '../config';

// 32MB - Cloud Run's hard limit for HTTP/1.1 requests
export const DIRECT_UPLOAD_LIMIT = 32 * 1024 * 1024;

export interface SignedUrlResponse {
  upload_url: string;
  gcs_path: string;
  method: string;
  expires_in: number;
}

export interface UploadConfig {
  gcs_enabled: boolean;
  direct_upload_limit: number;
  gcs_bucket: string | null;
  max_file_size: number;
}

/**
 * Get upload configuration from the server
 */
export async function getUploadConfig(): Promise<UploadConfig> {
  const response = await fetch(`${API_BASE_URL}/api/upload/config`);
  if (!response.ok) {
    throw new Error('Failed to get upload config');
  }
  return response.json();
}

/**
 * Get a signed URL for uploading to GCS
 */
export async function getSignedUploadUrl(
  filename: string,
  contentType: string,
  fileSize: number
): Promise<SignedUrlResponse> {
  const response = await fetch(`${API_BASE_URL}/api/upload/signed-url`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      filename,
      content_type: contentType,
      file_size: fileSize,
    }),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to get upload URL');
  }

  return response.json();
}

/**
 * Upload a file directly to GCS using a signed URL
 *
 * This bypasses the backend entirely, uploading directly to Google Cloud Storage.
 * Progress is tracked via XMLHttpRequest for accurate percentage reporting.
 */
export async function uploadToGCS(
  file: File,
  onProgress?: (loaded: number, total: number, percentage: number) => void
): Promise<string> {
  // Get signed URL from backend
  const { upload_url, gcs_path, method } = await getSignedUploadUrl(
    file.name,
    file.type || 'video/mp4',
    file.size
  );

  console.log(`[GCS] Starting ${method} upload to: ${gcs_path}`);

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();

    // Track upload progress
    xhr.upload.addEventListener('progress', (event) => {
      if (event.lengthComputable && onProgress) {
        const percentage = Math.round((event.loaded / event.total) * 100);
        onProgress(event.loaded, event.total, percentage);
        console.log(`[GCS] Upload progress: ${percentage}%`);
      }
    });

    xhr.addEventListener('load', () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        console.log(`[GCS] Upload complete: ${gcs_path}`);
        resolve(gcs_path);
      } else {
        console.error(`[GCS] Upload failed with status: ${xhr.status}`);
        reject(new Error(`Upload failed with status ${xhr.status}`));
      }
    });

    xhr.addEventListener('error', () => {
      console.error('[GCS] Upload network error');
      reject(new Error('Upload failed due to network error'));
    });

    xhr.addEventListener('abort', () => {
      console.warn('[GCS] Upload aborted');
      reject(new Error('Upload was aborted'));
    });

    xhr.open(method, upload_url);
    xhr.setRequestHeader('Content-Type', file.type || 'video/mp4');
    xhr.send(file);
  });
}

/**
 * Check if a file requires GCS upload (larger than Cloud Run limit)
 */
export function requiresGCSUpload(fileSize: number): boolean {
  return fileSize > DIRECT_UPLOAD_LIMIT;
}

/**
 * Format file size for display
 */
export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}
