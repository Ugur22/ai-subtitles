import { useState, useEffect, useMemo } from "react";
import {
  type TranscriptionResponse,
  translateLocalText,
  updateSpeakerName,
} from "../../../services/api";
import { SubtitleControls } from "./SubtitleControls";
import { SearchPanel } from "../search/SearchPanel";
import { AnalyticsPanel } from "../analytics/AnalyticsPanel";
import { SummaryPanel } from "../summary/SummaryPanel";
import { ChatPanel } from "../chat/ChatPanel";
import axios from "axios";
import CustomProgressBar from "./CustomProgressBar";
import React from "react";
import {
  formatProcessingTime,
  convertTimeToSeconds,
  timeToSeconds,
} from "../../../utils/time";
import { formatSpeakerLabel, getSpeakerColor } from "../../../utils/speaker";
import { ImageModal } from "../../common/ImageModal";
import { JumpToTimeModal } from "./JumpToTimeModal";
import { ProcessingOverlay } from "./ProcessingOverlay";
import { TranscriptSegmentList } from "./TranscriptSegmentList";
import { UploadZone } from "./UploadZone";
import { useFileUpload } from "../../../hooks/useFileUpload";
import { useVideoPlayer } from "../../../hooks/useVideoPlayer";
import { useSubtitles } from "../../../hooks/useSubtitles";
import { useTranscription } from "../../../hooks/useTranscription";
import { useSummaries } from "../../../hooks/useSummaries";

// Note: ProcessingStage type moved to useTranscription hook

// Add transcription method type
type TranscriptionMethod = "local";
type TranslationMethod = "none" | "marianmt";

type TranscriptionUploadProps = {
  onTranscriptionChange?: (transcription: TranscriptionResponse | null) => void;
};

