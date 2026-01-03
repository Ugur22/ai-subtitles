/**
 * Time utility functions for transcription and video playback
 */

/**
 * Formats processing time for better readability
 * @param timeStr - Time string (e.g., "45.2 seconds" or "45.2")
 * @returns Formatted time string (e.g., "45.2 seconds" or "1 minute 23 seconds")
 */
export const formatProcessingTime = (timeStr?: string | null): string => {
  // Return a default value if timeStr is undefined or null
  if (!timeStr) {
    return "Unknown";
  }

  // Try to extract a numeric value from the time string
  let seconds = 0;

  // Try to parse seconds from the string
  if (timeStr.includes("seconds")) {
    seconds = parseFloat(timeStr.replace(" seconds", "").trim());
  } else {
    // If it's a number without units, assume it's seconds
    const parsed = parseFloat(timeStr);
    if (!isNaN(parsed)) {
      seconds = parsed;
    }
  }

  // If we've successfully parsed a seconds value
  if (seconds > 0) {
    if (seconds < 5) {
      // Very fast processing
      return `${seconds.toFixed(1)} seconds (super fast!)`;
    } else if (seconds < 60) {
      // Less than a minute, keep as seconds
      return `${seconds.toFixed(1)} seconds`;
    } else {
      // Convert to minutes and seconds
      const minutes = Math.floor(seconds / 60);
      const remainingSeconds = Math.round(seconds % 60);

      if (remainingSeconds === 0) {
        // Even minutes
        return minutes === 1 ? "1 minute" : `${minutes} minutes`;
      } else {
        // Minutes and seconds
        return minutes === 1
          ? `1 minute ${remainingSeconds} seconds`
          : `${minutes} minutes ${remainingSeconds} seconds`;
      }
    }
  }

  // If we couldn't parse it, return the original
  return timeStr;
};

/**
 * Converts seconds to HH:MM:SS or MM:SS time string
 * @param seconds - Number of seconds
 * @returns Time string in HH:MM:SS or MM:SS format
 */
export const secondsToTimeString = (seconds: number): string => {
  if (isNaN(seconds) || seconds < 0) return "";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) {
    return `${h.toString().padStart(2, "0")}:${m
      .toString()
      .padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
  } else {
    return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
  }
};

/**
 * Converts HH:MM:SS time string to seconds
 * @param timeString - Time string in HH:MM:SS format
 * @returns Number of seconds
 */
export const convertTimeToSeconds = (timeString: string): number => {
  const [hours, minutes, seconds] = timeString.split(":").map(Number);
  return hours * 3600 + minutes * 60 + seconds;
};

/**
 * Converts HH:MM:SS or HH:MM:SS.mmm time string to seconds
 * @param timeStr - Time string
 * @returns Number of seconds (including fractional seconds)
 */
export const timeToSeconds = (timeStr: string): number => {
  try {
    // Handle different time formats: HH:MM:SS or HH:MM:SS.mmm
    const parts = timeStr.split(":");
    if (parts.length !== 3) {
      console.error(`Invalid time format: ${timeStr}`);
      return 0;
    }

    const hours = parseInt(parts[0], 10);
    const minutes = parseInt(parts[1], 10);
    // Handle seconds with milliseconds
    const seconds = parseFloat(parts[2]);

    return hours * 3600 + minutes * 60 + seconds;
  } catch (error) {
    console.error(`Error converting time ${timeStr} to seconds:`, error);
    return 0;
  }
};

/**
 * Converts HH:MM:SS.mmm time string to milliseconds
 * @param timeString - Time string in HH:MM:SS.mmm format
 * @returns Number of milliseconds
 */
export const timeToMs = (timeString: string): number => {
  const [time, ms = "0"] = timeString.split(".");
  const [hours, minutes, seconds] = time.split(":").map(Number);

  return (
    (hours * 3600 + minutes * 60 + seconds) * 1000 +
    parseInt(ms.padEnd(3, "0").substring(0, 3))
  );
};

/**
 * Converts milliseconds to HH:MM:SS.mmm time string
 * @param ms - Number of milliseconds
 * @returns Time string in HH:MM:SS.mmm format
 */
export const msToTime = (ms: number): string => {
  const totalSeconds = Math.floor(ms / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  const milliseconds = ms % 1000;

  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(
    2,
    "0"
  )}:${String(seconds).padStart(2, "0")}.${String(milliseconds).padStart(
    3,
    "0"
  )}`;
};

/**
 * Formats a duration in seconds to a human-readable string
 * @param seconds - Duration in seconds
 * @returns Formatted string like "2 min 30 sec" or "45 sec"
 */
export const formatDuration = (seconds: number): string => {
  if (seconds < 60) {
    return `${Math.round(seconds)} sec`;
  }

  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = Math.round(seconds % 60);

  if (remainingSeconds === 0) {
    return `${minutes} min`;
  }

  return `${minutes} min ${remainingSeconds} sec`;
};

/**
 * Formats an ISO date string to a relative time string
 * @param isoString - ISO 8601 date string
 * @returns Relative time string like "2 hours ago", "yesterday", etc.
 */
export const formatRelativeTime = (isoString: string): string => {
  const date = new Date(isoString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSec = Math.floor(diffMs / 1000);
  const diffMin = Math.floor(diffSec / 60);
  const diffHours = Math.floor(diffMin / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffSec < 60) {
    return "just now";
  } else if (diffMin < 60) {
    return `${diffMin} ${diffMin === 1 ? "minute" : "minutes"} ago`;
  } else if (diffHours < 24) {
    return `${diffHours} ${diffHours === 1 ? "hour" : "hours"} ago`;
  } else if (diffDays === 1) {
    return "yesterday";
  } else if (diffDays < 7) {
    return `${diffDays} days ago`;
  } else {
    // For older dates, show the actual date
    return date.toLocaleDateString();
  }
};
