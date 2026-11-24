import { useState, useEffect, useMemo, useRef, useCallback } from "react";
import toast from "react-hot-toast";
import { match } from "ts-pattern";
import { useJobs } from "../../../hooks/useJobs";
import { type TranscriptionResponse } from "../../../services/api";
import { SummaryPanel } from "../summary/SummaryPanel";
import { ChatPanel } from "../chat/ChatPanel";
import React from "react";
import { secondsToTimeString } from "../../../utils/time";
import { formatSpeakerLabel } from "../../../utils/speaker";
import { DraggableImageModal } from "../../common/DraggableImageModal";
import { TranscriptSegmentList } from "./TranscriptSegmentList";
import { UploadZone } from "./UploadZone";
import { RecentTranscriptions } from "./RecentTranscriptions";
import { ActiveJobsSection } from "./ActiveJobsSection";
import { AutoIdentifyConfirmDialog } from "./AutoIdentifyConfirmDialog";
import { SpeakerEnrollModal } from "./SpeakerEnrollModal";
import { SubmissionProgressDialog } from "./SubmissionProgressDialog";
import { TranscriptHeader } from "./TranscriptHeader";
import { TranscriptToolbar } from "./TranscriptToolbar";
import { TranscriptionErrorBanner } from "./TranscriptionErrorBanner";
import { VideoPlayerPanel } from "./VideoPlayerPanel";
import { useSpeakerManagement } from "./hooks/useSpeakerManagement";
import { useTranscriptPlayback } from "./hooks/useTranscriptPlayback";
import { useOpenJob } from "./hooks/useOpenJob";
import { filterDisplayedSegments, listUniqueSpeakers } from "./segments";
import { DEFAULT_WHISPER_MODEL, isActiveJobStatus, type WhisperModelChoice } from "../../../types/job";
import { useFileUpload } from "../../../hooks/useFileUpload";
import { useVideoPlayer } from "../../../hooks/useVideoPlayer";
import { useSubtitles } from "../../../hooks/useSubtitles";
import { useSummaries } from "../../../hooks/useSummaries";
import { useChapters } from "../../../hooks/useChapters";
import { useFeatureFlags } from "../../../hooks/useFeatureFlags";
import { ChapterPanel } from "../chapters/ChapterPanel";
import { useBackgroundJobSubmit } from "../../../hooks/useBackgroundJobSubmit";
import { useJobTracker } from "../../../hooks/useJobTracker";
import { useAuth } from "../../../hooks/useAuth";
import { getMediaDurationSeconds } from "../../../utils/file";
import { JobPanel } from "../jobs";

// Per-file video length cap for non-admin (free) users. Backend (middleware/quota.py)
// is the source of truth; this just gives instant feedback before uploading.
const FREE_MAX_FILE_MINUTES = 30;

// Language options (ISO 639-1 codes)
const languageOptions = [
  { value: "", label: "Detect automatically" },
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
  { value: "cs", label: "Czech" },
];

const modelOptions: { value: WhisperModelChoice; label: string }[] = [
  { value: "large-v3", label: "Accurate (large-v3)" },
  { value: "turbo", label: "Fast (turbo)" },
];

type TranscriptionUploadProps = {
  onTranscriptionChange?: (transcription: TranscriptionResponse | null) => void;
};

type TranscriptTab = "transcript" | "chat" | "chapters" | "summary";

