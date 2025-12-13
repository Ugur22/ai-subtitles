/**
 * Speaker-related utility functions for transcription
 */

/**
 * Color scheme for speaker labels
 */
export interface SpeakerColors {
  bg: string;
  text: string;
  border: string;
}

/**
 * Formats speaker labels for display
 * Converts SPEAKER_00 to "Speaker 1", SPEAKER_01 to "Speaker 2", etc.
 * @param speaker - Raw speaker identifier
 * @returns Formatted speaker label
 */
export const formatSpeakerLabel = (speaker: string): string => {
  if (!speaker) return "Speaker 1";

  // Convert SPEAKER_00 to Speaker 1, SPEAKER_01 to Speaker 2, etc.
  if (speaker.startsWith("SPEAKER_")) {
    try {
      const speakerNum = parseInt(speaker.split("_")[1]) + 1;
      return `Speaker ${speakerNum}`;
    } catch {
      return speaker;
    }
  }

  return speaker;
};

/**
 * Gets consistent colors for speaker labels
 * Uses a hash function to ensure the same speaker always gets the same color
 * @param speaker - Speaker identifier
 * @returns Color scheme object with bg, text, and border classes
 */
export const getSpeakerColor = (speaker: string): SpeakerColors => {
  const colors: SpeakerColors[] = [
    {
      bg: "bg-violet-100",
      text: "text-violet-800",
      border: "border-violet-300",
    },
    { bg: "bg-rose-100", text: "text-rose-800", border: "border-rose-300" },
    {
      bg: "bg-emerald-100",
      text: "text-emerald-800",
      border: "border-emerald-300",
    },
    { bg: "bg-amber-100", text: "text-amber-800", border: "border-amber-300" },
    { bg: "bg-cyan-100", text: "text-cyan-800", border: "border-cyan-300" },
    { bg: "bg-pink-100", text: "text-pink-800", border: "border-pink-300" },
    {
      bg: "bg-purple-100",
      text: "text-purple-800",
      border: "border-purple-300",
    },
    { bg: "bg-teal-100", text: "text-teal-800", border: "border-teal-300" },
  ];

  // Generate a consistent hash for the speaker
  const hash = speaker
    .split("")
    .reduce((acc, char) => char.charCodeAt(0) + acc, 0);
  return colors[hash % colors.length];
};
