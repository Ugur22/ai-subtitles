/**
 * Convert seconds to HH:MM:SS format
 * @param seconds - Time in seconds (can be decimal)
 * @returns Formatted time string (HH:MM:SS)
 */
export function formatTimestamp(seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);

  return `${hours.toString().padStart(2, "0")}:${minutes
    .toString()
    .padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
}

/**
 * Parse timestamp string (HH:MM:SS or MM:SS) to seconds
 * @param timestamp - Time string in HH:MM:SS or MM:SS format
 * @returns Time in seconds
 */
export function parseTimestamp(timestamp: string): number {
  const parts = timestamp.split(":").map(Number);

  if (parts.length === 3) {
    // HH:MM:SS
    return parts[0] * 3600 + parts[1] * 60 + parts[2];
  } else if (parts.length === 2) {
    // MM:SS
    return parts[0] * 60 + parts[1];
  }

  return 0;
}
