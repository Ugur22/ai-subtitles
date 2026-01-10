/**
 * File utility functions
 * Provides file hashing and size formatting utilities
 */

import { createSHA256 } from 'hash-wasm';

/**
 * Generate a SHA-256 hash of a file using streaming hash algorithm.
 * Reads the file in chunks to handle large files efficiently without duplicating in memory.
 *
 * @param file - The File object to hash
 * @param onProgress - Optional progress callback (0-100)
 * @returns Promise<string> - Hex-encoded SHA-256 hash
 */
export async function generateFileHash(
  file: File,
  onProgress?: (progress: number) => void
): Promise<string> {
  const CHUNK_SIZE = 8 * 1024 * 1024; // 8MB chunks
  const hasher = await createSHA256();
  hasher.init();

  const totalChunks = Math.ceil(file.size / CHUNK_SIZE);

  for (let i = 0; i < totalChunks; i++) {
    const start = i * CHUNK_SIZE;
    const end = Math.min(start + CHUNK_SIZE, file.size);
    const chunk = file.slice(start, end);
    const buffer = await chunk.arrayBuffer();
    hasher.update(new Uint8Array(buffer));

    if (onProgress) {
      onProgress(Math.round(((i + 1) / totalChunks) * 100));
    }
  }

  return hasher.digest('hex');
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

/**
 * Get file extension from filename
 */
export function getFileExtension(filename: string): string {
  const parts = filename.split('.');
  return parts.length > 1 ? parts.pop()?.toLowerCase() || '' : '';
}

/**
 * Check if a file is a video based on extension
 */
export function isVideoFile(filename: string): boolean {
  const videoExtensions = ['mp4', 'mpeg', 'mpga', 'm4a', 'wav', 'webm', 'mp3', 'mov', 'mkv', 'avi'];
  const ext = getFileExtension(filename);
  return videoExtensions.includes(ext);
}
