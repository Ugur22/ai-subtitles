/**
 * useSubtitles - Custom hook for managing video subtitles
 * Handles subtitle generation, track management, and visibility
 */

import { useState, useEffect } from "react";
import { generateWebVTT, subtitleStyles } from "../utils/subtitle";
import type { TranscriptionResponse } from "../services/api";

interface UseSubtitlesOptions {
  transcription: TranscriptionResponse | null;
  videoRef: HTMLVideoElement | null;
  showTranslation: boolean;
}

export const useSubtitles = (options: UseSubtitlesOptions) => {
  const { transcription, videoRef, showTranslation } = options;

  const [showSubtitles, setShowSubtitles] = useState(true);
  const [subtitleTrackUrl, setSubtitleTrackUrl] = useState<string | null>(null);
  const [translatedSubtitleUrl, setTranslatedSubtitleUrl] = useState<string | null>(null);

  // Create and add subtitles to video
  const createSubtitleTracks = () => {
    if (!transcription) return;

    try {
      // Generate original language WebVTT
      const vttContent = generateWebVTT(
        transcription.transcription.segments,
        false,
        transcription.transcription.language || "en"
      );
      const vttBlob = new Blob([vttContent], { type: "text/vtt" });
      const vttUrl = URL.createObjectURL(vttBlob);
      setSubtitleTrackUrl(vttUrl);

      // Generate translated WebVTT if translations are available
      const hasTranslations = transcription.transcription.segments.some(
        (segment) => segment.translation
      );

      if (hasTranslations) {
        const translatedVttContent = generateWebVTT(
          transcription.transcription.segments,
          true,
          transcription.transcription.language || "en"
        );
        const translatedVttBlob = new Blob([translatedVttContent], {
          type: "text/vtt",
        });
        const translatedVttUrl = URL.createObjectURL(translatedVttBlob);
        setTranslatedSubtitleUrl(translatedVttUrl);
      }
    } catch (error) {
      console.error("Error creating subtitles:", error);
    }
  };

  // Create subtitles when transcription is available
  useEffect(() => {
    if (transcription) {
      createSubtitleTracks();

      // Add custom subtitle styles to document head
      const styleElement = document.createElement("style");
      styleElement.innerHTML = subtitleStyles;
      document.head.appendChild(styleElement);

      return () => {
        if (subtitleTrackUrl) {
          URL.revokeObjectURL(subtitleTrackUrl);
        }
        if (translatedSubtitleUrl) {
          URL.revokeObjectURL(translatedSubtitleUrl);
        }
        // Remove custom styles when component unmounts
        document.head.removeChild(styleElement);
      };
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [transcription]);

  // Update subtitles when translation toggle changes
  useEffect(() => {
    if (videoRef) {
      const trackElements = videoRef.textTracks;

      if (trackElements.length > 0) {
        // Hide all tracks first
        for (let i = 0; i < trackElements.length; i++) {
          trackElements[i].mode = "hidden";
        }

        // Show the active track if subtitles are enabled
        if (showSubtitles) {
          const trackIndex =
            showTranslation && trackElements.length > 1 ? 1 : 0;
          trackElements[trackIndex].mode = "showing";
        }
      }
    }
  }, [showTranslation, showSubtitles, videoRef]);

  const toggleSubtitles = () => {
    setShowSubtitles(!showSubtitles);
  };

  return {
    showSubtitles,
    subtitleTrackUrl,
    translatedSubtitleUrl,
    toggleSubtitles,
    createSubtitleTracks,
  };
};
