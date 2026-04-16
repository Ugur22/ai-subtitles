import { useState, useEffect, useMemo, useRef, useCallback, Fragment } from "react";
import { Dialog, Transition } from "@headlessui/react";
import toast from "react-hot-toast";
import axios from "axios";
import { useJobs } from "../../../contexts/JobsContext";
import {
  type TranscriptionResponse,
  translateLocalText,
  updateSpeakerName,
  enrollSpeaker,
  autoIdentifySpeakers,
} from "../../../services/api";
import { API_BASE_URL } from "../../../config";
import {
  formatScreenshotUrl,
  formatScreenshotUrlSafe,
} from "../../../utils/url";
import { SubtitleControls } from "./SubtitleControls";
import { SearchPanel } from "../search/SearchPanel";
// import { AnalyticsPanel } from "../analytics/AnalyticsPanel";
import { SummaryPanel } from "../summary/SummaryPanel";
import { ChatPanel } from "../chat/ChatPanel";
import CustomProgressBar from "./CustomProgressBar";
import React from "react";
import {
  formatProcessingTime,
  convertTimeToSeconds,
  timeToSeconds,
} from "../../../utils/time";
import { formatSpeakerLabel, getSpeakerColor } from "../../../utils/speaker";
import { DraggableImageModal } from "../../common/DraggableImageModal";
import { JumpToTimeModal } from "./JumpToTimeModal";
import { ProcessingOverlay } from "./ProcessingOverlay";
import { TranscriptSegmentList } from "./TranscriptSegmentList";
import { UploadZone } from "./UploadZone";
import { RecentTranscriptions } from "./RecentTranscriptions";
import { Job } from "../../../types/job";
import { useFileUpload } from "../../../hooks/useFileUpload";
import { useVideoPlayer } from "../../../hooks/useVideoPlayer";
import { useSubtitles } from "../../../hooks/useSubtitles";
import { useTranscription } from "../../../hooks/useTranscription";
import { useSummaries } from "../../../hooks/useSummaries";
import { useChapters } from "../../../hooks/useChapters";
import { ChapterPanel } from "../chapters/ChapterPanel";
import { useBackgroundJobSubmit } from "../../../hooks/useBackgroundJobSubmit";
import { useJobTracker } from "../../../hooks/useJobTracker";
import { JobPanel } from "../jobs";

// Note: ProcessingStage type moved to useTranscription hook

