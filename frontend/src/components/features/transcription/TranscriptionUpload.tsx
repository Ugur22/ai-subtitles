import { useState, useRef, useEffect } from "react";
import { useMutation } from "@tanstack/react-query";
import { useSpring, animated, config as springConfig } from "react-spring";
import {
  transcribeVideo,
  TranscriptionResponse,
  transcribeLocal,
  translateLocalText,
} from "../../../services/api";
import { SubtitleControls } from "./SubtitleControls";
import { SearchPanel } from "../search/SearchPanel";
import { AnalyticsPanel } from "../analytics/AnalyticsPanel";
import { SummaryPanel } from "../summary/SummaryPanel";
import { SavedTranscriptionsPanel } from "./SavedTranscriptionsPanel";
import axios from "axios";
import { FaSpinner } from "react-icons/fa";
import CustomProgressBar from "./CustomProgressBar";
import React from "react";
import { animationConfig } from "../../../utils/animations";

// Add custom subtitle styles
const subtitleStyles = `
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

type ProcessingStage =
  | "uploading"
  | "transcribing"
  | "translating"
  | "extracting"
  | "complete";

interface ProcessingStatus {
  stage: ProcessingStage;
  progress: number;
}

// Helper to format processing time for better readability
const formatProcessingTime = (timeStr?: string | null): string => {
  // Return a default value if timeStr is undefined or null
  if (!timeStr) {
    return "Unknown";
  }

  // Try to extract a numeric value from the time string
  let seconds = 0;

  // Try to parse seconds from the string
  if (timeStr.includes("seconds")) {
    seconds = parseFloat(timeStr.replace(" seconds", "").trim());
  } else {
    // If it's a number without units, assume it's seconds
    const parsed = parseFloat(timeStr);
    if (!isNaN(parsed)) {
      seconds = parsed;
    }
  }

  // If we've successfully parsed a seconds value
  if (seconds > 0) {
    if (seconds < 5) {
      // Very fast processing
      return `${seconds.toFixed(1)} seconds (super fast!)`;
    } else if (seconds < 60) {
      // Less than a minute, keep as seconds
      return `${seconds.toFixed(1)} seconds`;
    } else {
      // Convert to minutes and seconds
      const minutes = Math.floor(seconds / 60);
      const remainingSeconds = Math.round(seconds % 60);

      if (remainingSeconds === 0) {
        // Even minutes
        return minutes === 1 ? "1 minute" : `${minutes} minutes`;
      } else {
        // Minutes and seconds
        return minutes === 1
          ? `1 minute ${remainingSeconds} seconds`
          : `${minutes} minutes ${remainingSeconds} seconds`;
      }
    }
  }

  // If we couldn't parse it, return the original
  return timeStr;
};

// Function to check if a file exists using the Fetch API
const checkFileExists = async (path: string): Promise<boolean> => {
  try {
    // For local file system access, we need to use the file:// protocol
    const fileUrl = path.startsWith("/") ? `file://${path}` : path;
    const response = await fetch(fileUrl, { method: "HEAD" });
    return response.ok;
  } catch (error) {
    console.warn("Error checking if file exists:", error);
    return false;
  }
};

// Define the SummarySection interface that was in SummaryPanel.tsx
interface SummarySection {
  title: string;
  start: string;
  end: string;
  summary: string;
  screenshot_url?: string | null;
}

// Simple Image Modal Component
interface ImageModalProps {
  imageUrl: string;
  onClose: () => void;
}

const ImageModal: React.FC<ImageModalProps> = ({ imageUrl, onClose }) => {
  // Prevent closing modal when clicking on the image itself
  const handleImageClick = (e: React.MouseEvent) => {
    e.stopPropagation();
  };

  // Modal animation
  const backdropAnimation = useSpring({
    opacity: 1,
    config: animationConfig.smooth,
    from: { opacity: 0 },
  });

  const modalAnimation = useSpring({
    transform: "scale(1)",
    opacity: 1,
    config: springConfig.wobbly,
    from: { transform: "scale(0.9)", opacity: 0 },
  });

  return (
    <animated.div
      className="fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center z-50 p-4"
      style={backdropAnimation}
      onClick={onClose} // Close when clicking backdrop
    >
      <animated.div
        className="relative bg-white p-3 rounded-2xl shadow-2xl max-w-6xl max-h-[90vh]"
        style={modalAnimation}
        onClick={handleImageClick} // Prevent closing on image container click
      >
        <img
          src={imageUrl}
          alt="Enlarged screenshot"
          className="block w-[900px] max-h-[85vh] object-contain rounded-xl"
        />
        <button
          onClick={onClose}
          className="absolute -top-2 -right-2 bg-white rounded-full p-2 text-gray-700 hover:bg-gray-100 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500 shadow-lg transition-all duration-200 hover:scale-110"
          aria-label="Close image modal"
        >
          <svg
            className="w-5 h-5"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth="2"
              d="M6 18L18 6M6 6l12 12"
            />
          </svg>
        </button>
      </animated.div>
    </animated.div>
  );
};

// Add transcription method type
type TranscriptionMethod = "local";
type TranslationMethod = "none" | "marianmt";

// --- Add JumpToTimeModal component ---
interface JumpToTimeModalProps {
  isOpen: boolean;
  onClose: () => void;
  onJump: (seconds: number) => void;
  duration: number;
  currentTime: number;
  inputRef?: React.RefObject<HTMLInputElement>; // new prop
}

