import type { TranscriptionResponse } from "../../../services/api";

export type TranscriptSegment = TranscriptionResponse["transcription"]["segments"][number];

export function filterDisplayedSegments(
  segments: TranscriptSegment[],
  filteredSpeaker: string | null,
  showVisualMoments: boolean,
): TranscriptSegment[] {
  if (!filteredSpeaker) {
    if (showVisualMoments) return segments;
    return segments.filter((seg) => !seg.is_silent);
  }

  return segments.filter(
    (seg) =>
      seg.speaker === filteredSpeaker || (showVisualMoments && seg.is_silent)
  );
}

export function listUniqueSpeakers(segments: TranscriptSegment[]): string[] {
  const speakers = new Set(
    segments
      .map((seg) => seg.speaker)
      .filter((speaker): speaker is string => !!speaker)
  );
  return Array.from(speakers).sort();
}

export function formatSegmentCount(count: number): string {
  return `${count} ${count === 1 ? "segment" : "segments"}`;
}

/** Count shown on the Speakers button: distinct speakers, or the filtered speaker's segments. */
export function speakerFilterCountLabel(
  segments: TranscriptSegment[],
  uniqueSpeakers: string[],
  filteredSpeaker: string | null,
): string {
  if (!filteredSpeaker) return `(${uniqueSpeakers.length})`;
  return `· ${formatSegmentCount(segments.filter((seg) => seg.speaker === filteredSpeaker).length)}`;
}