// Add transcription method type
type TranscriptionMethod = "local" | "background";
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
  const [showSearch, setShowSearch] = useState(false);
  const [progressSimulation] = useState<NodeJS.Timeout | null>(null); // Unused but kept for future use
  const [activeSegmentId, setActiveSegmentId] = useState<string | null>(null);
  const [isNewTranscription, setIsNewTranscription] = useState(false);
  const [selectedLanguage, setSelectedLanguage] = useState<string>("");
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [modalImageUrl, setModalImageUrl] = useState<string | null>(null);
  const [transcriptionMethod, setTranscriptionMethod] =
    useState<TranscriptionMethod>("background");
  // Note: pollingIntervalRef removed - was unused after hook integration
  const [translationMethod] = useState<TranslationMethod>("none");
  const [jumpModalOpen, setJumpModalOpen] = useState(false);
  const [showScreenshots] = useState(false); // Unused but kept for future use
  const [editingSegmentId, setEditingSegmentId] = useState<string | null>(null);
  const [editSpeakerName, setEditSpeakerName] = useState("");
  const [isRenamingSpeaker, setIsRenamingSpeaker] = useState(false);
  const [filteredSpeaker, setFilteredSpeaker] = useState<string | null>(null);
  const [speakerDropdownOpen, setSpeakerDropdownOpen] = useState(false);
  const [showVisualMoments, setShowVisualMoments] = useState(true);
  const [isHeaderExpanded, setIsHeaderExpanded] = useState(false);
  const [showChapters, setShowChapters] = useState(false);

  // Speaker enrollment modal state
  const [enrollModalSegment, setEnrollModalSegment] = useState<any>(null);
  const [enrollSpeakerName, setEnrollSpeakerName] = useState('');
  const [enrollSubmitting, setEnrollSubmitting] = useState(false);

  // Auto-identify confirmation state
  const [autoIdentifyConfirmOpen, setAutoIdentifyConfirmOpen] = useState(false);
  const [autoIdentifyRunning, setAutoIdentifyRunning] = useState(false);

  // Enrolled speakers in speakers dropdown
  const [enrolledSpeakers, setEnrolledSpeakers] = useState<{name: string, samples_count: number}[]>([]);
  const [enrolledLoading, setEnrolledLoading] = useState(false);
  const [showEnrolledInDropdown, setShowEnrolledInDropdown] = useState(false);
  const [confirmingDeleteEnrolled, setConfirmingDeleteEnrolled] = useState<string | null>(null);

  // Jobs context — shares active count + panel state with Header
  const { setActiveJobCount, showJobPanel, setShowJobPanel } = useJobs();

  // Initialize job tracker for background processing
  const jobTracker = useJobTracker();
  const backgroundJobSubmit = useBackgroundJobSubmit(() => {
    // Refetch jobs when a new job is submitted
    jobTracker.refetch();
  });

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
    currentTime,
    isPlaying,
    volume,
    isVideoSeeking,
    handlePlayPause,
    handleVolumeChange,
    seek,
    play,
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

  const chaptersHook = useChapters({
    videoHash: transcription?.video_hash,
  });

  // Computed values
  const isTranscribing =
    processingStatus !== null && processingStatus.stage !== "complete";

  // Filter segments by selected speaker, optionally including visual moments
  const displayedSegments = useMemo(() => {
    if (!transcription) return [];
    const segments = transcription.transcription.segments;

    // No speaker filter - show all, but respect visual moments toggle
    if (!filteredSpeaker) {
      if (showVisualMoments) return segments;
      return segments.filter((seg) => !seg.is_silent);
    }

    // With speaker filter - include visual moments if toggle is on
    return segments.filter(
      (seg) =>
        seg.speaker === filteredSpeaker || (showVisualMoments && seg.is_silent)
    );
  }, [transcription, filteredSpeaker, showVisualMoments]);

  // Use a ref to track displayedSegments to avoid unnecessary effect re-runs
  const displayedSegmentsRef = useRef(displayedSegments);
  useEffect(() => {
    displayedSegmentsRef.current = displayedSegments;
  }, [displayedSegments]);

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

  // Sync active job count to header via context
  useEffect(() => {
    const activeCount = jobTracker.jobs.filter(
      (j) => j.status === "processing" || j.status === "pending"
    ).length;
    setActiveJobCount(activeCount);
  }, [jobTracker.jobs, setActiveJobCount]);

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

    // Convert language name to ISO code
    const languageCodeMap: Record<string, string> = {
      spanish: "es",
      italian: "it",
      french: "fr",
      german: "de",
      english: "en",
      portuguese: "pt",
      russian: "ru",
      chinese: "zh",
      japanese: "ja",
      korean: "ko",
    };
    const languageCode =
      languageCodeMap[selectedLanguage.toLowerCase()] || selectedLanguage;

    // Handle background processing mode
    if (transcriptionMethod === "background") {
      try {
        const result = await backgroundJobSubmit.submit(file, {
          language: languageCode || undefined,
          forceLanguage: true,
        });

        if (result) {
          // Show success message and open job panel
          setShowJobPanel(true);

          // If cached result, load it immediately
          if (result.cached) {
            // The job already has results, refetch to get the full data
            jobTracker.refetch();
          }
        }
      } catch (error) {
        // Error is already set in backgroundJobSubmit state
        console.error("Background job submission failed:", error);
      }
      return;
    }

    // Use the hook's handleStartTranscription for local processing
    await handleStartTranscription(
      file,
      transcriptionMethod as "local",
      selectedLanguage
    );
  };

  const handleViewTranscript = useCallback((job: Job) => {
    if (job.result_json) {
      setTranscription(job.result_json);
      setVideoUrl(
        `${API_BASE_URL}/api/jobs/${job.job_id}/video?token=${job.access_token}`
      );
      setShowJobPanel(false);
    }
  }, [setTranscription, setVideoUrl, setShowJobPanel]);

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

    setIsRenamingSpeaker(true);
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

      setEditingSegmentId(null);
      setEditSpeakerName("");
    } catch (err) {
      console.error("Failed to rename speaker:", err);
      alert("Failed to rename speaker");
    } finally {
      setIsRenamingSpeaker(false);
    }
  };

  // Speaker Recognition Handlers
  const handleEnrollSpeaker = (segment: any) => {
    setEnrollSpeakerName(formatSpeakerLabel(segment.speaker));
    setEnrollModalSegment(segment);
  };

  const handleEnrollConfirm = async () => {
    if (!enrollModalSegment || !transcription || !enrollSpeakerName.trim()) return;
    setEnrollSubmitting(true);
    try {
      const startTime = timeToSeconds(enrollModalSegment.start_time);
      const endTime = timeToSeconds(enrollModalSegment.end_time);
      await enrollSpeaker(
        enrollSpeakerName.trim(),
        transcription.video_hash,
        startTime,
        endTime
      );
      toast.success(`${enrollSpeakerName.trim()} enrolled successfully`);
      setEnrollModalSegment(null);
      setEnrollSpeakerName('');
    } catch (err: any) {
      console.error("Failed to enroll speaker:", err);
      toast.error(err.message || "Failed to enroll speaker");
    } finally {
      setEnrollSubmitting(false);
    }
  };

  const handleAutoIdentifySpeakers = () => {
    if (!transcription) return;
    setAutoIdentifyConfirmOpen(true);
    setSpeakerDropdownOpen(false);
  };

  const handleAutoIdentifyConfirm = async () => {
    if (!transcription) return;
    setAutoIdentifyRunning(true);
    try {
      const result = await autoIdentifySpeakers(transcription.video_hash, 0.7);
      toast.success(
        `Identified ${result.identified_segments}/${result.total_segments} segments — refreshing…`,
        { duration: 3000 }
      );
      setAutoIdentifyConfirmOpen(false);
      setTimeout(() => window.location.reload(), 1500);
    } catch (err: any) {
      console.error("Failed to auto-identify speakers:", err);
      toast.error(err.message || "Failed to auto-identify speakers");
      setAutoIdentifyRunning(false);
    }
  };

  const fetchEnrolledSpeakers = async () => {
    setEnrolledLoading(true);
    try {
      const response = await axios.get(`${API_BASE_URL}/api/speaker/list`);
      setEnrolledSpeakers(response.data.speakers || []);
    } catch (e) {
      console.error("Failed to fetch enrolled speakers:", e);
    } finally {
      setEnrolledLoading(false);
    }
  };

  const handleDeleteEnrolledSpeaker = async (name: string) => {
    try {
      await axios.delete(`${API_BASE_URL}/api/speaker/${name}`);
      setConfirmingDeleteEnrolled(null);
      await fetchEnrolledSpeakers();
    } catch (e) {
      toast.error("Failed to remove speaker");
    }
  };

  const seekToTimestamp = (timeString: string) => {
    if (!timeString) return;

    const seconds = timeToSeconds(timeString);
    seek(seconds);
    play();

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


  const handleSearchClick = () => {
    setShowSearch(!showSearch);
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
        // Use ref to avoid unnecessary effect re-runs when displayedSegments changes
        if (displayedSegmentsRef.current.length > 0) {
          const currentTime = videoRef.currentTime;
          const segments = displayedSegmentsRef.current;
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
  }, [videoRef]);

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
    <div className="relative min-h-screen" style={{ backgroundColor: 'var(--bg-base)' }}>
      {/* Processing overlay when transcribing */}
      <ProcessingOverlay
        isVisible={isTranscribing}
        processingStatus={processingStatus}
        elapsedTime={elapsedTime}
        file={file}
        videoRef={videoRef}
      />
      <div className="h-full px-4" style={{ color: 'var(--text-primary)' }}>
        {/* Upload Section */}
        {!transcription && (
          <div style={{ paddingBottom: '64px' }}>
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
              isNewTranscription={isNewTranscription}
              processingStatus={processingStatus}
              elapsedTime={elapsedTime}
              languageOptions={languageOptions}
            />
            <RecentTranscriptions
              jobs={jobTracker.jobs}
              onViewJob={handleViewTranscript}
              onViewAll={() => setShowJobPanel(true)}
            />
          </div>
        )}

        {/* Results Section */}
        {transcription && (
          <div className="h-screen flex flex-col overflow-hidden w-full" style={{ gap: '8px' }}>
            {/* Flat results top bar */}
            <div
              className="flex-shrink-0"
              style={{
                borderBottom: '1px solid var(--border-subtle)',
                backgroundColor: 'var(--bg-subtle)',
                borderRadius: '6px',
              }}
            >
              {/* Always-visible row */}
              <div style={{ padding: '8px 12px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px' }}>
                {/* Left: file name + meta badges */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px', minWidth: 0, flex: 1 }}>
                  <h2
                    style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '320px' }}
                    title={transcription.filename}
                  >
                    {transcription.filename}
                  </h2>
                  {!isHeaderExpanded && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexShrink: 0 }}>
                      <span className="badge badge-default" style={{ fontVariantNumeric: 'tabular-nums' }}>
                        {transcription.transcription.duration}
                      </span>
                      <span className="badge badge-default" style={{ textTransform: 'uppercase' }}>
                        {transcription.transcription.language}
                      </span>
                    </div>
                  )}
                </div>

                {/* Right: actions */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '2px', flexShrink: 0 }}>
                  <button
                    onClick={handleSearchClick}
                    className="btn-ghost"
                    style={{
                      padding: '6px',
                      color: showSearch ? 'var(--accent)' : 'var(--text-secondary)',
                      backgroundColor: showSearch ? 'var(--accent-dim)' : 'transparent',
                    }}
                    title={showSearch ? "Hide search" : "Show search"}
                  >
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                    </svg>
                  </button>

                  <button
                    onClick={startNewTranscription}
                    className="btn-ghost"
                    style={{ padding: '6px', color: 'var(--text-secondary)' }}
                    title="New transcription"
                  >
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <polyline points="23 4 23 10 17 10"></polyline>
                      <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path>
                    </svg>
                  </button>

                  <div style={{ width: '1px', height: '16px', backgroundColor: 'var(--border-subtle)', margin: '0 4px' }} />

                  <SubtitleControls
                    filename={transcription.filename}
                    videoHash={transcription.video_hash}
                  />

                  <div style={{ width: '1px', height: '16px', backgroundColor: 'var(--border-subtle)', margin: '0 4px' }} />

                  <button
                    onClick={() => setIsHeaderExpanded(!isHeaderExpanded)}
                    className="btn-ghost"
                    style={{ padding: '6px', color: 'var(--text-secondary)' }}
                  >
                    <svg
                      className="w-4 h-4"
                      style={{ transition: 'transform 200ms ease', transform: isHeaderExpanded ? 'rotate(180deg)' : 'rotate(0deg)' }}
                      fill="none" viewBox="0 0 24 24" stroke="currentColor"
                    >
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19 9l-7 7-7-7" />
                    </svg>
                  </button>
                </div>
              </div>

              {/* Expanded stats */}
              {isHeaderExpanded && (
                <div
                  className="animate-fade-in"
                  style={{ padding: '12px', borderTop: '1px solid var(--border-subtle)', display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '1px', backgroundColor: 'var(--border-subtle)' }}
                >
                  {[
                    { label: 'File', value: transcription.filename, title: transcription.filename, truncate: true },
                    { label: 'Duration', value: transcription.transcription.duration },
                    { label: 'Language', value: transcription.transcription.language?.toUpperCase() },
                    { label: 'Processing', value: formatProcessingTime(transcription.transcription.processing_time) },
                  ].map(({ label, value, title, truncate }) => (
                    <div key={label} style={{ backgroundColor: 'var(--bg-surface)', padding: '10px 12px' }}>
                      <div style={{ fontSize: '10px', fontWeight: 500, color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '4px' }}>
                        {label}
                      </div>
                      <div
                        style={{ fontSize: '13px', fontWeight: 500, color: 'var(--text-primary)', ...(truncate ? { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } : {}) }}
                        title={title}
                      >
                        {value}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Three-Column Layout */}
            <div className="flex flex-col lg:flex-row flex-grow overflow-hidden w-full" style={{ gap: '8px' }}>
              {/* Main Column: Video and Transcript/Summary */}
              <div
                className={`flex-grow flex flex-col xl:flex-row overflow-hidden gap-4 w-full`}
              >
                {/* Video Player (Top/Left) */}
                {videoUrl && (
                  <div
                    className="overflow-hidden flex-shrink-0 w-full xl:w-3/4 flex flex-col"
                    style={{ backgroundColor: '#000', borderRadius: '6px', border: '1px solid var(--border-subtle)' }}
                  >
                    <div className="w-full bg-black flex justify-center relative flex-grow items-center">
                      <video
                        ref={setVideoRef}
                        src={videoUrl}
                        className="w-full h-full max-h-[70vh] xl:max-h-[80vh] object-contain"
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
                                className="w-6 h-6"
                                style={{ color: 'var(--text-secondary)', transition: 'color 100ms ease' }}
                                fill="currentColor"
                                viewBox="0 0 24 24"
                                onMouseEnter={e => (e.currentTarget as SVGElement).style.color = 'var(--text-primary)'}
                                onMouseLeave={e => (e.currentTarget as SVGElement).style.color = 'var(--text-secondary)'}
                              >
                                <rect x="6" y="4" width="4" height="16" rx="1" />
                                <rect x="14" y="4" width="4" height="16" rx="1" />
                              </svg>
                            ) : (
                              <svg
                                className="w-6 h-6"
                                style={{ color: 'var(--text-secondary)', transition: 'color 100ms ease' }}
                                fill="currentColor"
                                viewBox="0 0 24 24"
                                onMouseEnter={e => (e.currentTarget as SVGElement).style.color = 'var(--text-primary)'}
                                onMouseLeave={e => (e.currentTarget as SVGElement).style.color = 'var(--text-secondary)'}
                              >
                                <path d="M8 5v14l11-7z" />
                              </svg>
                            )}
                          </button>

                          {/* Volume Control */}
                          <div className="flex items-center space-x-2">
                            <svg
                              className="w-5 h-5 cursor-pointer"
                              style={{ color: 'var(--text-secondary)', transition: 'color 100ms ease' }}
                              onMouseEnter={e => (e.currentTarget as SVGElement).style.color = 'var(--text-primary)'}
                              onMouseLeave={e => (e.currentTarget as SVGElement).style.color = 'var(--text-secondary)'}
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
                              style={{
                                width: '72px',
                                height: '3px',
                                appearance: 'none',
                                cursor: 'pointer',
                                backgroundColor: 'var(--border-default)',
                                borderRadius: '2px',
                                accentColor: 'var(--accent)',
                              }}
                            />
                          </div>
                        </div>
                        <CustomProgressBar
                          videoRef={videoRef}
                          duration={
                            videoRef && videoRef.duration > 0
                              ? videoRef.duration
                              : 0
                          }
                          currentTime={currentTime}
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
                              ? formatScreenshotUrl(closest.screenshot_url) ??
                                  null
                              : null;
                          }}
                          onSeek={(time: number) => {
                            seek(time);
                          }}
                          chapters={chaptersHook.chapters.map(ch => ({ start: ch.start, title: ch.title }))}
                        />
                        <div className="flex justify-end px-4 pb-2">
                          <button
                            className="btn-ghost"
                            style={{ fontSize: '12px', padding: '4px 8px' }}
                            onClick={() => setJumpModalOpen(true)}
                            title="Jump to a specific timestamp (Ctrl+J)"
                          >
                            Jump to time
                          </button>
                        </div>
                        <JumpToTimeModal
                          isOpen={jumpModalOpen}
                          onClose={() => setJumpModalOpen(false)}
                          onJump={(seconds) => {
                            seek(seconds);
                          }}
                          duration={
                            videoRef && videoRef.duration > 0
                              ? videoRef.duration
                              : 0
                          }
                          currentTime={currentTime}
                        />
                      </>
                    )}
                  </div>
                )}

                {/* Tabs for Transcript, Chat, Chapters, Summary */}
                <div
                  className="overflow-hidden flex-grow flex flex-col w-full xl:w-1/4"
                  style={{ backgroundColor: 'var(--bg-subtle)', borderRadius: '6px', border: '1px solid var(--border-subtle)' }}
                >
                  {/* Tab bar */}
                  <div
                    style={{
                      display: 'flex',
                      borderBottom: '1px solid var(--border-subtle)',
                      backgroundColor: 'var(--bg-subtle)',
                      position: 'sticky',
                      top: 0,
                      zIndex: 10,
                    }}
                  >
                    {[
                      { key: 'transcript', label: 'Transcript', active: !showSummary && !showChat && !showChapters, onClick: () => { setShowSummary(false); setShowChat(false); setShowChapters(false); } },
                      { key: 'chat',       label: 'Chat',       active: showChat,       onClick: () => { setShowSummary(false); setShowChat(true);  setShowChapters(false); } },
                      { key: 'chapters',   label: 'Chapters',   active: showChapters,   onClick: () => { setShowSummary(false); setShowChat(false); setShowChapters(true);  } },
                      { key: 'summary',    label: 'Summary',    active: showSummary,    onClick: () => { setShowSummary(true);  setShowChat(false); setShowChapters(false); } },
                    ].map(({ key, label, active, onClick }) => (
                      <button
                        key={key}
                        onClick={onClick}
                        style={{
                          flex: 1,
                          padding: '10px 4px',
                          fontSize: '12px',
                          fontWeight: active ? 600 : 400,
                          color: active ? 'var(--text-primary)' : 'var(--text-tertiary)',
                          borderBottom: active ? '2px solid var(--accent)' : '2px solid transparent',
                          transition: 'color 150ms ease, border-color 150ms ease',
                          backgroundColor: 'transparent',
                          cursor: 'pointer',
                        }}
                        onMouseEnter={e => { if (!active) (e.currentTarget as HTMLButtonElement).style.color = 'var(--text-secondary)'; }}
                        onMouseLeave={e => { if (!active) (e.currentTarget as HTMLButtonElement).style.color = 'var(--text-tertiary)'; }}
                      >
                        {label}
                      </button>
                    ))}
                  </div>

                  <div className="flex-grow overflow-auto relative">
                    {!showSummary && !showChat && !showChapters && (
                      <>
                        {/* Transcript toolbar */}
                        <div
                          className="sticky top-0 z-10 flex-wrap gap-2"
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            padding: '8px 10px',
                            borderBottom: '1px solid var(--border-subtle)',
                            backgroundColor: 'var(--bg-subtle)',
                          }}
                        >
                          <div className="flex items-center gap-2 flex-wrap">
                            <button
                              onClick={() => setShowTranslation(!showTranslation)}
                              className="btn-ghost"
                              style={{
                                padding: '4px 10px',
                                fontSize: '12px',
                                color: showTranslation ? 'var(--accent)' : 'var(--text-secondary)',
                                backgroundColor: showTranslation ? 'var(--accent-dim)' : 'transparent',
                              }}
                              title="Show translated text for each segment"
                            >
                              {showTranslation ? "Original" : "Translate"}
                            </button>

                            {/* Speaker Filter Dropdown */}
                            <div className="relative">
                              <button
                                onClick={() => setSpeakerDropdownOpen(!speakerDropdownOpen)}
                                className="btn-ghost"
                                style={{
                                  padding: '4px 10px',
                                  fontSize: '12px',
                                  color: filteredSpeaker ? 'var(--accent)' : 'var(--text-secondary)',
                                  backgroundColor: filteredSpeaker ? 'var(--accent-dim)' : 'transparent',
                                  display: 'flex', alignItems: 'center', gap: '6px',
                                }}
                              >
                                <span>{filteredSpeaker ? formatSpeakerLabel(filteredSpeaker) : 'Speakers'}</span>
                                <span style={{ opacity: 0.6 }}>({displayedSegments.length})</span>
                                <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" style={{ transform: speakerDropdownOpen ? 'rotate(180deg)' : 'rotate(0)', transition: 'transform 150ms ease' }}>
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                                </svg>
                              </button>

                              {/* Dropdown Menu */}
                              {speakerDropdownOpen && (
                                <div
                                  className="absolute left-0 mt-1 z-20 rounded-md"
                                  style={{
                                    width: '240px',
                                    backgroundColor: 'var(--bg-overlay)',
                                    border: '1px solid var(--border-subtle)',
                                    boxShadow: '0 8px 24px oklch(0% 0 0 / 0.5)',
                                  }}
                                >
                                  {/* Filter section */}
                                  <div style={{ maxHeight: '220px', overflowY: 'auto' }}>
                                    {/* Show All option */}
                                    <button
                                      onClick={() => { setFilteredSpeaker(null); setSpeakerDropdownOpen(false); }}
                                      style={{
                                        display: 'flex', width: '100%', textAlign: 'left',
                                        padding: '8px 12px', fontSize: '13px',
                                        color: !filteredSpeaker ? 'var(--accent)' : 'var(--text-secondary)',
                                        backgroundColor: !filteredSpeaker ? 'var(--accent-dim)' : 'transparent',
                                        alignItems: 'center', justifyContent: 'space-between',
                                      }}
                                    >
                                      <span style={{ fontWeight: 500 }}>All speakers</span>
                                      <span style={{ fontSize: '11px', color: 'var(--text-tertiary)' }}>
                                        {transcription?.transcription.segments.length}
                                      </span>
                                    </button>

                                    {/* Individual speakers */}
                                    {uniqueSpeakers.map((speaker) => {
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
                                          style={{
                                            width: '100%',
                                            textAlign: 'left',
                                            padding: '8px 14px',
                                            display: 'flex',
                                            alignItems: 'center',
                                            justifyContent: 'space-between',
                                            borderTop: '1px solid var(--border-subtle)',
                                            backgroundColor: filteredSpeaker === speaker ? 'var(--accent-dim)' : 'transparent',
                                            cursor: 'pointer',
                                            transition: 'background-color 100ms ease',
                                          }}
                                          onMouseEnter={e => { if (filteredSpeaker !== speaker) (e.currentTarget as HTMLButtonElement).style.backgroundColor = 'var(--bg-surface)'; }}
                                          onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.backgroundColor = filteredSpeaker === speaker ? 'var(--accent-dim)' : 'transparent'; }}
                                        >
                                          <div className="flex items-center gap-2">
                                            <span style={{
                                              display: 'inline-flex', alignItems: 'center', gap: '6px',
                                              padding: '2px 8px', borderRadius: '9999px',
                                              fontSize: '11px', fontWeight: 600,
                                              backgroundColor: filteredSpeaker === speaker ? 'var(--accent)' : 'var(--bg-overlay)',
                                              color: filteredSpeaker === speaker ? 'var(--accent-text)' : 'var(--text-secondary)',
                                              border: '1px solid var(--border-default)',
                                            }}>
                                              <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
                                                <path fillRule="evenodd" d="M10 9a3 3 0 100-6 3 3 0 000 6zm-7 9a7 7 0 1114 0H3z" clipRule="evenodd" />
                                              </svg>
                                              {formatSpeakerLabel(speaker)}
                                            </span>
                                          </div>
                                          <span style={{ fontSize: '11px', color: 'var(--text-tertiary)' }}>
                                            {segmentCount}
                                          </span>
                                        </button>
                                      );
                                    })}
                                  </div>

                                  {/* Speaker tools section */}
                                  <div style={{ borderTop: '1px solid var(--border-subtle)' }}>
                                    <p style={{ padding: '6px 12px 4px', fontSize: '10px', fontWeight: 600, color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                                      Speaker tools
                                    </p>

                                    {/* Auto-identify */}
                                    <button
                                      onClick={handleAutoIdentifySpeakers}
                                      style={{
                                        width: '100%', textAlign: 'left',
                                        padding: '7px 12px', fontSize: '12px',
                                        color: 'var(--text-secondary)',
                                        display: 'flex', alignItems: 'center', gap: '8px',
                                        transition: 'background-color 100ms ease',
                                      }}
                                      onMouseEnter={e => (e.currentTarget as HTMLButtonElement).style.backgroundColor = 'var(--bg-surface)'}
                                      onMouseLeave={e => (e.currentTarget as HTMLButtonElement).style.backgroundColor = 'transparent'}
                                      title="Automatically identify speakers using enrolled voice prints"
                                    >
                                      <svg className="w-3.5 h-3.5" style={{ color: 'var(--text-tertiary)', flexShrink: 0 }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
                                      </svg>
                                      Auto-identify speakers
                                    </button>

                                    {/* Enrolled speakers toggle */}
                                    <button
                                      onClick={() => {
                                        const next = !showEnrolledInDropdown;
                                        setShowEnrolledInDropdown(next);
                                        if (next) fetchEnrolledSpeakers();
                                      }}
                                      style={{
                                        width: '100%', textAlign: 'left',
                                        padding: '7px 12px', fontSize: '12px',
                                        color: showEnrolledInDropdown ? 'var(--accent)' : 'var(--text-secondary)',
                                        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                                        transition: 'background-color 100ms ease',
                                      }}
                                      onMouseEnter={e => (e.currentTarget as HTMLButtonElement).style.backgroundColor = 'var(--bg-surface)'}
                                      onMouseLeave={e => (e.currentTarget as HTMLButtonElement).style.backgroundColor = 'transparent'}
                                    >
                                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                        <svg className="w-3.5 h-3.5" style={{ color: 'var(--text-tertiary)', flexShrink: 0 }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
                                        </svg>
                                        Enrolled speakers
                                        {enrolledSpeakers.length > 0 && (
                                          <span style={{ fontSize: '10px', color: 'var(--text-tertiary)', background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', borderRadius: '9999px', padding: '0 5px' }}>
                                            {enrolledSpeakers.length}
                                          </span>
                                        )}
                                      </div>
                                      <svg
                                        className="w-3 h-3"
                                        style={{ color: 'var(--text-tertiary)', transform: showEnrolledInDropdown ? 'rotate(180deg)' : 'rotate(0)', transition: 'transform 150ms ease' }}
                                        fill="none" stroke="currentColor" viewBox="0 0 24 24"
                                      >
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                                      </svg>
                                    </button>

                                    {/* Enrolled speakers list */}
                                    {showEnrolledInDropdown && (
                                      <div style={{ borderTop: '1px solid var(--border-subtle)', maxHeight: '200px', overflowY: 'auto' }}>
                                        {enrolledLoading ? (
                                          <div style={{ display: 'flex', justifyContent: 'center', padding: '16px 0' }}>
                                            <div className="animate-spin" style={{ width: '16px', height: '16px', border: '2px solid var(--border-default)', borderTopColor: 'var(--accent)', borderRadius: '50%' }} />
                                          </div>
                                        ) : enrolledSpeakers.length === 0 ? (
                                          <p style={{ padding: '12px', fontSize: '11px', color: 'var(--text-tertiary)', textAlign: 'center' }}>
                                            No enrolled speakers. Click "Enroll" on a segment.
                                          </p>
                                        ) : (
                                          enrolledSpeakers.map(sp => (
                                            <div key={sp.name}>
                                              {confirmingDeleteEnrolled === sp.name ? (
                                                <div style={{ padding: '7px 12px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', backgroundColor: 'oklch(65% 0.20 25 / 0.06)' }}>
                                                  <span style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>Remove <strong style={{ color: 'var(--text-primary)' }}>{sp.name}</strong>?</span>
                                                  <div style={{ display: 'flex', gap: '6px' }}>
                                                    <button onClick={() => handleDeleteEnrolledSpeaker(sp.name)} style={{ fontSize: '11px', fontWeight: 600, color: 'var(--c-error)', background: 'none', border: 'none', cursor: 'pointer' }}>Yes</button>
                                                    <button onClick={() => setConfirmingDeleteEnrolled(null)} style={{ fontSize: '11px', color: 'var(--text-tertiary)', background: 'none', border: 'none', cursor: 'pointer' }}>No</button>
                                                  </div>
                                                </div>
                                              ) : (
                                                <div
                                                  style={{ padding: '7px 12px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px' }}
                                                  onMouseEnter={e => (e.currentTarget as HTMLDivElement).style.backgroundColor = 'var(--bg-surface)'}
                                                  onMouseLeave={e => (e.currentTarget as HTMLDivElement).style.backgroundColor = 'transparent'}
                                                >
                                                  <div>
                                                    <span style={{ fontSize: '12px', fontWeight: 500, color: 'var(--text-primary)' }}>{sp.name}</span>
                                                    <span style={{ fontSize: '10px', color: 'var(--text-tertiary)', marginLeft: '6px' }}>{sp.samples_count} sample{sp.samples_count !== 1 ? 's' : ''}</span>
                                                  </div>
                                                  <button
                                                    onClick={() => setConfirmingDeleteEnrolled(sp.name)}
                                                    style={{ background: 'none', border: 'none', cursor: 'pointer', padding: '2px', flexShrink: 0 }}
                                                    title="Remove enrolled speaker"
                                                  >
                                                    <svg className="w-3.5 h-3.5" style={{ color: 'var(--text-tertiary)' }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                                                    </svg>
                                                  </button>
                                                </div>
                                              )}
                                            </div>
                                          ))
                                        )}
                                      </div>
                                    )}
                                  </div>
                                </div>
                              )}
                            </div>

                            {/* Visual Moments Toggle */}
                            <button
                              onClick={() => setShowVisualMoments(!showVisualMoments)}
                              className="btn-ghost"
                              style={{
                                padding: '4px 10px',
                                fontSize: '12px',
                                color: showVisualMoments ? 'var(--accent)' : 'var(--text-secondary)',
                                backgroundColor: showVisualMoments ? 'var(--accent-dim)' : 'transparent',
                              }}
                              title="Show visual-only segments (silent frames captured from the video)"
                            >
                              <span>Scenes</span>
                            </button>
                          </div>
                        </div>
                        {/* Transcript content */}
                        <TranscriptSegmentList
                          segments={displayedSegments}
                          activeSegmentId={activeSegmentId}
                          showTranslation={showTranslation}
                          seekToTimestamp={seekToTimestamp}
                          openImageModal={openImageModal}
                          editingSegmentId={editingSegmentId}
                          setEditingSegmentId={setEditingSegmentId}
                          editSpeakerName={editSpeakerName}
                          setEditSpeakerName={setEditSpeakerName}
                          handleSpeakerRename={handleSpeakerRename}
                          isRenamingSpeaker={isRenamingSpeaker}
                          getSpeakerColor={getSpeakerColor}
                          formatSpeakerLabel={formatSpeakerLabel}
                          onEnrollSpeaker={handleEnrollSpeaker}
                        />
                      </>
                    )}

                    {/* Chat Panel */}
                    {showChat && (
                      <div style={{ position: 'absolute', inset: 0 }}>
                        <ChatPanel
                          videoHash={transcription?.video_hash || null}
                          onTimestampClick={seekToTimestamp}
                        />
                      </div>
                    )}

                    {/* Chapters Panel */}
                    {showChapters && (
                      <div style={{ position: 'absolute', inset: 0 }}>
                        <ChapterPanel
                          chapters={chaptersHook.chapters}
                          loading={chaptersHook.loading}
                          error={chaptersHook.error}
                          onGenerate={() => chaptersHook.generate()}
                          onSeekTo={seekToTimestamp}
                        />
                      </div>
                    )}

                    {/* Summary Panel */}
                    {showSummary && (
                      <div style={{ position: 'absolute', inset: 0 }}>
                        <SummaryPanel
                          isVisible={showSummary}
                          onSeekTo={seekToTimestamp}
                          summaries={summaries}
                          setSummaries={setSummaries}
                          loading={summaryLoading}
                          generateSummaries={generateSummaries}
                          videoHash={transcription?.video_hash}
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
                                    openImageModal(
                                      formatScreenshotUrlSafe(
                                        summary.screenshot_url
                                      )
                                    )
                                  }
                                >
                                  <img
                                    src={formatScreenshotUrlSafe(
                                      summary.screenshot_url
                                    )}
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
                  className="w-full lg:w-1/4 lg:min-w-[250px] overflow-y-auto mt-4 lg:mt-0 lg:ml-4"
                  style={{ backgroundColor: 'var(--bg-subtle)', borderRadius: '6px', border: '1px solid var(--border-subtle)' }}
                >
                  <div className="sticky top-0 z-10" style={{ backgroundColor: 'var(--bg-subtle)', borderBottom: '1px solid var(--border-subtle)' }}>
                    <div className="px-4 py-3 flex items-center justify-between">
                      <h3 style={{ fontSize: '13px', fontWeight: 500, color: 'var(--text-secondary)' }}>
                        Search & Analysis
                      </h3>
                    </div>
                  </div>

                  <div className="p-4 overflow-y-auto h-full">
                    <SearchPanel
                      onSeekToTimestamp={seekToTimestamp}
                      videoHash={transcription?.video_hash}
                      onImageClick={openImageModal}
                    />
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Error Display */}
        {error && (
          <div
            className="mt-6 w-full"
            style={{
              padding: '12px 16px',
              borderRadius: '6px',
              backgroundColor: 'oklch(65% 0.20 25 / 0.08)',
              border: '1px solid oklch(65% 0.20 25 / 0.3)',
              display: 'flex',
              alignItems: 'flex-start',
              gap: '12px',
            }}
          >
            <svg style={{ width: '16px', height: '16px', color: 'var(--c-error)', flexShrink: 0, marginTop: '1px' }} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="10"></circle>
              <line x1="12" y1="8" x2="12" y2="12"></line>
              <line x1="12" y1="16" x2="12.01" y2="16"></line>
            </svg>
            <div style={{ flex: 1 }}>
              <p style={{ fontSize: '13px', fontWeight: 500, color: 'var(--c-error)', marginBottom: '2px' }}>Transcription failed</p>
              <p style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>{error}</p>
              <button
                onClick={() => resetTranscriptionState()}
                style={{ marginTop: '8px', fontSize: '12px', color: 'var(--accent)', background: 'none', border: 'none', cursor: 'pointer', padding: 0, fontWeight: 500 }}
              >
                Try again
              </button>
            </div>
          </div>
        )}

        {/* Image Modal */}
        {isModalOpen && modalImageUrl && (
          <DraggableImageModal
            imageUrl={modalImageUrl}
            onClose={() => setIsModalOpen(false)}
            videoHash={transcription?.video_hash}
            speakers={uniqueSpeakers}
          />
        )}

        {/* Spinner if isPolling is true */}
        {isPolling && (
          <div className="flex flex-col items-center justify-center mt-8">
            <div className="animate-spin rounded-full h-10 w-10 mb-4" style={{ border: '2px solid var(--border-default)', borderTopColor: 'var(--accent)' }}></div>
            <p style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
              Transcribing, please wait…
            </p>
          </div>
        )}
      </div>

      {/* Background Job Submission Progress Overlay */}
      {backgroundJobSubmit.isSubmitting && (
        <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ backgroundColor: 'oklch(11% 0.008 250 / 0.85)' }}>
          <div style={{ backgroundColor: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', borderRadius: '8px', padding: '28px 32px', maxWidth: '400px', width: '100%', margin: '0 16px' }}>
            <h3 style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '20px' }}>
              Submitting job
            </h3>
            <div style={{ marginBottom: '16px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                <span style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
                  {backgroundJobSubmit.progress?.message || "Preparing..."}
                </span>
                <span style={{ fontSize: '13px', color: 'var(--text-tertiary)', fontVariantNumeric: 'tabular-nums' }}>
                  {backgroundJobSubmit.progress?.progress || 0}%
                </span>
              </div>
              <div style={{ width: '100%', height: '3px', backgroundColor: 'var(--border-subtle)', borderRadius: '2px', overflow: 'hidden' }}>
                <div
                  style={{
                    height: '100%',
                    backgroundColor: 'var(--accent)',
                    borderRadius: '2px',
                    transition: 'width 300ms ease',
                    width: `${backgroundJobSubmit.progress?.progress || 0}%`,
                  }}
                />
              </div>
            </div>
            <p style={{ fontSize: '12px', color: 'var(--text-tertiary)' }}>
              {backgroundJobSubmit.progress?.stage === "hashing" && "Calculating file fingerprint…"}
              {backgroundJobSubmit.progress?.stage === "uploading" && "Uploading to cloud storage…"}
              {backgroundJobSubmit.progress?.stage === "submitting" && "Queuing for processing…"}
              {backgroundJobSubmit.progress?.stage === "complete" && "Done!"}
            </p>
          </div>
        </div>
      )}

      {/* Background Jobs Panel */}
      <JobPanel
        isOpen={showJobPanel}
        onClose={() => setShowJobPanel(false)}
        onViewTranscript={handleViewTranscript}
      />

      {/* Enroll Speaker Modal */}
      <Transition appear show={enrollModalSegment !== null} as={Fragment}>
        <Dialog as="div" className="relative z-50" onClose={() => { setEnrollModalSegment(null); setEnrollSpeakerName(''); }}>
          <Transition.Child
            as={Fragment}
            enter="ease-out duration-200" enterFrom="opacity-0" enterTo="opacity-100"
            leave="ease-in duration-150" leaveFrom="opacity-100" leaveTo="opacity-0"
          >
            <div className="fixed inset-0" style={{ backgroundColor: 'oklch(11% 0.008 250 / 0.75)' }} />
          </Transition.Child>
          <div className="fixed inset-0 flex items-center justify-center p-4">
            <Transition.Child
              as={Fragment}
              enter="ease-out duration-200" enterFrom="opacity-0 scale-95" enterTo="opacity-100 scale-100"
              leave="ease-in duration-150" leaveFrom="opacity-100 scale-100" leaveTo="opacity-0 scale-95"
            >
              <Dialog.Panel style={{ backgroundColor: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', borderRadius: '8px', padding: '24px', width: '100%', maxWidth: '360px', boxShadow: '0 16px 48px oklch(0% 0 0 / 0.6)' }}>
                <Dialog.Title style={{ fontSize: '14px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '6px' }}>
                  Enroll speaker
                </Dialog.Title>
                <p style={{ fontSize: '12px', color: 'var(--text-tertiary)', marginBottom: '16px' }}>
                  Save this voice segment as a named speaker for future identification.
                </p>
                <input
                  type="text"
                  value={enrollSpeakerName}
                  onChange={e => setEnrollSpeakerName(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') handleEnrollConfirm(); if (e.key === 'Escape') { setEnrollModalSegment(null); setEnrollSpeakerName(''); } }}
                  placeholder="Speaker name"
                  autoFocus
                  style={{
                    width: '100%', padding: '8px 10px', fontSize: '13px',
                    backgroundColor: 'var(--bg-overlay)', border: '1px solid var(--border-default)',
                    borderRadius: '5px', color: 'var(--text-primary)', outline: 'none',
                    marginBottom: '16px',
                  }}
                  onFocus={e => (e.currentTarget.style.borderColor = 'var(--accent)')}
                  onBlur={e => (e.currentTarget.style.borderColor = 'var(--border-default)')}
                />
                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
                  <button
                    onClick={() => { setEnrollModalSegment(null); setEnrollSpeakerName(''); }}
                    className="btn-ghost"
                    style={{ padding: '6px 14px', fontSize: '13px' }}
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleEnrollConfirm}
                    disabled={enrollSubmitting || !enrollSpeakerName.trim()}
                    className="btn-primary"
                    style={{ padding: '6px 14px', fontSize: '13px', opacity: enrollSubmitting || !enrollSpeakerName.trim() ? 0.5 : 1 }}
                  >
                    {enrollSubmitting ? 'Enrolling…' : 'Enroll'}
                  </button>
                </div>
              </Dialog.Panel>
            </Transition.Child>
          </div>
        </Dialog>
      </Transition>

      {/* Auto-identify Confirmation Modal */}
      <Transition appear show={autoIdentifyConfirmOpen} as={Fragment}>
        <Dialog as="div" className="relative z-50" onClose={() => { if (!autoIdentifyRunning) setAutoIdentifyConfirmOpen(false); }}>
          <Transition.Child
            as={Fragment}
            enter="ease-out duration-200" enterFrom="opacity-0" enterTo="opacity-100"
            leave="ease-in duration-150" leaveFrom="opacity-100" leaveTo="opacity-0"
          >
            <div className="fixed inset-0" style={{ backgroundColor: 'oklch(11% 0.008 250 / 0.75)' }} />
          </Transition.Child>
          <div className="fixed inset-0 flex items-center justify-center p-4">
            <Transition.Child
              as={Fragment}
              enter="ease-out duration-200" enterFrom="opacity-0 scale-95" enterTo="opacity-100 scale-100"
              leave="ease-in duration-150" leaveFrom="opacity-100 scale-100" leaveTo="opacity-0 scale-95"
            >
              <Dialog.Panel style={{ backgroundColor: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', borderRadius: '8px', padding: '24px', width: '100%', maxWidth: '380px', boxShadow: '0 16px 48px oklch(0% 0 0 / 0.6)' }}>
                <Dialog.Title style={{ fontSize: '14px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '6px' }}>
                  Auto-identify speakers
                </Dialog.Title>
                <p style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '16px', lineHeight: '1.5' }}>
                  This will compare all transcript segments against your enrolled speaker voice prints and assign names where there's a confident match.
                </p>
                <p style={{ fontSize: '11px', color: 'var(--text-tertiary)', marginBottom: '20px' }}>
                  The page will refresh after identification completes.
                </p>
                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
                  <button
                    onClick={() => setAutoIdentifyConfirmOpen(false)}
                    disabled={autoIdentifyRunning}
                    className="btn-ghost"
                    style={{ padding: '6px 14px', fontSize: '13px', opacity: autoIdentifyRunning ? 0.5 : 1 }}
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleAutoIdentifyConfirm}
                    disabled={autoIdentifyRunning}
                    className="btn-primary"
                    style={{ padding: '6px 14px', fontSize: '13px', opacity: autoIdentifyRunning ? 0.5 : 1 }}
                  >
                    {autoIdentifyRunning ? (
                      <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <svg style={{ width: '12px', height: '12px', animation: 'spin 1s linear infinite' }} fill="none" viewBox="0 0 24 24">
                          <circle style={{ opacity: 0.25 }} cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                          <path style={{ opacity: 0.75 }} fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                        </svg>
                        Identifying…
                      </span>
                    ) : 'Identify'}
                  </button>
                </div>
              </Dialog.Panel>
            </Transition.Child>
          </div>
        </Dialog>
      </Transition>
    </div>
  );
};