export const TranscriptionUpload: React.FC<TranscriptionUploadProps> = ({
  onTranscriptionChange,
}) => {
  // UI-specific state (keep these)
  const [showTranslation, setShowTranslation] = useState(false);
  const [showSummary, setShowSummary] = useState(false);
  const [showChat, setShowChat] = useState(false);
  const [showSearch, setShowSearch] = useState(true);
  const [progressSimulation] = useState<NodeJS.Timeout | null>(null); // Unused but kept for future use
  const [activeSegmentId, setActiveSegmentId] = useState<string | null>(null);
  const [isNewTranscription, setIsNewTranscription] = useState(false);
  const [showSavedTranscriptions, setShowSavedTranscriptions] = useState(false);
  const [selectedLanguage, setSelectedLanguage] = useState<string>("");
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [modalImageUrl, setModalImageUrl] = useState<string | null>(null);
  const [transcriptionMethod, setTranscriptionMethod] =
    useState<TranscriptionMethod>("local");
  // Note: pollingIntervalRef removed - was unused after hook integration
  const [translationMethod] = useState<TranslationMethod>("none");
  const [jumpModalOpen, setJumpModalOpen] = useState(false);
  const [showScreenshots] = useState(false); // Unused but kept for future use
  const [editingSpeaker, setEditingSpeaker] = useState<string | null>(null);
  const [editSpeakerName, setEditSpeakerName] = useState("");
  const [filteredSpeaker, setFilteredSpeaker] = useState<string | null>(null);
  const [speakerDropdownOpen, setSpeakerDropdownOpen] = useState(false);
  const [isHeaderExpanded, setIsHeaderExpanded] = useState(false);

  // Initialize custom hooks
  const transcriptionHook = useTranscription();
  const {
    transcription,
    setTranscription,
    processingStatus,
    setProcessingStatus,
    elapsedTime,
    error,
    setError,
    isPolling,
    handleStartTranscription,
    resetState: resetTranscriptionState,
  } = transcriptionHook;

  const fileUploadHook = useFileUpload({
    onFileSelected: () => {
      setError(null);
      setTranscription(null);
      setProcessingStatus(null);
    },
  });
  const {
    file,
    dragActive,
    videoUrl,
    fileInputRef,
    handleFileChange: fileUploadHandleChange,
    handleDrag,
    handleDrop,
    handleButtonClick,
    setVideoUrl,
  } = fileUploadHook;

  const videoPlayerHook = useVideoPlayer({
    onJumpToTimeRequest: () => setJumpModalOpen(true),
  });
  const {
    videoRef,
    setVideoRef,
    isPlaying,
    volume,
    isVideoSeeking,
    handlePlayPause,
    handleVolumeChange,
  } = videoPlayerHook;

  const subtitlesHook = useSubtitles({
    transcription,
    videoRef,
    showTranslation,
  });
  const { showSubtitles, subtitleTrackUrl, translatedSubtitleUrl } =
    subtitlesHook;

  const summariesHook = useSummaries({
    transcription,
  });
  const { summaries, setSummaries, summaryLoading, generateSummaries } =
    summariesHook;

  // Computed values
  const isTranscribing =
    processingStatus !== null && processingStatus.stage !== "complete";

  // Filter segments by selected speaker
  const displayedSegments = useMemo(() => {
    if (!transcription) return [];
    if (!filteredSpeaker) return transcription.transcription.segments;
    return transcription.transcription.segments.filter(
      (seg) => seg.speaker === filteredSpeaker
    );
  }, [transcription, filteredSpeaker]);

  // Get unique speakers
  const uniqueSpeakers = useMemo(() => {
    if (!transcription) return [];
    const speakers = new Set(
      transcription.transcription.segments
        .map((seg) => seg.speaker)
        .filter((speaker): speaker is string => !!speaker)
    );
    return Array.from(speakers).sort();
  }, [transcription]);

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
        // currentTime is now managed by the useVideoPlayer hook internally
        // We only need to track the active segment here

        // Find the currently active segment based on video time (only from displayed segments)
        if (displayedSegments.length > 0) {
          const currentSegment = displayedSegments.find((segment) => {
            const startSeconds = convertTimeToSeconds(segment.start_time);
            const endSeconds = convertTimeToSeconds(segment.end_time);
            return (
              videoRef.currentTime >= startSeconds &&
              videoRef.currentTime <= endSeconds
            );
          });

          setActiveSegmentId(currentSegment?.id ?? null);
        }
      };

      videoRef.addEventListener("timeupdate", handleTimeUpdate);

      return () => {
        videoRef.removeEventListener("timeupdate", handleTimeUpdate);
      };
    }
  }, [videoRef, displayedSegments]);

  // Handle Escape key to clear speaker filter
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && filteredSpeaker) {
        setFilteredSpeaker(null);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [filteredSpeaker]);

  const handleLanguageChange = (
    event: React.ChangeEvent<HTMLSelectElement>
  ) => {
    setSelectedLanguage(event.target.value);
  };

  // Note: startPollingForTranscription removed - was unused
  // Polling logic can be added back if needed for cloud transcription

  // Handle transcription start using the hook
  const handleStartTranscriptionClick = async () => {
    if (!file) {
      setError("No file selected to transcribe.");
      return;
    }

    // Use the hook's handleStartTranscription which manages all state internally
    await handleStartTranscription(file, transcriptionMethod, selectedLanguage);
  };

  const startNewTranscription = () => {
    // Set flag to hide progress bar
    setIsNewTranscription(true);

    // Reset transcription state using the hook
    resetTranscriptionState();

    // Reset video URL (file is managed by the hook)
    setVideoUrl(null);

    // Reset UI state
    setShowTranslation(false);
    setSelectedLanguage("");
    setFilteredSpeaker(null);

    // Note: showSubtitles is managed by the useSubtitles hook
    // elapsedTime and processingTimer are managed by useTranscription hook
  };

  // Note: cleanupPreviousScreenshots removed - was unused

  const handleSpeakerRename = async (originalSpeaker: string) => {
    if (!editSpeakerName.trim() || !transcription) return;

    try {
      // Call API
      await updateSpeakerName(
        transcription.video_hash,
        originalSpeaker,
        editSpeakerName.trim()
      );

      // Update local state
      const updatedSegments = transcription.transcription.segments.map(
        (seg) => {
          if (seg.speaker === originalSpeaker) {
            return { ...seg, speaker: editSpeakerName.trim() };
          }
          return seg;
        }
      );

      setTranscription({
        ...transcription,
        transcription: {
          ...transcription.transcription,
          segments: updatedSegments,
        },
      });

      // Update filtered speaker if it was renamed
      if (filteredSpeaker === originalSpeaker) {
        setFilteredSpeaker(editSpeakerName.trim());
      }

      setEditingSpeaker(null);
      setEditSpeakerName("");
    } catch (err) {
      console.error("Failed to rename speaker:", err);
      alert("Failed to rename speaker");
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

    // Find the corresponding segment in the transcript (only from displayed segments)
    if (displayedSegments.length > 0) {
      const segments = displayedSegments;
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

  // Note: handleSummaryClick removed - was unused

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
      // Note: file is managed by useFileUpload hook, no need to clear it
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

  // Create and add subtitles to video
  // Subtitle-related logic now handled by useSubtitles hook

  // Cleanup function for timers when component unmounts
  useEffect(() => {
    return () => {
      if (progressSimulation) {
        clearInterval(progressSimulation);
      }
      // processingTimer is now managed by useTranscription hook
    };
  }, [progressSimulation]);

  // Note: Removed unused functions: updateUploadProgress, handleExtractingAudio,
  // handleTranscribing, fetchCurrentTranscription - all were unused

  // Summary logic now handled by useSummaries hook

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
      setModalImageUrl(imageUrl as string); // TypeScript narrowing
      setIsModalOpen(true);
    }
  };

  // Add this after the useEffect hooks
  useEffect(() => {
    if (videoRef) {
      // Seeking state is managed by useVideoPlayer hook
      // This effect only handles active segment updates after seeking
      const handleSeeked = () => {
        // Update active segment based on current time (only from displayed segments)
        if (displayedSegments.length > 0) {
          const currentTime = videoRef.currentTime;
          const segments = displayedSegments;
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

      videoRef.addEventListener("seeked", handleSeeked);

      return () => {
        videoRef.removeEventListener("seeked", handleSeeked);
      };
    }
  }, [videoRef, displayedSegments]);

  // --- Spinner/modal overlay logic handled by computed isTranscribing value ---

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

  // Video player logic now handled by useVideoPlayer hook

  // Notify parent when transcription changes
  useEffect(() => {
    if (onTranscriptionChange) {
      onTranscriptionChange(transcription);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [transcription]);

  return (
    <div className="relative min-h-screen bg-gradient-to-br from-slate-50 via-white to-slate-100">
      {/* Processing overlay when transcribing */}
      <ProcessingOverlay
        isVisible={isTranscribing}
        processingStatus={processingStatus}
        elapsedTime={elapsedTime}
        file={file}
        videoRef={videoRef}
      />
      <div className="h-full text-gray-900 p-6">
        {/* Upload Section */}
        {!transcription && (
          <UploadZone
            file={file}
            dragActive={dragActive}
            isTranscribing={isTranscribing}
            fileInputRef={fileInputRef}
            handleDrag={handleDrag}
            handleDrop={handleDrop}
            handleButtonClick={handleButtonClick}
            fileUploadHandleChange={fileUploadHandleChange}
            selectedLanguage={selectedLanguage}
            handleLanguageChange={handleLanguageChange}
            transcriptionMethod={transcriptionMethod}
            setTranscriptionMethod={setTranscriptionMethod}
            handleStartTranscriptionClick={handleStartTranscriptionClick}
            showSavedTranscriptions={showSavedTranscriptions}
            handleSavedTranscriptionsClick={handleSavedTranscriptionsClick}
            handleTranscriptionLoaded={handleTranscriptionLoaded}
            openImageModal={openImageModal}
            isNewTranscription={isNewTranscription}
            processingStatus={processingStatus}
            elapsedTime={elapsedTime}
            languageOptions={languageOptions}
          />
        )}

        {/* Results Section */}
        {transcription && (
          <div className="space-y-4 h-screen flex flex-col overflow-hidden w-full">
            <div className="bg-white rounded-xl shadow-lg border border-gray-200 flex-shrink-0 transition-all duration-300">
              {/* Header Top Row (Always Visible) */}
              <div className="p-4 flex flex-col md:flex-row items-center justify-between gap-4">
                {/* Left: File Info */}
                <div className="flex items-center gap-3 w-full md:w-auto overflow-hidden">
                  <div className="w-10 h-10 bg-gradient-to-br from-emerald-500 to-cyan-500 rounded-lg flex items-center justify-center shadow-md flex-shrink-0">
                    <svg
                      className="w-5 h-5 text-white"
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
                  <div className="flex flex-col min-w-0">
                    <h2
                      className="text-sm font-bold text-gray-900 truncate max-w-[200px] md:max-w-md"
                      title={transcription.filename}
                    >
                      {transcription.filename}
                    </h2>
                    {!isHeaderExpanded && (
                      <div className="flex items-center gap-3 text-xs text-gray-500">
                        <span className="font-medium text-purple-600 bg-purple-50 px-2 py-0.5 rounded">
                          {transcription.transcription.duration}
                        </span>
                        <span className="font-medium text-cyan-600 bg-cyan-50 px-2 py-0.5 rounded uppercase">
                          {transcription.transcription.language}
                        </span>
                      </div>
                    )}
                  </div>
                </div>

                {/* Right: Actions */}
                <div className="flex items-center gap-2 w-full md:w-auto justify-end">
                  <button
                    onClick={handleSearchClick}
                    className={`p-2 rounded-lg transition-colors ${
                      showSearch
                        ? "bg-slate-800 text-white hover:bg-slate-900"
                        : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                    }`}
                    title={showSearch ? "Hide Search" : "Show Search"}
                  >
                    <svg
                      className="w-5 h-5"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
                      />
                    </svg>
                  </button>

                  <button
                    onClick={startNewTranscription}
                    className="p-2 bg-blue-50 text-blue-600 hover:bg-blue-100 rounded-lg transition-colors"
                    title="New Transcription"
                  >
                    <svg
                      className="w-5 h-5"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                    >
                      <polyline points="23 4 23 10 17 10"></polyline>
                      <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path>
                    </svg>
                  </button>

                  <div className="h-6 w-px bg-gray-200 mx-1"></div>

                  <SubtitleControls filename={transcription.filename} />

                  <div className="h-6 w-px bg-gray-200 mx-1"></div>

                  <button
                    onClick={() => setIsHeaderExpanded(!isHeaderExpanded)}
                    className="p-2 hover:bg-gray-100 rounded-lg text-gray-500 transition-colors"
                  >
                    <svg
                      className={`w-5 h-5 transition-transform duration-200 ${
                        isHeaderExpanded ? "rotate-180" : ""
                      }`}
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M19 9l-7 7-7-7"
                      />
                    </svg>
                  </button>
                </div>
              </div>

              {/* Expanded Content */}
              {isHeaderExpanded && (
                <div className="px-6 pb-6 border-t border-gray-100 pt-6 animate-fade-in">
                  <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 md:gap-4">
                    <div className="bg-gradient-to-br from-blue-50 to-blue-100 rounded-xl p-4 border border-blue-200">
                      <div className="text-xs font-semibold text-blue-600 mb-1 uppercase tracking-wide">
                        📄 File
                      </div>
                      <div
                        className="text-sm font-bold text-gray-900 truncate"
                        title={transcription.filename}
                      >
                        {transcription.filename}
                      </div>
                    </div>
                    <div className="bg-gradient-to-br from-purple-50 to-purple-100 rounded-xl p-4 border border-purple-200">
                      <div className="text-xs font-semibold text-purple-600 mb-1 uppercase tracking-wide">
                        ⏱️ Duration
                      </div>
                      <div className="text-sm font-bold text-gray-900">
                        {transcription.transcription.duration}
                      </div>
                    </div>
                    <div className="bg-gradient-to-br from-cyan-50 to-cyan-100 rounded-xl p-4 border border-cyan-200">
                      <div className="text-xs font-semibold text-cyan-600 mb-1 uppercase tracking-wide">
                        🌐 Language
                      </div>
                      <div className="text-sm font-bold text-gray-900 uppercase">
                        {transcription.transcription.language}
                      </div>
                    </div>
                    <div className="bg-gradient-to-br from-emerald-50 to-emerald-100 rounded-xl p-4 border border-emerald-200">
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
                </div>
              )}
            </div>

            {/* New Three-Column Layout */}
            <div className="flex flex-col lg:flex-row flex-grow overflow-hidden w-full gap-4 mt-6">
              {/* Main Column: Video and Transcript/Summary */}
              <div
                className={`flex-grow flex flex-col xl:flex-row overflow-hidden gap-4 w-full`}
              >
                {/* Video Player (Top/Left) */}
                {videoUrl && (
                  <div className="bg-black rounded-xl shadow-lg border border-gray-300 overflow-hidden flex-shrink-0 w-full xl:w-3/5 flex flex-col">
                    <div className="w-full bg-black flex justify-center relative flex-grow items-center">
                      <video
                        ref={setVideoRef}
                        src={videoUrl}
                        className="w-full max-h-[50vh] xl:max-h-full object-none"
                        onTimeUpdate={() => {
                          if (!isVideoSeeking && videoRef) {
                            const currentTime = videoRef.currentTime;
                            if (displayedSegments.length > 0) {
                              const segments = displayedSegments;
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
                                className="w-6 h-6 text-gray-200 hover:text-white transition-colors"
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
                                className="w-6 h-6 text-gray-200 hover:text-white transition-colors"
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
                              className="w-5 h-5 text-gray-200 hover:text-white cursor-pointer transition-colors"
                              fill="none"
                              viewBox="0 0 24 24"
                              stroke="currentColor"
                              onClick={() => {
                                if (videoRef) {
                                  const newVolume = volume === 0 ? 1 : 0;
                                  // Volume is managed by useVideoPlayer hook
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
                          segments={displayedSegments}
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

                {/* Tabs for Transcript, Chat, and Summary */}
                <div className="bg-white rounded-xl shadow-md border border-gray-200 overflow-hidden flex-grow flex flex-col w-full xl:w-2/5">
                  <div className="flex border-b border-gray-200 sticky top-0 bg-gradient-to-r from-gray-50 to-white z-10">
                    <button
                      onClick={() => {
                        setShowSummary(false);
                        setShowChat(false);
                      }}
                      className={`flex-1 px-5 py-4 text-sm font-bold transition-all duration-200 relative ${
                        !showSummary && !showChat
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
                      {!showSummary && !showChat && (
                        <div className="absolute bottom-0 left-0 right-0 h-1 bg-gradient-to-r from-indigo-500 to-purple-600 rounded-t-full"></div>
                      )}
                    </button>
                    <button
                      onClick={() => {
                        setShowSummary(false);
                        setShowChat(true);
                      }}
                      className={`flex-1 px-5 py-4 text-sm font-bold transition-all duration-200 relative ${
                        showChat
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
                            d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z"
                          />
                        </svg>
                        Chat
                      </div>
                      {showChat && (
                        <div className="absolute bottom-0 left-0 right-0 h-1 bg-gradient-to-r from-indigo-500 to-purple-600 rounded-t-full"></div>
                      )}
                    </button>
                    <button
                      onClick={() => {
                        setShowSummary(true);
                        setShowChat(false);
                      }}
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
                    {!showSummary && !showChat && (
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

                            {/* Speaker Filter Dropdown */}
                            <div className="relative">
                              <button
                                onClick={() =>
                                  setSpeakerDropdownOpen(!speakerDropdownOpen)
                                }
                                className={`px-4 py-2 rounded-lg text-sm font-semibold transition-all duration-200 flex items-center gap-2 ${
                                  filteredSpeaker
                                    ? "bg-gradient-to-r from-indigo-500 to-indigo-600 text-white shadow-md hover:shadow-lg"
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
                                    d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z"
                                  />
                                </svg>
                                <span>
                                  {filteredSpeaker
                                    ? formatSpeakerLabel(filteredSpeaker)
                                    : "All Speakers"}
                                </span>
                                <span className="text-xs opacity-75">
                                  ({displayedSegments.length})
                                </span>
                                <svg
                                  className={`w-4 h-4 transition-transform ${
                                    speakerDropdownOpen ? "rotate-180" : ""
                                  }`}
                                  fill="none"
                                  stroke="currentColor"
                                  viewBox="0 0 24 24"
                                >
                                  <path
                                    strokeLinecap="round"
                                    strokeLinejoin="round"
                                    strokeWidth={2}
                                    d="M19 9l-7 7-7-7"
                                  />
                                </svg>
                              </button>

                              {/* Dropdown Menu */}
                              {speakerDropdownOpen && (
                                <div className="absolute left-0 mt-2 w-64 bg-white rounded-lg shadow-xl border border-gray-200 z-20 max-h-96 overflow-y-auto">
                                  {/* Show All option */}
                                  <button
                                    onClick={() => {
                                      setFilteredSpeaker(null);
                                      setSpeakerDropdownOpen(false);
                                    }}
                                    className={`w-full text-left px-4 py-3 hover:bg-gray-50 transition-colors flex items-center justify-between ${
                                      !filteredSpeaker ? "bg-blue-50" : ""
                                    }`}
                                  >
                                    <div className="flex items-center gap-2">
                                      <svg
                                        className="w-4 h-4 text-gray-600"
                                        fill="none"
                                        stroke="currentColor"
                                        viewBox="0 0 24 24"
                                      >
                                        <path
                                          strokeLinecap="round"
                                          strokeLinejoin="round"
                                          strokeWidth={2}
                                          d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z"
                                        />
                                      </svg>
                                      <span className="font-medium text-gray-900">
                                        All Speakers
                                      </span>
                                    </div>
                                    <span className="text-xs text-gray-500">
                                      {
                                        transcription?.transcription.segments
                                          .length
                                      }
                                    </span>
                                  </button>

                                  {/* Individual speakers */}
                                  {uniqueSpeakers.map((speaker) => {
                                    const speakerColors =
                                      getSpeakerColor(speaker);
                                    const segmentCount =
                                      transcription?.transcription.segments.filter(
                                        (seg) => seg.speaker === speaker
                                      ).length || 0;

                                    return (
                                      <button
                                        key={speaker}
                                        onClick={() => {
                                          setFilteredSpeaker(speaker);
                                          setSpeakerDropdownOpen(false);
                                        }}
                                        className={`w-full text-left px-4 py-3 hover:bg-gray-50 transition-colors flex items-center justify-between border-t border-gray-100 ${
                                          filteredSpeaker === speaker
                                            ? "bg-blue-50"
                                            : ""
                                        }`}
                                      >
                                        <div className="flex items-center gap-2">
                                          <span
                                            className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold border ${speakerColors.bg} ${speakerColors.text} ${speakerColors.border}`}
                                          >
                                            <svg
                                              className="w-3.5 h-3.5"
                                              fill="currentColor"
                                              viewBox="0 0 20 20"
                                            >
                                              <path
                                                fillRule="evenodd"
                                                d="M10 9a3 3 0 100-6 3 3 0 000 6zm-7 9a7 7 0 1114 0H3z"
                                                clipRule="evenodd"
                                              />
                                            </svg>
                                            {formatSpeakerLabel(speaker)}
                                          </span>
                                        </div>
                                        <span className="text-xs text-gray-500">
                                          {segmentCount}
                                        </span>
                                      </button>
                                    );
                                  })}
                                </div>
                              )}
                            </div>
                          </div>
                        </div>
                        {/* Transcript content */}
                        <TranscriptSegmentList
                          segments={displayedSegments}
                          activeSegmentId={activeSegmentId}
                          showTranslation={showTranslation}
                          seekToTimestamp={seekToTimestamp}
                          openImageModal={openImageModal}
                          editingSpeaker={editingSpeaker}
                          setEditingSpeaker={setEditingSpeaker}
                          editSpeakerName={editSpeakerName}
                          setEditSpeakerName={setEditSpeakerName}
                          handleSpeakerRename={handleSpeakerRename}
                          getSpeakerColor={getSpeakerColor}
                          formatSpeakerLabel={formatSpeakerLabel}
                        />
                      </>
                    )}

                    {/* Chat Panel */}
                    {showChat && (
                      <div className="h-full">
                        <ChatPanel
                          videoHash={transcription?.video_hash || null}
                          onTimestampClick={seekToTimestamp}
                        />
                      </div>
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
                <div className="w-full lg:w-1/4 lg:min-w-[250px] overflow-y-auto bg-white rounded-lg shadow-sm border border-gray-100 mt-4 lg:mt-0 lg:ml-4 hidden">
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
                    onClick={() => resetTranscriptionState()}
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
