/**
 * Speaker-related utility functions for transcription.
 * Disciplined 5-hue palette at consistent saturation, with light/dark variants
 * so badges read as a coherent set in both themes (WCAG AA in both).
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
 * Returns Tailwind classes for a speaker label badge.
 * - Light mode: dark text (xxx-800) on light tinted bg (xxx-100) — ~7:1 contrast
 * - Dark mode:  light text (xxx-300) on dark tinted bg (xxx-500/20) — readable
 */
export const getSpeakerColor = (speaker: string): SpeakerColors => {
  const colors: SpeakerColors[] = [
    { bg: "bg-emerald-100 dark:bg-emerald-500/20", text: "text-emerald-800 dark:text-emerald-300", border: "border-emerald-300 dark:border-emerald-500/30" },
    { bg: "bg-sky-100 dark:bg-sky-500/20",         text: "text-sky-800 dark:text-sky-300",         border: "border-sky-300 dark:border-sky-500/30" },
    { bg: "bg-amber-100 dark:bg-amber-500/20",     text: "text-amber-800 dark:text-amber-300",     border: "border-amber-300 dark:border-amber-500/30" },
    { bg: "bg-fuchsia-100 dark:bg-fuchsia-500/20", text: "text-fuchsia-800 dark:text-fuchsia-300", border: "border-fuchsia-300 dark:border-fuchsia-500/30" },
    { bg: "bg-orange-100 dark:bg-orange-500/20",   text: "text-orange-800 dark:text-orange-300",   border: "border-orange-300 dark:border-orange-500/30" },
  ];

  const hash = speaker.split("").reduce((acc, char) => char.charCodeAt(0) + acc, 0);
  return colors[hash % colors.length];
};
