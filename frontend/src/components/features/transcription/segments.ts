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
