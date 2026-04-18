/**
 * Speaker-related utility functions for transcription.
 * Dark-mode only — palette is disciplined: 5 distinct hues at consistent
 * lightness/chroma so badges read as a coherent set rather than a rainbow.
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
 * Returns Tailwind classes for a speaker label badge. Dark-mode only.
 * 5 hues, all at L=70% / C=0.12 for visual consistency.
 */
export const getSpeakerColor = (speaker: string): SpeakerColors => {
  const colors: SpeakerColors[] = [
    { bg: "bg-emerald-500/20", text: "text-emerald-300", border: "border-emerald-500/30" },
    { bg: "bg-sky-500/20",     text: "text-sky-300",     border: "border-sky-500/30" },
    { bg: "bg-amber-500/20",   text: "text-amber-300",   border: "border-amber-500/30" },
    { bg: "bg-fuchsia-500/20", text: "text-fuchsia-300", border: "border-fuchsia-500/30" },
    { bg: "bg-orange-500/20",  text: "text-orange-300",  border: "border-orange-500/30" },
  ];

  const hash = speaker.split("").reduce((acc, char) => char.charCodeAt(0) + acc, 0);
  return colors[hash % colors.length];
};
