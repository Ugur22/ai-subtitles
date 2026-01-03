/**
 * File utility functions
 * Provides file hashing and size formatting utilities
 */

/**
 * Generate a SHA-256 hash of a file using Web Crypto API.
 * Reads the file in chunks to handle large files efficiently.
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
  const chunks: ArrayBuffer[] = [];
  const totalChunks = Math.ceil(file.size / CHUNK_SIZE);

  // Read file in chunks
  for (let i = 0; i < totalChunks; i++) {
    const start = i * CHUNK_SIZE;
    const end = Math.min(start + CHUNK_SIZE, file.size);
    const chunk = file.slice(start, end);
    const buffer = await chunk.arrayBuffer();
    chunks.push(buffer);

    if (onProgress) {
      onProgress(Math.round(((i + 1) / totalChunks) * 100));
    }
  }

  // Combine all chunks
  const totalSize = chunks.reduce((acc, chunk) => acc + chunk.byteLength, 0);
  const combined = new Uint8Array(totalSize);
  let offset = 0;
  for (const chunk of chunks) {
    combined.set(new Uint8Array(chunk), offset);
    offset += chunk.byteLength;
  }

  // Generate SHA-256 hash
  const hashBuffer = await crypto.subtle.digest('SHA-256', combined);
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  const hashHex = hashArray.map(b => b.toString(16).padStart(2, '0')).join('');

  return hashHex;
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
