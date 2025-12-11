/**
 * Subtitle generation utilities
 */

import { timeToMs, msToTime } from "./time";

/**
 * Segment interface for subtitle generation
 */
export interface SubtitleSegment {
  start_time: string;
  end_time: string;
  text: string;
  translation?: string | null;
}

/**
 * Determines optimal chunk size based on language complexity
 * Some languages are more information-dense and need fewer words per line
 * @param lang - ISO language code (e.g., 'en', 'ja', 'zh')
 * @returns Optimal number of words per subtitle chunk
 */
const getOptimalChunkSize = (lang: string): number => {
  const langSettings: { [key: string]: number } = {
    en: 7, // English - standard
    de: 5, // German - longer words
    ja: 12, // Japanese - character-based
    zh: 12, // Chinese - character-based
    ko: 10, // Korean - character-based
    it: 6, // Italian
    fr: 6, // French
    es: 6, // Spanish
    ru: 5, // Russian - longer words
  };

  return langSettings[lang.toLowerCase()] || 6; // Default to 6 words
};

/**
 * Breaks text into natural language chunks for subtitles
 * Respects sentence boundaries, clause boundaries, and word limits
 * @param text - Text to break into chunks
 * @param maxWordsPerChunk - Maximum words per chunk
 * @returns Array of text chunks
 */
const breakText = (text: string, maxWordsPerChunk: number): string[] => {
  if (text.length <= 42) {
    // Short text - no need to break
    return [text];
  }

  // Try to break at sentence boundaries first
  const sentenceBreaks = text.match(/[.!?]+(?=\s|$)/g);
  if (sentenceBreaks && sentenceBreaks.length > 1) {
    // Multiple sentences - break at sentence boundaries
    return text
      .split(/(?<=[.!?])\s+/g)
      .filter((s) => s.trim().length > 0);
  }

  // Try to break at clause boundaries
  const clauseMatches = text.match(/[,;:]+(?=\s|$)/g);
  if (clauseMatches && clauseMatches.length > 0) {
    // Break at clauses
    return text.split(/(?<=[,;:])\s+/g).filter((s) => s.trim().length > 0);
  }

  // Last resort: break by word count
  const words = text.split(" ");
  const chunks = [];

  for (let i = 0; i < words.length; i += maxWordsPerChunk) {
    chunks.push(words.slice(i, i + maxWordsPerChunk).join(" "));
  }

  return chunks;
};

/**
 * Generates WebVTT content from transcript segments
 * @param segments - Array of subtitle segments
 * @param useTranslation - Whether to use translation instead of original text
 * @param language - Language code for optimizing chunking (default: 'en')
 * @returns WebVTT formatted string
 */
export const generateWebVTT = (
  segments: SubtitleSegment[],
  useTranslation: boolean = false,
  language: string = "en"
): string => {
  let vttContent = "WEBVTT\n\n";

  // Base chunk size on language
  const maxWordsPerChunk = getOptimalChunkSize(language);

  segments.forEach((segment, index) => {
    // Convert HH:MM:SS format to HH:MM:SS.000 (WebVTT requires milliseconds)
    const startTime = segment.start_time.includes(".")
      ? segment.start_time
      : `${segment.start_time}.000`;

    const endTime = segment.end_time.includes(".")
      ? segment.end_time
      : `${segment.end_time}.000`;

    // Use translation if available and requested
    const text =
      useTranslation && segment.translation
        ? segment.translation
        : segment.text;

    // Smart chunking based on:
    // 1. Respect sentence boundaries (., ?, !)
    // 2. Respect clause boundaries (,, :, ;)
    // 3. Keep important phrases together
    const textChunks = breakText(text, maxWordsPerChunk);

    // If only one chunk, display as is
    if (textChunks.length === 1) {
      vttContent += `${index + 1}\n`;
      vttContent += `${startTime} --> ${endTime}\n`;
      vttContent += `${text}\n\n`;
    } else {
      // Multiple chunks - distribute timing
      const segmentDurationMs = timeToMs(endTime) - timeToMs(startTime);
      const msPerChunk = segmentDurationMs / textChunks.length;

      textChunks.forEach((chunk, chunkIndex) => {
        const chunkStartMs = timeToMs(startTime) + chunkIndex * msPerChunk;
        const chunkEndMs =
          chunkIndex === textChunks.length - 1
            ? timeToMs(endTime) // Last chunk ends at segment end
            : chunkStartMs + msPerChunk;

        vttContent += `${index + 1}.${chunkIndex + 1}\n`;
        vttContent += `${msToTime(chunkStartMs)} --> ${msToTime(
          chunkEndMs
        )}\n`;
        vttContent += `${chunk}\n\n`;
      });
    }
  });

  return vttContent;
};

/**
 * Custom subtitle styles for WebVTT
 */
export const subtitleStyles = `
::cue {
  background-color: rgba(0, 0, 0, 0.75);
  color: white;
  font-family: sans-serif;
  font-size: 1em;
  line-height: 1.4;
  text-shadow: 0px 1px 2px rgba(0, 0, 0, 0.8);
  padding: 0.2em 0.5em;
  border-radius: 0.2em;
  white-space: pre-line;
}
`;
