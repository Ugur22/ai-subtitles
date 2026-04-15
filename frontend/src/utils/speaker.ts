/**
 * Speaker-related utility functions for transcription
 */

export interface SpeakerColors {
  bg: string;
  text: string;
  border: string;
}

export const formatSpeakerLabel = (speaker: string): string => {
  if (!speaker) return "Speaker 1";
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
 * Gets consistent dark-mode colors for speaker labels.
 * Returns Tailwind classes that are dark-mode compatible (muted/translucent).
 */
export const getSpeakerColor = (speaker: string): SpeakerColors => {
  const colors: SpeakerColors[] = [
    { bg: "bg-violet-100 dark:bg-violet-500/20",  text: "text-violet-700 dark:text-violet-300",  border: "border-violet-300 dark:border-violet-500/30" },
    { bg: "bg-rose-100 dark:bg-rose-500/20",      text: "text-rose-700 dark:text-rose-300",      border: "border-rose-300 dark:border-rose-500/30" },
    { bg: "bg-emerald-100 dark:bg-emerald-500/20",text: "text-emerald-700 dark:text-emerald-300",border: "border-emerald-300 dark:border-emerald-500/30" },
    { bg: "bg-amber-100 dark:bg-amber-500/20",    text: "text-amber-700 dark:text-amber-300",    border: "border-amber-300 dark:border-amber-500/30" },
    { bg: "bg-cyan-100 dark:bg-cyan-500/20",      text: "text-cyan-700 dark:text-cyan-300",      border: "border-cyan-300 dark:border-cyan-500/30" },
    { bg: "bg-pink-100 dark:bg-pink-500/20",      text: "text-pink-700 dark:text-pink-300",      border: "border-pink-300 dark:border-pink-500/30" },
    { bg: "bg-purple-100 dark:bg-purple-500/20",  text: "text-purple-700 dark:text-purple-300",  border: "border-purple-300 dark:border-purple-500/30" },
    { bg: "bg-teal-100 dark:bg-teal-500/20",      text: "text-teal-700 dark:text-teal-300",      border: "border-teal-300 dark:border-teal-500/30" },
  ];

  const hash = speaker.split("").reduce((acc, char) => char.charCodeAt(0) + acc, 0);
  return colors[hash % colors.length];
};
