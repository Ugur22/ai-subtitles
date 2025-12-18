/**
 * useVideoPlayer - Custom hook for managing video player state and controls
 * Handles playback, volume, seeking, and keyboard shortcuts
 */

import { useState, useEffect, useCallback, useRef } from "react";

interface UseVideoPlayerOptions {
  onJumpToTimeRequest?: () => void;
}

export const useVideoPlayer = (options: UseVideoPlayerOptions = {}) => {
  const { onJumpToTimeRequest } = options;

  const videoRefInternal = useRef<HTMLVideoElement | null>(null);
  const [videoRef, setVideoRefState] = useState<HTMLVideoElement | null>(null);

  // Use a stable callback ref to avoid re-renders when the video element mounts
  const setVideoRef = useCallback((element: HTMLVideoElement | null) => {
    videoRefInternal.current = element;
    // Only update state if the element actually changed
    setVideoRefState((prev) => {
      if (prev !== element) {
        return element;
      }
      return prev;
    });
  }, []);
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
      const video = videoRefInternal.current;
      if (!video) return;

      // Ctrl+J to open Jump to Time
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "j") {
        e.preventDefault();
        onJumpToTimeRequest?.();
        return;
      }

      switch (e.key) {
        case "ArrowRight":
          e.preventDefault();
          video.currentTime = Math.min(
            video.duration,
            video.currentTime + 5
          );
          break;
        case "ArrowLeft":
          e.preventDefault();
          video.currentTime = Math.max(0, video.currentTime - 5);
          break;
        // Removed 'P' key shortcut - was interfering with typing
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onJumpToTimeRequest]);

  const handlePlayPause = useCallback(() => {
    const video = videoRefInternal.current;
    if (video) {
      if (video.paused) {
        video.play();
      } else {
        video.pause();
      }
    }
  }, []);

  const handleVolumeChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const newVolume = parseFloat(e.target.value);
      setVolume(newVolume);
      const video = videoRefInternal.current;
      if (video) {
        video.volume = newVolume;
      }
    },
    []
  );

  const seek = useCallback(
    (seconds: number) => {
      const video = videoRefInternal.current;
      if (video) {
        video.currentTime = seconds;
      }
    },
    []
  );

  const play = useCallback(() => {
    const video = videoRefInternal.current;
    if (video) {
      video.play().catch((err) => console.error("Error playing video:", err));
    }
  }, []);

  const pause = useCallback(() => {
    const video = videoRefInternal.current;
    if (video) {
      video.pause();
    }
  }, []);

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