const secondsToTimeString = (seconds: number): string => {
  if (isNaN(seconds) || seconds < 0) return "";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) {
    return `${h.toString().padStart(2, "0")}:${m
      .toString()
      .padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
  } else {
    return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
  }
};

const JumpToTimeModal: React.FC<JumpToTimeModalProps> = ({
  isOpen,
  onClose,
  onJump,
  duration,
  currentTime,
  inputRef,
}) => {
  const localInputRef = useRef<HTMLInputElement>(null);
  const [input, setInput] = useState("");
  const [error, setError] = useState("");

  // Correctly place parseTimeInput here
  const parseTimeInput = (input: string): number | null => {
    const parts = input
      .trim()
      .split(":")
      .map((p) => p.trim());
    if (parts.length === 0) return null;
    let seconds = 0;
    if (parts.length === 3) {
      seconds =
        parseFloat(parts[0]) * 3600 +
        parseFloat(parts[1]) * 60 +
        parseFloat(parts[2]);
    } else if (parts.length === 2) {
      seconds = parseFloat(parts[0]) * 60 + parseFloat(parts[1]);
    } else if (parts.length === 1) {
      seconds = parseFloat(parts[0]);
    } else {
      return null;
    }
    return isNaN(seconds) ? null : seconds;
  };

  useEffect(() => {
    if (isOpen) {
      setInput(secondsToTimeString(currentTime));
      setError("");
      setTimeout(() => {
        (inputRef?.current || localInputRef.current)?.focus();
      }, 0);
    }
  }, [isOpen, currentTime, inputRef]);

  const handleOk = () => {
    const seconds = parseTimeInput(input);
    if (seconds === null || seconds < 0 || seconds > duration) {
      setError(
        "Invalid time. Please enter a value between 0 and the video duration."
      );
      return;
    }
    setError("");
    onJump(seconds);
    onClose();
  };

  if (!isOpen) return null;

  // Modal animation
  const backdropAnimation = useSpring({
    opacity: 1,
    config: animationConfig.smooth,
    from: { opacity: 0 },
  });

  const modalAnimation = useSpring({
    transform: "scale(1)",
    opacity: 1,
    config: springConfig.wobbly,
    from: { transform: "scale(0.85)", opacity: 0 },
  });

  return (
    <animated.div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm"
      style={backdropAnimation}
    >
      <animated.div
        className="bg-white rounded-2xl shadow-2xl p-8 w-full max-w-md flex flex-col items-center"
        style={modalAnimation}
      >
        <div className="mb-6 flex flex-col items-center">
          <div className="w-16 h-16 mb-4 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-2xl flex items-center justify-center shadow-lg">
            <svg
              className="w-8 h-8 text-white"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M10 9V5a1 1 0 011-1h2a1 1 0 011 1v4m-1 4h.01M12 17h.01"
              />
              <polygon points="8,17 16,12 8,7" fill="currentColor" />
            </svg>
          </div>
          <h2 className="text-2xl font-bold mb-2 text-gray-900">
            Jump to Time
          </h2>
          <p className="text-sm text-gray-600 text-center leading-relaxed">
            Enter the time you want to jump to in the video.
            <br />
            <span className="text-indigo-600 font-medium">
              Example: 20:35 or 1:30:45
            </span>
          </p>
        </div>
        <input
          ref={inputRef || localInputRef}
          className="w-full border-2 border-gray-200 rounded-xl px-4 py-3 mb-3 text-center text-lg font-mono focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all duration-200"
          placeholder="mm:ss or hh:mm:ss"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          autoFocus
        />
        {error && (
          <div className="text-sm text-red-500 mb-4 p-3 bg-red-50 rounded-lg border border-red-200">
            {error}
          </div>
        )}
        <div className="flex w-full gap-3 mt-4">
          <button
            className="flex-1 py-3 rounded-xl bg-gray-100 text-gray-700 font-semibold hover:bg-gray-200 transition-all duration-200 hover:scale-105"
            onClick={onClose}
          >
            Cancel
          </button>
          <button
            className="flex-1 py-3 rounded-xl bg-blue-600 text-white font-semibold hover:bg-blue-700 transition-all duration-200 hover:scale-105"
            onClick={handleOk}
          >
            Jump
          </button>
        </div>
      </animated.div>
    </animated.div>
  );
};

type TranscriptionUploadProps = {
  onTranscriptionChange?: (transcription: TranscriptionResponse | null) => void;
};

export const TranscriptionUpload: React.FC<TranscriptionUploadProps> = ({
  onTranscriptionChange,
}) => {
  const [uploadProgress, setUploadProgress] = useState(0);
  const [transcription, setTranscription] =
    useState<TranscriptionResponse | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [showTranslation, setShowTranslation] = useState(false);
  const [showSummary, setShowSummary] = useState(false);
  const [showSearch, setShowSearch] = useState(true);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [processingStatus, setProcessingStatus] =
    useState<ProcessingStatus | null>(null);
  const [hideProgressBar, setHideProgressBar] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const playerRef = useRef<any>(null);
  const [file, setFile] = useState<File | null>(null);
  const [videoRef, setVideoRef] = useState<HTMLVideoElement | null>(null);
  const [showSubtitles, setShowSubtitles] = useState(true);
  const [subtitleTrackUrl, setSubtitleTrackUrl] = useState<string | null>(null);
  const [translatedSubtitleUrl, setTranslatedSubtitleUrl] = useState<
    string | null
  >(null);
  const [progressSimulation, setProgressSimulation] =
    useState<NodeJS.Timeout | null>(null);
  const [activeSegmentId, setActiveSegmentId] = useState<string | null>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [elapsedTime, setElapsedTime] = useState(0);
  const [processingTimer, setProcessingTimer] = useState<NodeJS.Timeout | null>(
    null
  );
  const [showProgressBar, setShowProgressBar] = useState(false);
  const [isNewTranscription, setIsNewTranscription] = useState(false);
  const [showSavedTranscriptions, setShowSavedTranscriptions] = useState(false);
  const [summaries, setSummaries] = useState<SummarySection[]>([]);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [selectedLanguage, setSelectedLanguage] = useState<string>("");
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [modalImageUrl, setModalImageUrl] = useState<string | null>(null);
  const [transcriptionMethod, setTranscriptionMethod] =
    useState<TranscriptionMethod>("local");
  const [isVideoSeeking, setIsVideoSeeking] = useState(false);
  const [isPolling, setIsPolling] = useState(false);
  const pollingIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const [translationMethod, setTranslationMethod] =
    useState<TranslationMethod>("none");
  const [jumpModalOpen, setJumpModalOpen] = useState(false);
  const [isPlaying, setIsPlaying] = useState(false);
  const [isVideoHovered, setIsVideoHovered] = useState(false);
  const [volume, setVolume] = useState(1);
  const [showScreenshots, setShowScreenshots] = useState(false);
  const [hoveredSegmentId, setHoveredSegmentId] = useState<string | null>(null);

  const transcribeMutation = useMutation({
    mutationFn: transcribeVideo,
    onMutate: () => {
      // Reset the flag when starting a new transcription
      setIsNewTranscription(false);

      // Show progress bar when starting a new transcription
      setHideProgressBar(false);

      // Start with uploading status
      setProcessingStatus({ stage: "uploading", progress: 0 });

      // Start the timer for elapsed time
      if (processingTimer) {
        clearInterval(processingTimer);
      }

      setElapsedTime(0);
      const timer = setInterval(() => {
        setElapsedTime((prev) => prev + 1);
      }, 1000);

      setProcessingTimer(timer);
    },
    onSuccess: (data) => {
      // Clear simulation on success
      if (progressSimulation) {
        clearInterval(progressSimulation);
        setProgressSimulation(null);
      }

      // Clear processing timer
      if (processingTimer) {
        clearInterval(processingTimer);
        setProcessingTimer(null);
      }

      setTranscription(data);
      setProcessingStatus({ stage: "complete", progress: 100 });
      setError(null);
    },
    onError: (error) => {
      // Clear simulation on error
      if (progressSimulation) {
        clearInterval(progressSimulation);
        setProgressSimulation(null);
      }

      // Clear processing timer
      if (processingTimer) {
        clearInterval(processingTimer);
        setProcessingTimer(null);
      }

      console.error("Transcription error:", error);
      setError("Failed to transcribe the file. Please try again.");
      setProcessingStatus({ stage: "uploading", progress: 0 });
    },
  });

  // Clean up object URL when component unmounts or videoUrl changes
  useEffect(() => {
    return () => {
      if (videoUrl) {
        URL.revokeObjectURL(videoUrl);
      }
    };
  }, [videoUrl]);

  // Cleanup function for progress simulation
  useEffect(() => {
    return () => {
      if (progressSimulation) {
        clearInterval(progressSimulation);
      }
    };
  }, [progressSimulation]);

  // Add time update handler to track current video position
  useEffect(() => {
    if (videoRef) {
      const handleTimeUpdate = () => {
        setCurrentTime(videoRef.currentTime);

        // Find the currently active segment based on video time
        if (transcription) {
          const currentSegment = transcription.transcription.segments.find(
            (segment) => {
              const startSeconds = convertTimeToSeconds(segment.start_time);
              const endSeconds = convertTimeToSeconds(segment.end_time);
              return (
                videoRef.currentTime >= startSeconds &&
                videoRef.currentTime <= endSeconds
              );
            }
          );

          setActiveSegmentId(currentSegment?.id ?? null);
        }
      };

      videoRef.addEventListener("timeupdate", handleTimeUpdate);

      return () => {
        videoRef.removeEventListener("timeupdate", handleTimeUpdate);
      };
    }
  }, [videoRef, transcription]);

  // Helper to convert HH:MM:SS to seconds
  const convertTimeToSeconds = (timeString: string): number => {
    const [hours, minutes, seconds] = timeString.split(":").map(Number);
    return hours * 3600 + minutes * 60 + seconds;
  };

  const handleLanguageChange = (
    event: React.ChangeEvent<HTMLSelectElement>
  ) => {
    setSelectedLanguage(event.target.value);
  };

  const handleFileChange = async (
    event: React.ChangeEvent<HTMLInputElement>
  ) => {
    const selectedFile = event.target.files?.[0];
    if (selectedFile) {
      setFile(selectedFile);
      // Create URL for video preview if it's a video file
      if (selectedFile.type.startsWith("video/")) {
        const url = URL.createObjectURL(selectedFile);
        setVideoUrl(url);
      } else {
        setVideoUrl(null); // Clear video URL for non-video files
      }
      // Don't start processing immediately
      // await processFile(file);
      // Reset any previous errors or results
      setError(null);
      setTranscription(null);
      setProcessingStatus(null);
      setElapsedTime(0);
      if (processingTimer) clearInterval(processingTimer);
    }
  };

  const processFile = async (fileToProcess: File) => {
    try {
      setProcessingStatus({ stage: "uploading", progress: 0 });
      setError(null);

      // Choose transcription method based on user selection
      const transcriptionResult = await (transcriptionMethod === "local"
        ? transcribeLocal(fileToProcess)
        : transcribeVideo({ file: fileToProcess, language: selectedLanguage }));

      setTranscription(transcriptionResult);
      setProcessingStatus({ stage: "complete", progress: 100 });
    } catch (error) {
      setError(
        error instanceof Error
          ? error.message
          : "An error occurred during transcription"
      );
      setProcessingStatus({ stage: "complete", progress: 0 });
    }
  };

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  };

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);

    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      const droppedFile = e.dataTransfer.files[0];
      setFile(droppedFile);

      // Create and store video URL for dropped file if it's a video
      if (droppedFile.type.startsWith("video/")) {
        const objectUrl = URL.createObjectURL(droppedFile);
        setVideoUrl(objectUrl);
      } else {
        setVideoUrl(null);
      }

      // Don't start processing immediately
      // try {
      //   await processFile(file);
      // } catch (error) {
      //   console.error('Processing failed:', error);
      // }
      // Reset any previous errors or results
      setError(null);
      setTranscription(null);
      setProcessingStatus(null);
      setElapsedTime(0);
      if (processingTimer) clearInterval(processingTimer);
    }
  };

  const handleButtonClick = () => {
    fileInputRef.current?.click();
  };

  // Function to start polling for transcription completion
  const startPollingForTranscription = (videoHash: string) => {
    setIsPolling(true);
    setProcessingStatus({ stage: "transcribing", progress: 0 });

    if (pollingIntervalRef.current) {
      clearInterval(pollingIntervalRef.current);
    }

    pollingIntervalRef.current = setInterval(async () => {
      try {
        const response = await axios.get(
          `http://localhost:8000/transcription/${videoHash}`
        );
        if (
          response.data &&
          response.data.transcription &&
          response.data.transcription.segments.length > 0
        ) {
          setTranscription(response.data);
          setProcessingStatus({ stage: "complete", progress: 100 });
          setIsPolling(false);
          if (pollingIntervalRef.current) {
            clearInterval(pollingIntervalRef.current);
          }
        }
      } catch (error) {
        // Optionally handle error or show a message
      }
    }, 3000); // Poll every 3 seconds
  };

  // Clean up polling interval on unmount
  useEffect(() => {
    return () => {
      if (pollingIntervalRef.current) {
        clearInterval(pollingIntervalRef.current);
      }
    };
  }, []);

  // Update handleStartTranscriptionClick to use polling
  const handleStartTranscriptionClick = async () => {
    if (file) {
      setProcessingStatus({ stage: "transcribing", progress: 0 });
      setError(null);
      try {
        let result;
        if (transcriptionMethod === "local") {
          console.log("Calling transcribeLocal()");
          result = await transcribeLocal(file);
        } else {
          console.log("Calling transcribeVideo()");
          result = await transcribeVideo({ file, language: selectedLanguage });
        }
        // Start polling for completion using video_hash
        if (result && result.video_hash) {
          startPollingForTranscription(result.video_hash);
        } else {
          setError("Failed to start transcription: Missing video identifier.");
        }
      } catch (error) {
        setError(
          error instanceof Error
            ? error.message
            : "An error occurred during transcription"
        );
        setProcessingStatus({ stage: "complete", progress: 0 });
      }
    } else {
      setError("No file selected to transcribe.");
    }
  };

  const startNewTranscription = () => {
    // Set flag to hide progress bar
    setIsNewTranscription(true);

    setTranscription(null);
    setVideoUrl(null);
    setFile(null);
    setShowTranslation(false);
    setShowSubtitles(false);
    setUploadProgress(0);
    setElapsedTime(0);
    setSelectedLanguage("");

    if (processingTimer) {
      clearInterval(processingTimer);
      setProcessingTimer(null);
    }

    setTimeout(() => {
      setShowSubtitles(true);
    }, 500);
  };

  // Function to delete previous screenshots
  const cleanupPreviousScreenshots = async () => {
    try {
      await axios.post("http://localhost:8000/cleanup_screenshots/");
      console.log("Previous screenshots cleaned up successfully");
    } catch (error) {
      console.error("Failed to cleanup screenshots:", error);
      // Non-critical error, don't show to user
    }
  };

  const seekToTimestamp = (timeString: string) => {
    console.log("Seeking to timestamp:", timeString, "videoRef:", videoRef);
    if (!videoRef) {
      console.error("Video reference not available");
      return;
    }
    if (!timeString) {
      console.error("Time string is empty");
      return;
    }

    const seconds = timeToSeconds(timeString);
    console.log("Converted to seconds:", seconds);
    videoRef.currentTime = seconds;
    videoRef
      .play()
      .catch((err: Error) => console.error("Error playing video:", err));

    // Find the corresponding segment in the transcript
    if (transcription && transcription.transcription.segments) {
      const segments = transcription.transcription.segments;
      const matchingSegmentIndex = segments.findIndex((segment) => {
        const segmentStartSeconds = timeToSeconds(segment.start_time);
        const segmentEndSeconds = timeToSeconds(segment.end_time);
        return seconds >= segmentStartSeconds && seconds <= segmentEndSeconds;
      });

      // If a matching segment is found, scroll to it
      if (matchingSegmentIndex !== -1) {
        const matchingSegment = segments[matchingSegmentIndex];
        setActiveSegmentId(matchingSegment.id);

        // Use setTimeout to ensure the DOM has updated with the active segment
        setTimeout(() => {
          const segmentElement = document.getElementById(
            `transcript-segment-${matchingSegment.id}`
          );
          if (segmentElement) {
            // Find the scrollable container instead of scrolling the whole page
            const transcriptContainer = document.querySelector(
              ".flex-grow.overflow-auto"
            );
            if (transcriptContainer) {
              // Calculate position relative to the container
              const containerRect = transcriptContainer.getBoundingClientRect();
              const elementRect = segmentElement.getBoundingClientRect();
              const relativeTop = elementRect.top - containerRect.top;

              // Scroll the container, not the element
              transcriptContainer.scrollTo({
                top: transcriptContainer.scrollTop + relativeTop - 100, // 100px from top for better visibility
                behavior: "smooth",
              });
            } else {
              // Fallback to the previous behavior
              segmentElement.scrollIntoView({
                behavior: "smooth",
                block: "center",
              });
            }
          }
        }, 100);
      }
    }
  };

  const handleSummaryClick = () => {
    setShowSearch(false);
    setShowSavedTranscriptions(false);
    setShowSummary(!showSummary);
  };

  const handleSearchClick = () => {
    setShowSearch(!showSearch);
  };

  const handleSavedTranscriptionsClick = () => {
    setShowSavedTranscriptions(!showSavedTranscriptions);
  };

  // Handle when a saved transcription is loaded
  const handleTranscriptionLoaded = async (videoHash?: string) => {
    try {
      let data;
      if (videoHash) {
        // Load a specific saved transcription
        const response = await axios.get(
          `http://localhost:8000/transcription/${videoHash}`
        );
        data = response.data;
      } else {
        // Load the current transcription
        const response = await axios.get(
          "http://localhost:8000/current_transcription/"
        );
        data = response.data;
      }
      console.log("Loaded transcription data:", data);
      // No translation logic needed, just set the transcription
      setTranscription(data);
      setFile(null);
      setProcessingStatus({ stage: "complete", progress: 100 });
      setShowSavedTranscriptions(false);
      setSummaries([]);
      if (data.video_hash) {
        const videoPath = `http://localhost:8000/video/${data.video_hash}`;
        setVideoUrl(videoPath);
      } else if (data.file_path) {
        const pathParts = data.file_path.split("/");
        const fileName = pathParts[pathParts.length - 1];
        const hashMatch = fileName.match(/^([a-f0-9]+)\./i);
        if (hashMatch && hashMatch[1]) {
          const extractedHash = hashMatch[1];
          const videoPath = `http://localhost:8000/video/${extractedHash}`;
          setVideoUrl(videoPath);
        } else {
          setError("Could not load video: Missing video identifier");
        }
      } else {
        setError("Could not load video: Missing file information");
      }
    } catch (error) {
      console.error("Error loading transcription:", error);
      setError("Failed to load the transcription. Please try again.");
    }
  };

  // Generate WebVTT content from transcript segments
  const generateWebVTT = (
    segments: any[],
    useTranslation: boolean = false
  ): string => {
    let vttContent = "WEBVTT\n\n";

    // Get language to optimize chunking
    const language = transcription?.transcription.language || "en";

    // Determine optimal chunk size based on language complexity
    // Some languages are more information-dense and need fewer words per line
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

      // Split into natural language chunks
      const breakText = (text: string): string[] => {
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
          return text
            .split(/(?<=[,;:])\s+/g)
            .filter((s) => s.trim().length > 0);
        }

        // Last resort: break by word count
        const words = text.split(" ");
        const chunks = [];

        for (let i = 0; i < words.length; i += maxWordsPerChunk) {
          chunks.push(words.slice(i, i + maxWordsPerChunk).join(" "));
        }

        return chunks;
      };

      const textChunks = breakText(text);

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

  // Helper function to convert HH:MM:SS.mmm to milliseconds
  const timeToMs = (timeString: string): number => {
    const [time, ms = "0"] = timeString.split(".");
    const [hours, minutes, seconds] = time.split(":").map(Number);

    return (
      (hours * 3600 + minutes * 60 + seconds) * 1000 +
      parseInt(ms.padEnd(3, "0").substring(0, 3))
    );
  };

  // Helper function to convert milliseconds to HH:MM:SS.mmm format
  const msToTime = (ms: number): string => {
    const totalSeconds = Math.floor(ms / 1000);
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    const milliseconds = ms % 1000;

    return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(
      2,
      "0"
    )}:${String(seconds).padStart(2, "0")}.${String(milliseconds).padStart(
      3,
      "0"
    )}`;
  };

  // Create and add subtitles to video
  const createSubtitleTracks = () => {
    if (!transcription) return;

    try {
      // Generate original language WebVTT
      const vttContent = generateWebVTT(transcription.transcription.segments);
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
          true
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

  // Toggle subtitles visibility
  const toggleSubtitles = () => {
    setShowSubtitles(!showSubtitles);
  };

  // Cleanup function for timers when component unmounts
  useEffect(() => {
    return () => {
      if (progressSimulation) {
        clearInterval(progressSimulation);
      }
      if (processingTimer) {
        clearInterval(processingTimer);
      }
    };
  }, [progressSimulation, processingTimer]);

  // Update the handle functions for processing status to handle null
  const updateUploadProgress = (progress: number) => {
    setUploadProgress(progress);
    setProcessingStatus((prevStatus) =>
      prevStatus
        ? {
            ...prevStatus,
            progress: Math.min(99, progress),
          }
        : { stage: "uploading", progress: Math.min(99, progress) }
    );
  };

  const handleExtractingAudio = () => {
    setProcessingStatus((prevStatus) =>
      prevStatus
        ? {
            ...prevStatus,
            stage: "extracting",
            progress: 0,
          }
        : { stage: "extracting", progress: 0 }
    );
  };

  const handleTranscribing = () => {
    setProcessingStatus((prevStatus) =>
      prevStatus
        ? {
            ...prevStatus,
            stage: "transcribing",
            progress: 0,
          }
        : { stage: "transcribing", progress: 0 }
    );
  };

  // Function to fetch the current transcription data from the backend
  const fetchCurrentTranscription =
    async (): Promise<TranscriptionResponse | null> => {
      try {
        const response = await fetch(
          "http://localhost:8000/current_transcription/"
        );

        if (!response.ok) {
          console.error(
            "Failed to fetch current transcription",
            response.statusText
          );
          return null;
        }

        const data = await response.json();
        setTranscription(data);
        // Reset summaries when loading a new transcription to prevent showing summaries from previous videos
        setSummaries([]);
        setProcessingStatus({ stage: "complete", progress: 100 });

        // Set video URL if video_hash is available
        if (data.video_hash) {
          const videoPath = `http://localhost:8000/video/${data.video_hash}`;
          console.log(
            "Setting video URL from current transcription:",
            videoPath
          );
          setVideoUrl(videoPath);
        }

        return data;
      } catch (error) {
        console.error("Error fetching current transcription:", error);
        return null;
      }
    };

  // Add a function to generate summaries here (moved from SummaryPanel)
  const generateSummaries = async () => {
    setSummaryLoading(true);
    try {
      console.log("Generating summaries...");
      const response = await axios.post(
        "http://localhost:8000/generate_summary/"
      );
      console.log("Summary response:", response.data);

      const summaryData = response.data.summaries || [];
      const responseFilename = response.data.filename;

      // More detailed logging to debug the issue
      console.log("Current transcription:", transcription?.filename);
      console.log("Response filename:", responseFilename);

      // Only perform the filename check if both filenames are defined and don't match
      // This ensures we still show summaries even if one of the filenames is undefined
      if (
        transcription &&
        responseFilename &&
        transcription.filename &&
        responseFilename !== transcription.filename
      ) {
        console.warn(
          "Summary filename mismatch:",
          responseFilename,
          "vs",
          transcription.filename
        );
        // Continue anyway - don't return early
      }

      console.log("Received summary data:", summaryData);

      if (!summaryData || summaryData.length === 0) {
        console.warn("No summary data received");
        setSummaryLoading(false);
        return;
      }

      console.log("Now fetching screenshots for summaries...");

      // First set the basic summaries without screenshots
      setSummaries(summaryData);

      // Then try to enhance them with screenshots
      try {
        const enhancedSummaries = await fetchScreenshotsForSummaries(
          summaryData
        );
        console.log("Final enhanced summaries:", enhancedSummaries);
        setSummaries(enhancedSummaries);
      } catch (screenshotError) {
        console.error(
          "Error adding screenshots to summaries:",
          screenshotError
        );
        // We still have the basic summaries displayed
      }
    } catch (error) {
      console.error("Error generating summaries:", error);
      // Handle error (you can add error state if needed)
    } finally {
      setSummaryLoading(false);
    }
  };

  // Add the helper function to fetch screenshots (moved from SummaryPanel)
  const fetchScreenshotsForSummaries = async (
    summaryData: SummarySection[]
  ) => {
    try {
      // Get the current transcription data
      const response = await axios.get(
        "http://localhost:8000/current_transcription/"
      );

      if (response.status !== 200) {
        console.error(`Error fetching transcription data: ${response.status}`);
        return summaryData;
      }

      const segments = response.data.transcription.segments;

      console.log("Fetched transcription data successfully");
      console.log(
        "Number of segments with screenshots:",
        segments.filter((s: any) => s.screenshot_url).length
      );

      // Match summary sections with segment screenshots
      const enhancedSummaries = summaryData.map((summary: SummarySection) => {
        // Find the best matching segment for this summary
        // Strategy 1: Find a segment that's very close to the start time of the summary (within 5 seconds)
        let matchingSegment = segments.find(
          (segment: any) =>
            Math.abs(
              timeToSeconds(segment.start_time) - timeToSeconds(summary.start)
            ) < 5
        );

        // Strategy 2: If no exact match found, try to find a segment that's contained within the summary time range
        if (!matchingSegment) {
          const summaryStartTime = timeToSeconds(summary.start);
          const summaryEndTime = timeToSeconds(summary.end);

          matchingSegment = segments.find((segment: any) => {
            const segmentTime = timeToSeconds(segment.start_time);
            return (
              segmentTime >= summaryStartTime && segmentTime <= summaryEndTime
            );
          });
        }

        // Strategy 3: If still no match, just take the closest segment
        if (!matchingSegment) {
          let closestSegment = segments[0];
          let closestDiff = Math.abs(
            timeToSeconds(segments[0].start_time) - timeToSeconds(summary.start)
          );

          for (const segment of segments) {
            const diff = Math.abs(
              timeToSeconds(segment.start_time) - timeToSeconds(summary.start)
            );
            if (diff < closestDiff) {
              closestDiff = diff;
              closestSegment = segment;
            }
          }

          matchingSegment = closestSegment;
        }

        return {
          ...summary,
          screenshot_url: matchingSegment?.screenshot_url || null,
        };
      });

      return enhancedSummaries;
    } catch (error) {
      console.error("Error getting screenshots for summaries:", error);
      return summaryData; // Return original data if something fails
    }
  };

  // Add the timeToSeconds function that was missing
  const timeToSeconds = (timeStr: string): number => {
    try {
      // Handle different time formats: HH:MM:SS or HH:MM:SS.mmm
      const parts = timeStr.split(":");
      if (parts.length !== 3) {
        console.error(`Invalid time format: ${timeStr}`);
        return 0;
      }

      const hours = parseInt(parts[0], 10);
      const minutes = parseInt(parts[1], 10);
      // Handle seconds with milliseconds
      const seconds = parseFloat(parts[2]);

      return hours * 3600 + minutes * 60 + seconds;
    } catch (error) {
      console.error(`Error converting time ${timeStr} to seconds:`, error);
      return 0;
    }
  };

  // Language options (ISO 639-1 codes)
  const languageOptions = [
    { value: "", label: "Auto-detect Language" },
    { value: "en", label: "English" },
    { value: "es", label: "Spanish" },
    { value: "fr", label: "French" },
    { value: "de", label: "German" },
    { value: "it", label: "Italian" },
    { value: "ja", label: "Japanese" },
    { value: "ko", label: "Korean" },
    { value: "pt", label: "Portuguese" },
    { value: "ru", label: "Russian" },
    { value: "zh", label: "Chinese" },
    // Add more languages as needed
  ];

  // Function to open the modal
  const openImageModal = (imageUrl: string | undefined) => {
    if (imageUrl) {
      setModalImageUrl(imageUrl);
      setIsModalOpen(true);
    }
  };

  // Add this after the useEffect hooks
  useEffect(() => {
    if (videoRef) {
      // Add seeking event listeners
      const handleSeeking = () => {
        setIsVideoSeeking(true);
      };

      const handleSeeked = () => {
        setIsVideoSeeking(false);
        // Update active segment based on current time
        if (transcription?.transcription.segments) {
          const currentTime = videoRef.currentTime;
          const segments = transcription.transcription.segments;
          const matchingSegment = segments.find((segment) => {
            const segmentStartSeconds = timeToSeconds(segment.start_time);
            const segmentEndSeconds = timeToSeconds(segment.end_time);
            return (
              currentTime >= segmentStartSeconds &&
              currentTime <= segmentEndSeconds
            );
          });

          if (matchingSegment) {
            setActiveSegmentId(matchingSegment.id);
            // Scroll to the active segment
            const segmentElement = document.getElementById(
              `transcript-segment-${matchingSegment.id}`
            );
            if (segmentElement) {
              const transcriptContainer = document.querySelector(
                ".flex-grow.overflow-auto"
              );
              if (transcriptContainer) {
                const containerRect =
                  transcriptContainer.getBoundingClientRect();
                const elementRect = segmentElement.getBoundingClientRect();
                const relativeTop = elementRect.top - containerRect.top;

                transcriptContainer.scrollTo({
                  top: transcriptContainer.scrollTop + relativeTop - 100,
                  behavior: "smooth",
                });
              }
            }
          }
        }
      };

      videoRef.addEventListener("seeking", handleSeeking);
      videoRef.addEventListener("seeked", handleSeeked);

      return () => {
        videoRef.removeEventListener("seeking", handleSeeking);
        videoRef.removeEventListener("seeked", handleSeeked);
      };
    }
  }, [videoRef, transcription]);

  // --- Spinner/modal overlay ---
  const isTranscribing =
    processingStatus &&
    ["uploading", "transcribing", "extracting"].includes(
      processingStatus.stage
    );

  // When translation is requested, translate all segments using the selected translation method
  useEffect(() => {
    if (
      transcription &&
      transcription.transcription.language &&
      transcription.transcription.language.toLowerCase() !== "en" &&
      translationMethod === "marianmt" &&
      transcription.transcription.segments.some((seg) => !seg.translation)
    ) {
      const doTranslation = async () => {
        const sourceLang = transcription.transcription.language.toLowerCase();
        const updatedSegments = await Promise.all(
          transcription.transcription.segments.map(async (seg) => {
            if (!seg.translation && seg.text) {
              try {
                const translation = await translateLocalText(
                  seg.text,
                  sourceLang
                );
                return { ...seg, translation };
              } catch (e) {
                return { ...seg, translation: "[Translation failed]" };
              }
            }
            return seg;
          })
        );
        setTranscription({
          ...transcription,
          transcription: {
            ...transcription.transcription,
            segments: updatedSegments,
          },
        });
      };
      doTranslation();
    }
  }, [transcription, translationMethod]);

  // Play/pause handlers
  const handlePlayPause = () => {
    if (videoRef) {
      if (videoRef.paused) {
        videoRef.play();
      } else {
        videoRef.pause();
      }
    }
  };

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

  // Notify parent when transcription changes
  useEffect(() => {
    if (onTranscriptionChange) {
      onTranscriptionChange(transcription);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [transcription]);

  // Add keyboard event handler for seeking and play/pause
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (!videoRef) return;
      // Ctrl+J to open Jump to Time
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "j") {
        e.preventDefault();
        setJumpModalOpen(true);
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
        case "p": // P key
        case "P": // P key (uppercase)
          e.preventDefault();
          handlePlayPause();
          break;
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [videoRef]);

  // Add volume change handler
  const handleVolumeChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const newVolume = parseFloat(e.target.value);
    setVolume(newVolume);
    if (videoRef) {
      videoRef.volume = newVolume;
    }
  };

  return (
    <div className="relative min-h-screen bg-gradient-to-br from-slate-50 via-white to-slate-100">
      {/* Spinner overlay when transcribing */}
      {isTranscribing && (
        <div className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-black/70 backdrop-blur-md">
          <div className="bg-white rounded-3xl p-12 shadow-2xl max-w-md">
            <div className="flex justify-center mb-6">
              <div className="w-16 h-16 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-2xl flex items-center justify-center animate-pulse">
                <div className="animate-spin">
                  <FaSpinner size={32} color="white" />
                </div>
              </div>
            </div>
            <div className="text-gray-900 text-xl font-bold text-center mb-2">
              Transcribing your file...
            </div>
            <div className="text-gray-600 text-sm text-center leading-relaxed">
              Our AI is processing your content. This may take a few minutes
              depending on the file size.
            </div>
            <div className="mt-6 w-full h-1 bg-gray-200 rounded-full overflow-hidden">
              <div className="h-full w-1/3 bg-gradient-to-r from-indigo-500 to-purple-600 animate-pulse"></div>
            </div>
          </div>
        </div>
      )}
      <div className="h-full text-gray-900 p-6">
        {/* Upload Section */}
        {!transcription && (
          <div className="mx-auto max-w-5xl">
            <div className="mb-8">
              <div className="flex items-center gap-3 mb-4">
                <div className="w-12 h-12 bg-gradient-to-br from-indigo-600 to-purple-600 rounded-xl flex items-center justify-center">
                  <svg
                    className="w-6 h-6 text-white"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M14.828 14.828a4 4 0 01-5.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                    />
                  </svg>
                </div>
                <div>
                  <h1 className="text-4xl font-bold text-gray-900">AI Subs</h1>
                  <p className="text-sm text-gray-500">
                    Intelligent Transcription & Subtitle Generation
                  </p>
                </div>
              </div>
            </div>

            <div className="bg-white rounded-2xl shadow-lg border border-gray-200 overflow-hidden">
              <div className="p-8 md:p-10">
                <div className="text-center mb-10">
                  <h2 className="text-2xl md:text-3xl font-bold text-gray-900 mb-3">
                    Transform Your Media Into Text
                  </h2>
                  <p className="text-gray-600 max-w-2xl mx-auto leading-relaxed">
                    Upload a video or audio file and our advanced AI will
                    automatically transcribe it with accurate timestamps.
                    <br />
                    <span className="inline-block mt-2 text-indigo-600 font-semibold">
                      ⚡ Supports large files • 30+ languages • Instant results
                    </span>
                  </p>
                </div>

                <div
                  className={`
                    relative flex flex-col items-center justify-center
                    w-full max-w-2xl mx-auto h-72 border-3 border-dashed rounded-3xl
                    transition-all duration-300 ease-in-out cursor-pointer
                    ${
                      dragActive
                        ? "border-indigo-500 bg-indigo-50 shadow-xl scale-[1.02]"
                        : "border-gray-300 bg-gray-50 hover:bg-indigo-50/70 hover:border-indigo-400 hover:scale-[1.01]"
                    }
                    ${
                      transcribeMutation.isPending
                        ? "opacity-60 pointer-events-none"
                        : ""
                    }
                  `}
                  onDragEnter={handleDrag}
                  onDragLeave={handleDrag}
                  onDragOver={handleDrag}
                  onDrop={handleDrop}
                  onClick={handleButtonClick}
                >
                  <div className="flex flex-col items-center justify-center py-8 px-8 text-center">
                    <div className="mb-6">
                      <div
                        className={`w-20 h-20 rounded-2xl flex items-center justify-center mb-4 transition-all duration-300 ${
                          dragActive
                            ? "bg-gradient-to-br from-indigo-500 to-purple-600 scale-110 shadow-lg"
                            : "bg-gradient-to-br from-indigo-100 to-purple-100"
                        }`}
                      >
                        <svg
                          className={`w-10 h-10 transition-colors duration-300 ${
                            dragActive ? "text-white" : "text-indigo-600"
                          }`}
                          fill="none"
                          stroke="currentColor"
                          viewBox="0 0 24 24"
                          strokeWidth="1.5"
                        >
                          <path d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                        </svg>
                      </div>
                    </div>
                    <h3 className="text-2xl font-bold text-gray-900 mb-2">
                      {dragActive ? "Release to upload" : "Drop your file here"}
                    </h3>
                    <p className="text-gray-600 mb-1 text-base font-medium">
                      or{" "}
                      <span className="text-indigo-600 underline">browse</span>{" "}
                      your computer
                    </p>
                    <p className="text-xs text-gray-500 mt-2">
                      MP4 • MP3 • WAV • WebM • AVI • MKV and more (up to 10GB)
                    </p>
                  </div>
                  <input
                    ref={fileInputRef}
                    type="file"
                    className="hidden"
                    accept="video/*,audio/*"
                    onChange={handleFileChange}
                    disabled={transcribeMutation.isPending}
                  />
                </div>

                {/* Show selected file info if a file is staged */}
                {file && !transcription && (
                  <div className="mt-8 max-w-2xl mx-auto p-6 bg-gradient-to-r from-emerald-50 via-cyan-50 to-blue-50 rounded-2xl border-2 border-emerald-200 shadow-sm">
                    <div className="flex items-start gap-4">
                      <div className="flex-shrink-0">
                        <div className="flex items-center justify-center h-12 w-12 rounded-xl bg-gradient-to-br from-emerald-500 to-cyan-500 shadow-md">
                          {file.type.startsWith("video/") ? (
                            <svg
                              className="h-6 w-6 text-white"
                              fill="none"
                              stroke="currentColor"
                              viewBox="0 0 24 24"
                            >
                              <path
                                strokeLinecap="round"
                                strokeLinejoin="round"
                                strokeWidth={2}
                                d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"
                              />
                              <path
                                strokeLinecap="round"
                                strokeLinejoin="round"
                                strokeWidth={2}
                                d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                              />
                            </svg>
                          ) : (
                            <svg
                              className="h-6 w-6 text-white"
                              fill="none"
                              stroke="currentColor"
                              viewBox="0 0 24 24"
                            >
                              <path
                                strokeLinecap="round"
                                strokeLinejoin="round"
                                strokeWidth={2}
                                d="M9 19V6a2 2 0 012-2h4a2 2 0 012 2v13m-6 0a2 2 0 002 2h4a2 2 0 002-2m0 0V9a2 2 0 00-2-2h-4a2 2 0 00-2 2v13"
                              />
                            </svg>
                          )}
                        </div>
                      </div>
                      <div className="flex-grow">
                        <h4 className="text-sm font-bold text-gray-900 truncate">
                          {file.name}
                        </h4>
                        <p className="text-sm text-gray-600 mt-1">
                          📊 Size: {(file.size / (1024 * 1024)).toFixed(2)} MB
                        </p>
                        <p className="text-xs text-emerald-700 font-medium mt-2">
                          ✓ File ready to transcribe
                        </p>
                      </div>
                    </div>
                  </div>
                )}

                {/* Language and Method Selection */}
                <div className="mt-8 max-w-2xl mx-auto grid grid-cols-1 md:grid-cols-2 gap-6">
                  {/* Language Selection */}
                  <div>
                    <label
                      htmlFor="language-select"
                      className="block text-sm font-semibold text-gray-900 mb-2"
                    >
                      🌐 Source Language
                    </label>
                    <select
                      id="language-select"
                      value={selectedLanguage}
                      onChange={handleLanguageChange}
                      disabled={transcribeMutation.isPending}
                      className="input-base w-full"
                    >
                      {languageOptions.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                    <p className="mt-2 text-xs text-gray-500">
                      Auto-detect if you're not sure
                    </p>
                  </div>

                  {/* Transcription Method */}
                  <div>
                    <label className="block text-sm font-semibold text-gray-900 mb-2">
                      ⚡ Processing Method
                    </label>
                    <div className="flex items-center h-11 px-4 border-2 border-gray-300 rounded-lg bg-white hover:border-indigo-400 transition-colors">
                      <input
                        type="radio"
                        id="local-method"
                        className="w-4 h-4 accent-indigo-600 cursor-pointer"
                        name="transcriptionMethod"
                        value="local"
                        checked={transcriptionMethod === "local"}
                        onChange={(e) => {
                          setTranscriptionMethod(
                            e.target.value as TranscriptionMethod
                          );
                        }}
                      />
                      <label
                        htmlFor="local-method"
                        className="ml-3 text-sm font-medium text-gray-700 cursor-pointer flex-grow"
                      >
                        Local (Faster, Free)
                      </label>
                    </div>
                    <p className="mt-2 text-xs text-gray-500">
                      Processes on your device
                    </p>
                  </div>
                </div>

                {/* Start Transcription Button */}
                {file && !transcribeMutation.isPending && !transcription && (
                  <div className="mt-10 max-w-2xl mx-auto text-center">
                    <button
                      onClick={handleStartTranscriptionClick}
                      className="w-full md:w-auto px-8 py-4 bg-gradient-to-r from-indigo-600 to-purple-600 text-white font-bold rounded-xl shadow-lg 
                                 hover:from-indigo-700 hover:to-purple-700 hover:shadow-xl
                                 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500
                                 transition-all duration-200 active:scale-95
                                 flex items-center justify-center gap-2 text-lg"
                    >
                      <svg
                        className="w-5 h-5"
                        fill="none"
                        stroke="currentColor"
                        viewBox="0 0 24 24"
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          strokeWidth={2}
                          d="M13 10V3L4 14h7v7l9-11h-7z"
                        />
                      </svg>
                      Start Transcribing
                    </button>
                  </div>
                )}

                {/* Load Saved Button */}
                <div className="mt-3 text-center">
                  <button
                    onClick={handleSavedTranscriptionsClick}
                    className="text-sm text-blue-600 hover:text-blue-800 font-medium flex items-center justify-center mx-auto"
                    disabled={transcribeMutation.isPending}
                  >
                    <svg
                      className="w-4 h-4 mr-1"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                    >
                      <path d="M19 14l-7 7m0 0l-7-7m7 7V3"></path>
                    </svg>
                    {showSavedTranscriptions
                      ? "Hide Saved"
                      : "Load Saved Transcription"}
                  </button>
                </div>

                {/* Saved Transcriptions Panel */}
                {showSavedTranscriptions && (
                  <div className="mt-4 max-w-lg mx-auto">
                    <SavedTranscriptionsPanel
                      onTranscriptionLoaded={handleTranscriptionLoaded}
                      onImageClick={openImageModal}
                    />
                  </div>
                )}

                {/* File Format Info */}
                <div className="mt-4 flex justify-center gap-3">
                  <div className="flex items-center space-x-1 text-gray-600">
                    <svg
                      className="w-3 h-3 text-teal-500"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                    >
                      <circle cx="12" cy="12" r="10"></circle>
                      <polyline points="12 6 12 12 16 14"></polyline>
                    </svg>
                    <span className="text-2xs">Quick Processing</span>
                  </div>
                  <div className="flex items-center space-x-1 text-gray-600">
                    <svg
                      className="w-3 h-3 text-teal-500"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                    >
                      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path>
                    </svg>
                    <span className="text-2xs">Secure Upload</span>
                  </div>
                  <div className="flex items-center space-x-1 text-gray-600">
                    <svg
                      className="w-3 h-3 text-teal-500"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                    >
                      <path d="M22 12h-4l-3 9L9 3l-3 9H2"></path>
                    </svg>
                    <span className="text-2xs">High Accuracy</span>
                  </div>
                </div>

                {/* Processing Status - Keep only this one */}
                {!isNewTranscription && processingStatus && (
                  <div className="w-full max-w-lg mx-auto mt-6 p-4 rounded-lg border border-gray-100">
                    <div className="flex justify-between items-center mb-2">
                      <span className="text-sm font-medium text-teal-700 flex items-center">
                        {processingStatus.stage === "extracting" ? (
                          <>
                            <svg
                              className="animate-spin -ml-1 mr-2 h-3 w-3 text-teal-500"
                              fill="none"
                              viewBox="0 0 24 24"
                            >
                              <circle
                                className="opacity-25"
                                cx="12"
                                cy="12"
                                r="10"
                                stroke="currentColor"
                                strokeWidth="4"
                              ></circle>
                              <path
                                className="opacity-75"
                                fill="currentColor"
                                d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                              ></path>
                            </svg>
                            Extracting audio...
                          </>
                        ) : processingStatus.stage === "transcribing" ? (
                          <>
                            <svg
                              className="animate-spin -ml-1 mr-2 h-3 w-3 text-teal-500"
                              fill="none"
                              viewBox="0 0 24 24"
                            >
                              <circle
                                className="opacity-25"
                                cx="12"
                                cy="12"
                                r="10"
                                stroke="currentColor"
                                strokeWidth="4"
                              ></circle>
                              <path
                                className="opacity-75"
                                fill="currentColor"
                                d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                              ></path>
                            </svg>
                            Transcribing audio...
                          </>
                        ) : (
                          "Processing..."
                        )}
                      </span>
                      <span className="text-xs font-medium text-teal-700">
                        {processingStatus.stage === "extracting"
                          ? "Step 1 of 3"
                          : processingStatus.stage === "transcribing"
                          ? "Step 2 of 3"
                          : processingStatus.stage === "complete"
                          ? "Step 3 of 3"
                          : `${processingStatus.progress}%`}
                      </span>
                    </div>
                    <div className="h-1.5 w-full bg-gray-200 rounded-full overflow-hidden">
                      {processingStatus.stage === "extracting" ? (
                        <div className="h-full w-full bg-orange-400 rounded-full animate-pulse opacity-60"></div>
                      ) : (
                        <div
                          className="h-full bg-gradient-to-r from-orange-400 to-rose-500 rounded-full transition-all duration-300"
                          style={{ width: `${processingStatus.progress}%` }}
                        />
                      )}
                    </div>
                    <div className="mt-2 flex justify-between text-2xs text-gray-500">
                      <p className="text-center">
                        {processingStatus.stage === "extracting"
                          ? "Extracting audio from video file. This may take several minutes depending on file size..."
                          : processingStatus.stage === "transcribing"
                          ? "Converting speech to text..."
                          : "Processing your file..."}
                      </p>
                      <p className="text-right font-medium">
                        {elapsedTime > 0 &&
                          `Time elapsed: ${formatProcessingTime(
                            elapsedTime.toString()
                          )}`}
                      </p>
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* Features Cards */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mt-10 pt-2">
              <div className="group bg-white p-6 rounded-xl shadow-sm border border-gray-200 hover:shadow-lg hover:-translate-y-1 transition-all duration-300">
                <div className="flex items-start gap-4">
                  <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-violet-100 to-violet-200 flex items-center justify-center flex-shrink-0 group-hover:scale-110 transition-transform">
                    <svg
                      className="w-6 h-6 text-violet-600"
                      fill="none"
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                      strokeWidth="1.5"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                      />
                    </svg>
                  </div>
                  <div className="flex-grow">
                    <h3 className="text-sm font-bold text-gray-900 mb-1">
                      High Accuracy
                    </h3>
                    <p className="text-xs text-gray-600 leading-relaxed">
                      Advanced AI model trained on diverse speech patterns for
                      exceptional accuracy
                    </p>
                  </div>
                </div>
              </div>

              <div className="group bg-white p-6 rounded-xl shadow-sm border border-gray-200 hover:shadow-lg hover:-translate-y-1 transition-all duration-300">
                <div className="flex items-start gap-4">
                  <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-orange-100 to-orange-200 flex items-center justify-center flex-shrink-0 group-hover:scale-110 transition-transform">
                    <svg
                      className="w-6 h-6 text-orange-600"
                      fill="none"
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                      strokeWidth="1.5"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"
                      />
                    </svg>
                  </div>
                  <div className="flex-grow">
                    <h3 className="text-sm font-bold text-gray-900 mb-1">
                      Fast Processing
                    </h3>
                    <p className="text-xs text-gray-600 leading-relaxed">
                      Get results in minutes, not hours. Optimized for speed
                      without sacrificing quality
                    </p>
                  </div>
                </div>
              </div>

              <div className="group bg-white p-6 rounded-xl shadow-sm border border-gray-200 hover:shadow-lg hover:-translate-y-1 transition-all duration-300">
                <div className="flex items-start gap-4">
                  <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-rose-100 to-rose-200 flex items-center justify-center flex-shrink-0 group-hover:scale-110 transition-transform">
                    <svg
                      className="w-6 h-6 text-rose-600"
                      fill="none"
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                      strokeWidth="1.5"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        d="M3.375 19.5h17.25m-17.25 0a1.125 1.125 0 01-1.125-1.125M3.375 19.5h0a1.125 1.125 0 001.125 1.125m0 0v1.5a.5.5 0 01-.5.5H5a.5.5 0 01-.5-.5v-1.5m0 0h-1.5a.5.5 0 01-.5-.5V15m0 0a1.125 1.125 0 001.125-1.125m0 0h0a1.125 1.125 0 001.125 1.125m0 0v1.5a.5.5 0 01-.5.5H5a.5.5 0 01-.5-.5v-1.5"
                      />
                    </svg>
                  </div>
                  <div className="flex-grow">
                    <h3 className="text-sm font-bold text-gray-900 mb-1">
                      30+ Languages
                    </h3>
                    <p className="text-xs text-gray-600 leading-relaxed">
                      Automatic language detection with support for languages
                      worldwide
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Results Section */}
        {transcription && (
          <div className="space-y-8 h-screen flex flex-col overflow-hidden w-full">
            <div className="bg-white rounded-2xl p-6 md:p-8 shadow-lg border border-gray-200 flex-shrink-0">
              <div className="flex items-start gap-4 mb-6">
                <div className="w-12 h-12 bg-gradient-to-br from-emerald-500 to-cyan-500 rounded-xl flex items-center justify-center shadow-lg flex-shrink-0">
                  <svg
                    className="w-6 h-6 text-white"
                    fill="currentColor"
                    viewBox="0 0 20 20"
                  >
                    <path
                      fillRule="evenodd"
                      d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z"
                      clipRule="evenodd"
                    />
                  </svg>
                </div>
                <div className="flex-grow">
                  <h2 className="text-2xl md:text-3xl font-bold text-gray-900 mb-1">
                    Transcription Ready!
                  </h2>
                  <p className="text-sm text-gray-600">
                    ✨ Your content has been successfully transcribed with
                    timestamps
                  </p>
                </div>
              </div>

              {/* Stats Grid */}
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 md:gap-4 mb-6">
                <div className="bg-gradient-to-br from-blue-50 to-blue-100 rounded-xl p-4 md:p-5 border border-blue-200">
                  <div className="text-xs font-semibold text-blue-600 mb-1 uppercase tracking-wide">
                    📄 File
                  </div>
                  <div
                    className="text-sm font-bold text-gray-900 truncate"
                    title={transcription.filename}
                  >
                    {transcription.filename.length > 20
                      ? transcription.filename.substring(0, 17) + "..."
                      : transcription.filename}
                  </div>
                </div>
                <div className="bg-gradient-to-br from-purple-50 to-purple-100 rounded-xl p-4 md:p-5 border border-purple-200">
                  <div className="text-xs font-semibold text-purple-600 mb-1 uppercase tracking-wide">
                    ⏱️ Duration
                  </div>
                  <div className="text-sm font-bold text-gray-900">
                    {transcription.transcription.duration}
                  </div>
                </div>
                <div className="bg-gradient-to-br from-cyan-50 to-cyan-100 rounded-xl p-4 md:p-5 border border-cyan-200">
                  <div className="text-xs font-semibold text-cyan-600 mb-1 uppercase tracking-wide">
                    🌐 Language
                  </div>
                  <div className="text-sm font-bold text-gray-900 uppercase">
                    {transcription.transcription.language}
                  </div>
                </div>
                <div className="bg-gradient-to-br from-emerald-50 to-emerald-100 rounded-xl p-4 md:p-5 border border-emerald-200">
                  <div className="text-xs font-semibold text-emerald-600 mb-1 uppercase tracking-wide">
                    ⚡ Speed
                  </div>
                  <div className="text-sm font-bold text-emerald-900">
                    {formatProcessingTime(
                      transcription.transcription.processing_time
                    )}
                  </div>
                </div>
              </div>

              {/* Action Buttons */}
              <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3 flex-wrap">
                <button
                  onClick={handleSearchClick}
                  className={`px-6 py-3 rounded-xl font-semibold shadow-lg hover:shadow-xl transition-all duration-200 hover:scale-105 flex items-center justify-center gap-2 ${
                    showSearch
                      ? "bg-gradient-to-r from-slate-800 to-slate-900 hover:from-slate-900 hover:to-black text-white"
                      : "bg-gradient-to-r from-slate-700 to-slate-800 hover:from-slate-800 hover:to-slate-900 text-white"
                  }`}
                >
                  <svg
                    className="w-4 h-4"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth="2.5"
                  >
                    <path d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                  </svg>
                  <span>{showSearch ? "Hide Search" : "Search"}</span>
                </button>

                <button
                  onClick={startNewTranscription}
                  className="px-6 py-3 bg-gradient-to-r from-blue-600 to-blue-700 hover:from-blue-700 hover:to-blue-800 text-white font-semibold rounded-xl shadow-lg hover:shadow-xl transition-all duration-200 hover:scale-105 flex items-center justify-center gap-2"
                >
                  <svg
                    className="w-4 h-4"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2.5"
                  >
                    <polyline points="23 4 23 10 17 10"></polyline>
                    <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path>
                  </svg>
                  <span>New Transcription</span>
                </button>
                <SubtitleControls filename={transcription.filename} />
              </div>
            </div>

            {/* New Three-Column Layout */}
            <div className="flex flex-col lg:flex-row flex-grow overflow-hidden w-full gap-4 mt-6">
              {/* Main Column: Video and Transcript/Summary */}
              <div
                className={`flex-grow flex flex-col overflow-hidden ${
                  showSearch ? "lg:w-3/4" : "lg:w-full"
                }`}
              >
                {/* Video Player (Top) */}
                {videoUrl && (
                  <div className="bg-black rounded-xl shadow-lg border border-gray-300 overflow-hidden flex-shrink-0 mb-4 lg:mb-0">
                    <div
                      className="w-full bg-black flex justify-center relative"
                      onMouseEnter={() => setIsVideoHovered(true)}
                      onMouseLeave={() => setIsVideoHovered(false)}
                    >
                      <video
                        ref={setVideoRef}
                        src={videoUrl}
                        className="w-full max-h-[50vh] object-contain"
                        onTimeUpdate={() => {
                          if (!isVideoSeeking && videoRef) {
                            const currentTime = videoRef.currentTime;
                            if (transcription?.transcription.segments) {
                              const segments =
                                transcription.transcription.segments;
                              const matchingSegment = segments.find(
                                (segment) => {
                                  const segmentStartSeconds = timeToSeconds(
                                    segment.start_time
                                  );
                                  const segmentEndSeconds = timeToSeconds(
                                    segment.end_time
                                  );
                                  return (
                                    currentTime >= segmentStartSeconds &&
                                    currentTime <= segmentEndSeconds
                                  );
                                }
                              );

                              if (matchingSegment) {
                                setActiveSegmentId(matchingSegment.id);
                              }
                            }
                          }
                        }}
                      >
                        {subtitleTrackUrl && (
                          <track
                            src={subtitleTrackUrl}
                            kind="subtitles"
                            srcLang={
                              transcription?.transcription.language || "en"
                            }
                            label={
                              transcription?.transcription.language?.toUpperCase() ||
                              "Original"
                            }
                            default={showSubtitles && !showTranslation}
                          />
                        )}
                        {translatedSubtitleUrl && (
                          <track
                            src={translatedSubtitleUrl}
                            kind="subtitles"
                            srcLang="en"
                            label="ENGLISH"
                            default={showSubtitles && showTranslation}
                          />
                        )}
                      </video>
                    </div>
                    {/* Custom Progress Bar with Tooltip and Screenshot Preview */}
                    {videoRef && (
                      <>
                        <div className="flex items-center px-4 py-2 gap-4">
                          {/* Play/Pause Button */}
                          <button
                            onClick={handlePlayPause}
                            className="flex items-center justify-center"
                            aria-label={isPlaying ? "Pause" : "Play"}
                          >
                            {isPlaying ? (
                              <svg
                                className="w-6 h-6 text-gray-700"
                                fill="currentColor"
                                viewBox="0 0 24 24"
                              >
                                <rect
                                  x="6"
                                  y="4"
                                  width="4"
                                  height="16"
                                  rx="1"
                                />
                                <rect
                                  x="14"
                                  y="4"
                                  width="4"
                                  height="16"
                                  rx="1"
                                />
                              </svg>
                            ) : (
                              <svg
                                className="w-6 h-6 text-gray-700"
                                fill="currentColor"
                                viewBox="0 0 24 24"
                              >
                                <path d="M8 5v14l11-7z" />
                              </svg>
                            )}
                          </button>

                          {/* Volume Control */}
                          <div className="flex items-center space-x-2">
                            <svg
                              className="w-5 h-5 text-gray-600 cursor-pointer"
                              fill="none"
                              viewBox="0 0 24 24"
                              stroke="currentColor"
                              onClick={() => {
                                if (videoRef) {
                                  const newVolume = volume === 0 ? 1 : 0;
                                  setVolume(newVolume);
                                  videoRef.volume = newVolume;
                                }
                              }}
                            >
                              {volume === 0 ? (
                                <path
                                  strokeLinecap="round"
                                  strokeLinejoin="round"
                                  strokeWidth={2}
                                  d="M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z"
                                />
                              ) : (
                                <path
                                  strokeLinecap="round"
                                  strokeLinejoin="round"
                                  strokeWidth={2}
                                  d="M15.536 8.464a5 5 0 010 7.072m2.828-9.9a9 9 0 010 12.728M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z"
                                />
                              )}
                            </svg>
                            <input
                              type="range"
                              min="0"
                              max="1"
                              step="0.1"
                              value={volume}
                              onChange={handleVolumeChange}
                              className="w-20 h-1 bg-gray-200 rounded-lg appearance-none cursor-pointer"
                            />
                          </div>
                        </div>
                        <CustomProgressBar
                          videoRef={videoRef}
                          duration={videoRef.duration || 0}
                          currentTime={videoRef.currentTime || 0}
                          segments={transcription.transcription.segments}
                          getScreenshotUrlForTime={(time) => {
                            // Find the segment whose start_time is closest to the hovered time
                            if (!transcription.transcription.segments)
                              return null;
                            let closest = null;
                            let minDiff = Infinity;
                            for (const seg of transcription.transcription
                              .segments) {
                              const segTime = timeToSeconds(seg.start_time);
                              const diff = Math.abs(segTime - time);
                              if (diff < minDiff) {
                                minDiff = diff;
                                closest = seg;
                              }
                            }
                            return closest && closest.screenshot_url
                              ? `http://localhost:8000${closest.screenshot_url}`
                              : null;
                          }}
                          onSeek={(time: number) => {
                            videoRef.currentTime = time;
                          }}
                        />
                        <div className="flex justify-end px-4 pb-2">
                          <button
                            className="px-3 py-1 rounded bg-gray-600 text-white text-xs font-semibold hover:bg-gray-700 shadow"
                            onClick={() => setJumpModalOpen(true)}
                          >
                            Jump to Time
                          </button>
                        </div>
                        <JumpToTimeModal
                          isOpen={jumpModalOpen}
                          onClose={() => setJumpModalOpen(false)}
                          onJump={(seconds) => {
                            if (videoRef) videoRef.currentTime = seconds;
                          }}
                          duration={videoRef.duration || 0}
                          currentTime={videoRef.currentTime || 0}
                        />
                      </>
                    )}
                  </div>
                )}

                {/* Tabs for Transcript and Summary */}
                <div className="bg-white rounded-xl shadow-md border border-gray-200 overflow-hidden flex-grow flex flex-col mt-4 lg:mt-0">
                  <div className="flex border-b border-gray-200 sticky top-0 bg-gradient-to-r from-gray-50 to-white z-10">
                    <button
                      onClick={() => setShowSummary(false)}
                      className={`flex-1 px-5 py-4 text-sm font-bold transition-all duration-200 relative ${
                        !showSummary
                          ? "text-indigo-600"
                          : "text-gray-600 hover:text-gray-900"
                      }`}
                    >
                      <div className="flex items-center justify-center gap-2">
                        <svg
                          className="w-4 h-4"
                          fill="none"
                          stroke="currentColor"
                          viewBox="0 0 24 24"
                        >
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth={2}
                            d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                          />
                        </svg>
                        Transcript
                      </div>
                      {!showSummary && (
                        <div className="absolute bottom-0 left-0 right-0 h-1 bg-gradient-to-r from-indigo-500 to-purple-600 rounded-t-full"></div>
                      )}
                    </button>
                    <button
                      onClick={() => setShowSummary(true)}
                      className={`flex-1 px-5 py-4 text-sm font-bold transition-all duration-200 relative ${
                        showSummary
                          ? "text-indigo-600"
                          : "text-gray-600 hover:text-gray-900"
                      }`}
                    >
                      <div className="flex items-center justify-center gap-2">
                        <svg
                          className="w-4 h-4"
                          fill="none"
                          stroke="currentColor"
                          viewBox="0 0 24 24"
                        >
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth={2}
                            d="M19 20H5a2 2 0 01-2-2V6a2 2 0 012-2h10a2 2 0 012 2v11m-5-5v6m0 0v3m0-3a3 3 0 11-6 0 3 3 0 016 0z"
                          />
                        </svg>
                        Summary
                      </div>
                      {showSummary && (
                        <div className="absolute bottom-0 left-0 right-0 h-1 bg-gradient-to-r from-indigo-500 to-purple-600 rounded-t-full"></div>
                      )}
                    </button>
                  </div>

                  <div className="flex-grow overflow-auto relative">
                    {!showSummary && (
                      <>
                        {/* Sticky Show Translation button */}
                        <div className="sticky top-0 bg-gradient-to-r from-gray-50 to-white z-10 px-5 py-4 border-b border-gray-200 flex justify-between items-center">
                          <div className="flex items-center gap-2">
                            <button
                              onClick={() =>
                                setShowTranslation(!showTranslation)
                              }
                              className={`px-4 py-2 rounded-lg text-sm font-semibold transition-all duration-200 flex items-center gap-2 ${
                                showTranslation
                                  ? "bg-gradient-to-r from-blue-500 to-blue-600 text-white shadow-md hover:shadow-lg"
                                  : "bg-gray-200 text-gray-700 hover:bg-gray-300"
                              }`}
                            >
                              <svg
                                className="w-4 h-4"
                                fill="none"
                                stroke="currentColor"
                                viewBox="0 0 24 24"
                              >
                                <path
                                  strokeLinecap="round"
                                  strokeLinejoin="round"
                                  strokeWidth={2}
                                  d="M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0 01.684.949V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z"
                                />
                              </svg>
                              {showTranslation
                                ? "Show Original"
                                : "Show Translation"}
                            </button>
                          </div>
                        </div>
                        {/* Transcript content */}
                        <div className="p-5 space-y-4">
                          {transcription.transcription.segments.map(
                            (segment, index) => (
                              <div
                                key={segment.id}
                                id={`transcript-segment-${segment.id}`}
                                onClick={() =>
                                  seekToTimestamp(segment.start_time)
                                }
                                className={`p-4 md:p-5 rounded-xl border-2 transition-all duration-200 cursor-pointer hover:shadow-md hover:cursor-pointer ${
                                  activeSegmentId === segment.id
                                    ? "bg-blue-50 border-blue-400 shadow-md"
                                    : "bg-white border-gray-200 hover:border-gray-300 hover:bg-gray-50"
                                }`}
                              >
                                <div className="flex items-start gap-4">
                                  {segment.screenshot_url && (
                                    <div className="flex-shrink-0">
                                      <img
                                        src={`http://localhost:8000${segment.screenshot_url}`}
                                        alt={`Screenshot at ${segment.start_time}`}
                                        className="w-40 h-24 object-cover rounded-lg shadow-sm hover:shadow-lg transition-shadow hover:scale-110 cursor-pointer border border-gray-200"
                                        onClick={(e) => {
                                          e.stopPropagation();
                                          openImageModal(
                                            `http://localhost:8000${segment.screenshot_url}`
                                          );
                                        }}
                                      />
                                    </div>
                                  )}
                                  <div className="flex-grow min-w-0">
                                    <div className="flex items-center flex-wrap gap-2 mb-2 text-xs font-semibold">
                                      <button
                                        onClick={(e) => {
                                          e.stopPropagation();
                                          seekToTimestamp(segment.start_time);
                                        }}
                                        className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-indigo-100 hover:bg-indigo-200 text-indigo-700 hover:text-indigo-900 rounded-lg transition-all duration-200 hover:shadow-sm active:scale-95"
                                        title="Click to jump to this timestamp"
                                      >
                                        <svg
                                          className="w-4 h-4"
                                          viewBox="0 0 24 24"
                                          fill="currentColor"
                                        >
                                          <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z" />
                                        </svg>
                                        {segment.start_time}
                                      </button>
                                      <span className="text-gray-400">→</span>
                                      <span className="text-gray-600">
                                        {segment.end_time}
                                      </span>
                                      <span className="ml-auto inline-flex items-center px-3 py-1 rounded-full text-2xs font-semibold bg-indigo-100 text-indigo-700">
                                        Segment {index + 1}
                                      </span>
                                    </div>
                                    <p
                                      className={`text-gray-800 leading-relaxed ${
                                        activeSegmentId === segment.id
                                          ? "font-semibold text-gray-900"
                                          : "font-medium"
                                      }`}
                                    >
                                      {showTranslation &&
                                      segment.translation ? (
                                        <>
                                          {segment.translation}
                                          <span className="block text-xs text-gray-500 italic mt-2">
                                            Original: {segment.text}
                                          </span>
                                        </>
                                      ) : (
                                        segment.text
                                      )}
                                    </p>
                                  </div>
                                </div>
                              </div>
                            )
                          )}
                        </div>
                      </>
                    )}

                    {/* Summary Panel */}
                    {showSummary && (
                      <div className="h-full">
                        <SummaryPanel
                          isVisible={showSummary}
                          onSeekTo={seekToTimestamp}
                          summaries={summaries}
                          setSummaries={setSummaries}
                          loading={summaryLoading}
                          generateSummaries={generateSummaries}
                        />
                      </div>
                    )}
                    {showScreenshots && (
                      <div className="h-full p-4">
                        <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                          {summaries.map(
                            (summary, index) =>
                              summary.screenshot_url && (
                                <div
                                  key={index}
                                  className="relative group cursor-pointer"
                                  onClick={() =>
                                    summary.screenshot_url &&
                                    openImageModal(summary.screenshot_url)
                                  }
                                >
                                  <img
                                    src={summary.screenshot_url}
                                    alt={`Screenshot at ${summary.start}`}
                                    className="w-full h-auto rounded-lg shadow-sm hover:shadow-md transition-shadow"
                                  />
                                  <div className="absolute bottom-0 left-0 right-0 bg-black bg-opacity-50 text-white p-2 rounded-b-lg">
                                    <p className="text-sm">{summary.start}</p>
                                  </div>
                                </div>
                              )
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              </div>

              {/* Right Column: Search & Analysis Panels */}
              {showSearch && (
                <div
                  className="w-full lg:w-1/4 lg:min-w-[250px] overflow-y-auto bg-white rounded-lg shadow-sm border border-gray-100 mt-4 lg:mt-0 lg:ml-4"
                  style={{ display: "none" }}
                >
                  <div className="sticky top-0 bg-white z-10 border-b border-gray-200">
                    <div className="px-4 py-3 flex items-center justify-between">
                      <h3 className="text-sm font-medium text-gray-800">
                        Search & Analysis
                      </h3>
                    </div>
                  </div>

                  <div className="p-4 overflow-y-auto h-full">
                    <SearchPanel onSeekToTimestamp={seekToTimestamp} />
                    <div className="mt-4">
                      <AnalyticsPanel onSeekToTimestamp={seekToTimestamp} />
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Error Display */}
        {error && (
          <div className="mt-6 bg-red-50 border-l-4 border-red-400 p-4 rounded-md w-full">
            <div className="flex">
              <div className="flex-shrink-0">
                <svg
                  className="h-5 w-5 text-red-400"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                >
                  <circle cx="12" cy="12" r="10"></circle>
                  <line x1="12" y1="8" x2="12" y2="12"></line>
                  <line x1="12" y1="16" x2="12.01" y2="16"></line>
                </svg>
              </div>
              <div className="ml-3">
                <h3 className="text-sm font-medium text-red-800">
                  Transcription Failed
                </h3>
                <p className="mt-1 text-xs text-red-700">{error}</p>
                <div className="mt-2">
                  <button
                    onClick={() => transcribeMutation.reset()}
                    className="text-xs font-medium text-red-700 hover:text-red-600 focus:outline-none"
                  >
                    Try again
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Image Modal */}
        {isModalOpen && modalImageUrl && (
          <ImageModal
            imageUrl={modalImageUrl}
            onClose={() => setIsModalOpen(false)}
          />
        )}

        {/* Spinner if isPolling is true */}
        {isPolling && (
          <div className="flex flex-col items-center justify-center mt-8">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-teal-500 mb-4"></div>
            <p className="text-teal-700 font-medium">
              Transcribing, please wait…
            </p>
          </div>
        )}
      </div>
    </div>
  );
};