export const TranscriptionUpload: React.FC<TranscriptionUploadProps> = ({
  onTranscriptionChange,
}) => {
  // UI-specific state (keep these)
  const [showTranslation, setShowTranslation] = useState(true);
  const [activeTab, setActiveTab] = useState<TranscriptTab>("transcript");
  const [chatMountedFor, setChatMountedFor] = useState<string | null>(null);
  const [selectedLanguage, setSelectedLanguage] = useState<string>("");
  const [selectedModel, setSelectedModel] = useState<WhisperModelChoice>(DEFAULT_WHISPER_MODEL);
  const [modalImageUrl, setModalImageUrl] = useState<string | null>(null);
  const [transcription, setTranscription] = useState<TranscriptionResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [jumpModalOpen, setJumpModalOpen] = useState(false);
  const [filteredSpeaker, setFilteredSpeaker] = useState<string | null>(null);
  const [showVisualMoments, setShowVisualMoments] = useState(true);
  const [videoDuration, setVideoDuration] = useState(0);
  const displayDuration =
    transcription?.transcription.duration ||
    (videoDuration > 0 ? secondsToTimeString(videoDuration) : "");
  const languageLabel = transcription?.transcription.language?.toUpperCase();


  // Jobs context — shares active count + panel state with Header
  const { setActiveJobCount, showJobPanel, setShowJobPanel } = useJobs();

  // Current user (for plan/admin-aware upload limits)
  const { user } = useAuth();

  // Initialize job tracker for background processing
  const jobTracker = useJobTracker();
  const backgroundJobSubmit = useBackgroundJobSubmit(() => {
    // Refetch jobs when a new job is submitted
    jobTracker.refetch();
  });

  const fileUploadHook = useFileUpload({
    onFileSelected: () => {
      setError(null);
      setTranscription(null);
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
    resetFile,
  } = fileUploadHook;

  const videoPlayerHook = useVideoPlayer({
    onJumpToTimeRequest: () => setJumpModalOpen(true),
  });
  const { videoRef, seek, play } = videoPlayerHook;

  const subtitlesHook = useSubtitles({
    transcription,
    videoRef,
    showTranslation,
  });

  const summariesHook = useSummaries({
    transcription,
  });
  const { summaries, setSummaries, summaryLoading, generateSummaries } =
    summariesHook;

  const chaptersHook = useChapters({
    videoHash: transcription?.video_hash,
  });
  const featureFlags = useFeatureFlags();


  // Computed values
  const isTranscribing = backgroundJobSubmit.isSubmitting;

  // Filter segments by selected speaker, optionally including visual moments
  const displayedSegments = useMemo(
    () => (transcription ? filterDisplayedSegments(transcription.transcription.segments, filteredSpeaker, showVisualMoments) : []),
    [transcription, filteredSpeaker, showVisualMoments],
  );

  const uniqueSpeakers = useMemo(
    () => (transcription ? listUniqueSpeakers(transcription.transcription.segments) : []),
    [transcription],
  );

  const transcriptScrollRef = useRef<HTMLDivElement>(null);
  const { activeSegmentId, seekToTimestamp } = useTranscriptPlayback({
    videoRef,
    transcriptScrollRef,
    displayedSegments,
    seek,
    play,
  });

  const speakers = useSpeakerManagement({
    transcription,
    setTranscription,
    filteredSpeaker,
    setFilteredSpeaker,
  });
  const {
    editingSegmentId,
    setEditingSegmentId,
    editSpeakerName,
    setEditSpeakerName,
    isRenamingSpeaker,
    handleSpeakerRename,
    handleEnrollSpeaker,
  } = speakers;

  // Sync active job count to header via context
  useEffect(() => {
    const activeCount = jobTracker.jobs.filter((job) =>
      isActiveJobStatus(job.status)
    ).length;
    setActiveJobCount(activeCount);
  }, [jobTracker.jobs, setActiveJobCount]);

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

  // Note: startPollingForTranscription removed - was unused
  // Polling logic can be added back if needed for cloud transcription

  // Handle transcription start using the hook
  const handleStartTranscriptionClick = async () => {
    if (!file) {
      setError("No file selected to transcribe.");
      return;
    }

    const durationSeconds = await getMediaDurationSeconds(file);

    if (
      durationSeconds &&
      !user?.is_admin &&
      durationSeconds > FREE_MAX_FILE_MINUTES * 60
    ) {
      toast.error(
        `Videos are limited to ${FREE_MAX_FILE_MINUTES} minutes on your plan. ` +
          `This file is ${Math.ceil(durationSeconds / 60)} minutes.`
      );
      return;
    }

    try {
      setError(null);
      const result = await backgroundJobSubmit.submit(file, {
        durationSeconds: durationSeconds ?? undefined,
        language: selectedLanguage || undefined,
        forceLanguage: true,
        model: selectedModel,
      });

      if (result) {
        resetFile();
        setShowJobPanel(true);
      }
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to submit job";
      setError(message);
      console.error("Background job submission failed:", error);
      toast.error(message);
    }
  };

  const resetJobSubmit = backgroundJobSubmit.reset;
  const closeTranscription = useCallback(() => {
    setTranscription(null);
    setError(null);
    resetJobSubmit();
    setVideoUrl(null);
    setShowTranslation(true);
    setSelectedLanguage("");
    setSelectedModel(DEFAULT_WHISPER_MODEL);
    setFilteredSpeaker(null);
  }, [resetJobSubmit, setVideoUrl]);

  const { handleViewTranscript, handleVideoError, closeJob, currentJobId, currentAccessToken } =
    useOpenJob({
      jobs: jobTracker.jobs,
      jobsFresh: jobTracker.isFresh,
      transcription,
      setTranscription,
      setShowTranslation,
      setVideoUrl,
      setShowJobPanel,
      onClose: closeTranscription,
    });

  // Function to open the modal
  const openImageModal = (imageUrl: string | undefined) => {
    if (imageUrl) setModalImageUrl(imageUrl);
  };

  // Notify parent when transcription changes
  useEffect(() => {
    if (onTranscriptionChange) {
      onTranscriptionChange(transcription);
    }
  }, [transcription, onTranscriptionChange]);

  return (
    <div className={`relative min-h-screen ${transcription ? 'bg-base' : 'bg-surface'}`}>
      <div className="h-full px-4" style={{ color: 'var(--text-primary)' }}>
        {/* Upload Section */}
        {!transcription && (
          <div className="-mx-4 pb-24">
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
              onLanguageChange={setSelectedLanguage}
              handleStartTranscriptionClick={handleStartTranscriptionClick}
              languageOptions={languageOptions}
              selectedModel={selectedModel}
              onModelChange={setSelectedModel}
              modelOptions={modelOptions}
            >
            <ActiveJobsSection jobs={jobTracker.jobs} onOpenJobPanel={() => setShowJobPanel(true)} />
            <RecentTranscriptions
              jobs={jobTracker.jobs}
              onViewJob={handleViewTranscript}
              onViewAll={() => setShowJobPanel(true)}
              isLoading={jobTracker.isLoading}
            />
            </UploadZone>
          </div>
        )}

        {transcription && (
          <div className="h-screen flex flex-col overflow-hidden w-full" style={{ gap: '8px' }}>
            <TranscriptHeader
              transcription={transcription}
              onClose={closeJob}
              displayDuration={displayDuration}
              languageLabel={languageLabel}
            />

            {/* Three-Column Layout */}
            <div className="flex flex-col lg:flex-row flex-grow overflow-hidden w-full" style={{ gap: '8px' }}>
              {/* Main Column: Video and Transcript/Summary */}
              <div
                className="watch-layout flex-grow flex flex-col overflow-hidden gap-4 w-full"
              >
                <VideoPlayerPanel
                  transcription={transcription}
                  videoUrl={videoUrl}
                  videoPlayer={videoPlayerHook}
                  subtitles={subtitlesHook}
                  displayedSegments={displayedSegments}
                  videoDuration={videoDuration}
                  setVideoDuration={setVideoDuration}
                  showTranslation={showTranslation}
                  onVideoError={handleVideoError}
                  chapters={featureFlags.chapters ? chaptersHook.chapters.map(ch => ({ start: ch.start, title: ch.title })) : []}
                  jumpModalOpen={jumpModalOpen}
                  setJumpModalOpen={setJumpModalOpen}
                />

                <div
                  className="rp overflow-hidden flex-grow flex flex-col w-full"
                >
                  <div className="rp-tabs">
                    {([
                      { key: 'transcript', label: 'Transcript', count: transcription?.transcription.segments.length },
                      { key: 'chat',       label: 'Chat' },
                      { key: 'chapters',   label: 'Chapters',   count: chaptersHook.chapters.length },
                      { key: 'summary',    label: 'Summary' },
                    ] satisfies Array<{ key: TranscriptTab; label: string; count?: number }>).filter(({ key }) => (key !== 'chapters' || featureFlags.chapters) && (key !== 'summary' || featureFlags.summary)).map(({ key, label, count }) => (
                      <button
                        key={key}
                        onClick={() => {
                          setActiveTab(key);
                          if (key === 'chat') setChatMountedFor(transcription?.video_hash ?? null);
                        }}
                        className={`rp-tab ${activeTab === key ? 'on' : ''}`}
                      >
                        {label}
                        {typeof count === 'number' && count > 0 && (
                          <span className="ct mono">{count}</span>
                        )}
                      </button>
                    ))}
                  </div>

                  <div ref={transcriptScrollRef} className="flex-grow overflow-auto relative">
                    {activeTab !== 'chat' && match(activeTab)
                      .with('transcript', () => (
                        <>
                          <TranscriptToolbar
                            transcription={transcription}
                            displayedSegments={displayedSegments}
                            uniqueSpeakers={uniqueSpeakers}
                            showTranslation={showTranslation}
                            setShowTranslation={setShowTranslation}
                            filteredSpeaker={filteredSpeaker}
                            setFilteredSpeaker={setFilteredSpeaker}
                            showVisualMoments={showVisualMoments}
                            setShowVisualMoments={setShowVisualMoments}
                            speakers={speakers}
                          />
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
                            formatSpeakerLabel={formatSpeakerLabel}
                            onEnrollSpeaker={handleEnrollSpeaker}
                          />
                        </>
                      ))
                      .with('chapters', () => featureFlags.chapters && (
                        <div style={{ position: 'absolute', inset: 0 }}>
                          <ChapterPanel
                            chapters={chaptersHook.chapters}
                            loading={chaptersHook.loading}
                            error={chaptersHook.error}
                            onGenerate={chaptersHook.generate}
                            onSeekTo={seekToTimestamp}
                          />
                        </div>
                      ))
                      .with('summary', () => featureFlags.summary && (
                        <div style={{ position: 'absolute', inset: 0 }}>
                          <SummaryPanel
                            isVisible
                            onSeekTo={seekToTimestamp}
                            summaries={summaries}
                            setSummaries={setSummaries}
                            loading={summaryLoading}
                            generateSummaries={generateSummaries}
                            videoHash={transcription?.video_hash}
                          />
                        </div>
                      ))
                      .exhaustive()}

                    {chatMountedFor && chatMountedFor === transcription?.video_hash && (
                      <div style={{ position: 'absolute', inset: 0 }} hidden={activeTab !== 'chat'}>
                        <ChatPanel
                          videoHash={chatMountedFor}
                          transcriptSpeakers={uniqueSpeakers}
                          onTimestampClick={seekToTimestamp}
                          jobId={currentJobId}
                          accessToken={currentAccessToken}
                        />
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Error Display */}
        {error && <TranscriptionErrorBanner error={error} setError={setError} />}

        {/* Image Modal */}
        {modalImageUrl && (
          <DraggableImageModal
            imageUrl={modalImageUrl}
            onClose={() => setModalImageUrl(null)}
            videoHash={transcription?.video_hash}
            speakers={uniqueSpeakers}
          />
        )}

      </div>

      <SubmissionProgressDialog
        isOpen={backgroundJobSubmit.isSubmitting}
        progress={backgroundJobSubmit.progress}
        file={file}
      />

      {/* Background Jobs Panel */}
      <JobPanel
        isOpen={showJobPanel}
        onClose={() => setShowJobPanel(false)}
        onViewTranscript={handleViewTranscript}
        tracker={jobTracker}
      />

      {/* Enroll Speaker Modal */}
      <SpeakerEnrollModal speakers={speakers} />

      {/* Auto-identify Confirmation Modal */}
      <AutoIdentifyConfirmDialog speakers={speakers} />
    </div>
  );
};
