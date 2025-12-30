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
 *
 * For files >= 100MB, uses resumable upload protocol (two-step):
 * 1. POST to signed URL with x-goog-resumable: start -> returns session URI
 * 2. PUT file data to session URI
 *
 * For files < 100MB, uses simple PUT upload.
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

  const contentType = file.type || 'video/mp4';
  console.log(`[GCS] Starting ${method} upload to: ${gcs_path}`);

  // For resumable uploads (method === "POST"), we need to:
  // 1. First initiate the resumable session to get a session URI
  // 2. Then upload the file to that session URI
  if (method === 'POST') {
    return uploadResumable(file, upload_url, gcs_path, contentType, onProgress);
  }

  // Simple PUT upload for smaller files
  return uploadSimple(file, upload_url, gcs_path, contentType, onProgress);
}

/**
 * Simple PUT upload for files < 100MB
 */
async function uploadSimple(
  file: File,
  uploadUrl: string,
  gcsPath: string,
  contentType: string,
  onProgress?: (loaded: number, total: number, percentage: number) => void
): Promise<string> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();

    xhr.upload.addEventListener('progress', (event) => {
      if (event.lengthComputable && onProgress) {
        const percentage = Math.round((event.loaded / event.total) * 100);
        onProgress(event.loaded, event.total, percentage);
        console.log(`[GCS] Upload progress: ${percentage}%`);
      }
    });

    xhr.addEventListener('load', () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        console.log(`[GCS] Upload complete: ${gcsPath}`);
        resolve(gcsPath);
      } else {
        console.error(`[GCS] Upload failed with status: ${xhr.status}`, xhr.responseText);
        reject(new Error(`Upload failed with status ${xhr.status}: ${xhr.responseText}`));
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

    xhr.open('PUT', uploadUrl);
    xhr.setRequestHeader('Content-Type', contentType);
    xhr.send(file);
  });
}

/**
 * Resumable upload for large files (>= 100MB)
 *
 * GCS Resumable Upload Protocol:
 * Step 1: POST to signed URL with "x-goog-resumable: start" header
 *         -> GCS returns 200 OK with "Location" header containing session URI
 * Step 2: PUT file data to the session URI
 *         -> GCS returns 200 OK when complete
 */
async function uploadResumable(
  file: File,
  initiationUrl: string,
  gcsPath: string,
  contentType: string,
  onProgress?: (loaded: number, total: number, percentage: number) => void
): Promise<string> {
  // Step 1: Initiate resumable upload session
  console.log('[GCS] Initiating resumable upload session...');

  const initResponse = await fetch(initiationUrl, {
    method: 'POST',
    headers: {
      'Content-Type': contentType,
      'x-goog-resumable': 'start',
      'Content-Length': '0',
    },
  });

  if (!initResponse.ok) {
    const errorText = await initResponse.text();
    console.error(`[GCS] Failed to initiate resumable upload: ${initResponse.status}`, errorText);
    throw new Error(`Failed to initiate resumable upload: ${initResponse.status} ${errorText}`);
  }

  // Get the session URI from the Location header
  const sessionUri = initResponse.headers.get('Location');
  if (!sessionUri) {
    console.error('[GCS] No Location header in resumable upload response');
    throw new Error('No session URI returned from GCS');
  }

  console.log(`[GCS] Got session URI, uploading ${formatFileSize(file.size)}...`);

  // Step 2: Upload the file to the session URI
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();

    xhr.upload.addEventListener('progress', (event) => {
      if (event.lengthComputable && onProgress) {
        const percentage = Math.round((event.loaded / event.total) * 100);
        onProgress(event.loaded, event.total, percentage);
        if (percentage % 10 === 0) {
          console.log(`[GCS] Resumable upload progress: ${percentage}%`);
        }
      }
    });

    xhr.addEventListener('load', () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        console.log(`[GCS] Resumable upload complete: ${gcsPath}`);
        resolve(gcsPath);
      } else {
        console.error(`[GCS] Resumable upload failed with status: ${xhr.status}`, xhr.responseText);
        reject(new Error(`Resumable upload failed with status ${xhr.status}: ${xhr.responseText}`));
      }
    });

    xhr.addEventListener('error', () => {
      console.error('[GCS] Resumable upload network error');
      reject(new Error('Resumable upload failed due to network error'));
    });

    xhr.addEventListener('abort', () => {
      console.warn('[GCS] Resumable upload aborted');
      reject(new Error('Resumable upload was aborted'));
    });

    // PUT the file to the session URI (NOT the original signed URL)
    xhr.open('PUT', sessionUri);
    xhr.setRequestHeader('Content-Type', contentType);
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
