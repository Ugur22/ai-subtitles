/**
 * useVideoPlayer - Custom hook for managing video player state and controls
 * Handles playback, volume, seeking, and keyboard shortcuts
 */

import { useState, useEffect, useCallback } from "react";

interface UseVideoPlayerOptions {
  onJumpToTimeRequest?: () => void;
}

export const useVideoPlayer = (options: UseVideoPlayerOptions = {}) => {
  const { onJumpToTimeRequest } = options;

  const [videoRef, setVideoRef] = useState<HTMLVideoElement | null>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [volume, setVolume] = useState(1);
  const [isVideoSeeking, setIsVideoSeeking] = useState(false);

  // Update current time when video plays
  useEffect(() => {
    if (!videoRef) return;

    const handleTimeUpdate = () => {
      if (!isVideoSeeking) {
        setCurrentTime(videoRef.currentTime);
      }
    };

    videoRef.addEventListener("timeupdate", handleTimeUpdate);
    return () => {
      videoRef.removeEventListener("timeupdate", handleTimeUpdate);
    };
  }, [videoRef, isVideoSeeking]);

  // Track play/pause state
  useEffect(() => {
    if (!videoRef) return;

    const handlePlay = () => setIsPlaying(true);
    const handlePause = () => setIsPlaying(false);

    videoRef.addEventListener("play", handlePlay);
    videoRef.addEventListener("pause", handlePause);

    return () => {
      videoRef.removeEventListener("play", handlePlay);
      videoRef.removeEventListener("pause", handlePause);
    };
  }, [videoRef]);

  // Track seeking state
  useEffect(() => {
    if (!videoRef) return;

    const handleSeeking = () => setIsVideoSeeking(true);
    const handleSeeked = () => setIsVideoSeeking(false);

    videoRef.addEventListener("seeking", handleSeeking);
    videoRef.addEventListener("seeked", handleSeeked);

    return () => {
      videoRef.removeEventListener("seeking", handleSeeking);
      videoRef.removeEventListener("seeked", handleSeeked);
    };
  }, [videoRef]);

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (!videoRef) return;

      // Ctrl+J to open Jump to Time
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "j") {
        e.preventDefault();
        onJumpToTimeRequest?.();
        return;
      }

      switch (e.key) {
        case "ArrowRight":
          e.preventDefault();
          videoRef.currentTime = Math.min(
            videoRef.duration,
            videoRef.currentTime + 5
          );
          break;
        case "ArrowLeft":
          e.preventDefault();
          videoRef.currentTime = Math.max(0, videoRef.currentTime - 5);
          break;
        case "p":
        case "P":
          e.preventDefault();
          handlePlayPause();
          break;
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [videoRef, onJumpToTimeRequest]);

  const handlePlayPause = useCallback(() => {
    if (videoRef) {
      if (videoRef.paused) {
        videoRef.play();
      } else {
        videoRef.pause();
      }
    }
  }, [videoRef]);

  const handleVolumeChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const newVolume = parseFloat(e.target.value);
      setVolume(newVolume);
      if (videoRef) {
        videoRef.volume = newVolume;
      }
    },
    [videoRef]
  );

  const seek = useCallback(
    (seconds: number) => {
      if (videoRef) {
        videoRef.currentTime = seconds;
      }
    },
    [videoRef]
  );

  const play = useCallback(() => {
    if (videoRef) {
      videoRef.play().catch((err) => console.error("Error playing video:", err));
    }
  }, [videoRef]);

  const pause = useCallback(() => {
    if (videoRef) {
      videoRef.pause();
    }
  }, [videoRef]);

  return {
    videoRef,
    setVideoRef,
    currentTime,
    isPlaying,
    volume,
    isVideoSeeking,
    handlePlayPause,
    handleVolumeChange,
    seek,
    play,
    pause,
  };
};
