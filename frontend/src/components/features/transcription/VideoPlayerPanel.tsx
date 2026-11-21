import type { RefObject } from "react";
import { getJobVideoUrl, type TranscriptionResponse } from "../../../services/api";
import { formatScreenshotUrl } from "../../../utils/url";
import { timeToSeconds } from "../../../utils/time";
import type { useSubtitles } from "../../../hooks/useSubtitles";
import type { useVideoPlayer } from "../../../hooks/useVideoPlayer";
import CustomProgressBar from "./CustomProgressBar";
import { JumpToTimeModal } from "./JumpToTimeModal";
import type { TranscriptSegment } from "./segments";

interface VideoPlayerPanelProps {
  transcription: TranscriptionResponse;
  videoUrl: string | null;
  setVideoUrl: (url: string | null) => void;
  videoPlayer: ReturnType<typeof useVideoPlayer>;
  subtitles: ReturnType<typeof useSubtitles>;
  displayedSegments: TranscriptSegment[];
  videoDuration: number;
  setVideoDuration: (seconds: number) => void;
  showTranslation: boolean;
  currentJobRef: RefObject<{ jobId: string; accessToken?: string } | null>;
  videoRetriedRef: RefObject<boolean>;
  chapters: { start: number; title: string }[];
  jumpModalOpen: boolean;
  setJumpModalOpen: (open: boolean) => void;
}

export const VideoPlayerPanel: React.FC<VideoPlayerPanelProps> = ({
  transcription,
  videoUrl,
  setVideoUrl,
  videoPlayer,
  subtitles,
  displayedSegments,
  videoDuration,
  setVideoDuration,
  showTranslation,
  currentJobRef,
  videoRetriedRef,
  chapters,
  jumpModalOpen,
  setJumpModalOpen,
}) => {
  const {
    videoRef,
    setVideoRef,
    currentTime,
    isPlaying,
    volume,
    handlePlayPause,
    handleVolumeChange,
    seek,
  } = videoPlayer;
  const { showSubtitles, subtitleTrackUrl, translatedSubtitleUrl } = subtitles;

  return (
    <div
      className="overflow-hidden flex-shrink-0 w-full flex flex-col"
      style={{ backgroundColor: '#000', borderRadius: '6px', border: '1px solid var(--border-subtle)' }}
    >
      <div className="w-full bg-black flex justify-center relative flex-grow items-center">
        {videoUrl ? (
        <video
          ref={setVideoRef}
          src={videoUrl}
          className="w-full h-full max-h-[70vh] xl:max-h-[80vh] object-contain"
          onLoadedMetadata={(e) => setVideoDuration(e.currentTarget.duration)}
          onError={async () => {
            if (videoRetriedRef.current || !currentJobRef.current) return;
            videoRetriedRef.current = true;
            try {
              const { download_url } = await getJobVideoUrl(
                currentJobRef.current.jobId,
                currentJobRef.current.accessToken
              );
              setVideoUrl(download_url);
            } catch (e) {
              console.error("Failed to refresh video URL", e);
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
        ) : (
        <div
          className="w-full flex items-center justify-center"
          style={{ minHeight: '320px', aspectRatio: '16 / 9' }}
        >
          <span className="text-sm" style={{ color: 'rgba(255,255,255,0.5)' }}>
            Loading video…
          </span>
        </div>
        )}
      </div>
      {videoRef && (
        <>
          <div className="bg-gradient-to-t from-black/70 via-black/20 to-transparent pt-4">
          <div className="flex items-center px-4 py-2 gap-4">
            <button
              onClick={handlePlayPause}
              aria-label={isPlaying ? "Pause" : "Play"}
              className="group flex items-center justify-center w-9 h-9 rounded-full transition-[background-color,transform] duration-150 hover:bg-white/10 active:bg-white/20 active:scale-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/60"
            >
              {isPlaying ? (
                <svg
                  className="w-6 h-6 transition-colors duration-150"
                  style={{ color: 'var(--player-icon)' }}
                  fill="currentColor"
                  viewBox="0 0 24 24"
                >
                  <rect x="6" y="4" width="4" height="16" rx="1" />
                  <rect x="14" y="4" width="4" height="16" rx="1" />
                </svg>
              ) : (
                <svg
                  className="w-6 h-6 transition-colors duration-150"
                  style={{ color: 'var(--player-icon)' }}
                  fill="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path d="M8 5v14l11-7z" />
                </svg>
              )}
            </button>

            <div className="flex items-center space-x-2">
              <button
                type="button"
                onClick={() => {
                  if (videoRef) {
                    videoRef.volume = volume === 0 ? 1 : 0;
                  }
                }}
                aria-label={volume === 0 ? "Unmute" : "Mute"}
                className="group flex items-center justify-center w-8 h-8 rounded-full transition-[background-color,transform] duration-150 hover:bg-white/10 active:bg-white/20 active:scale-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/60"
              >
                <svg
                  className="w-5 h-5 transition-colors duration-150"
                  style={{ color: 'var(--player-icon)' }}
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
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
              </button>
              <input
                type="range"
                min="0"
                max="1"
                step="0.05"
                value={volume}
                onChange={handleVolumeChange}
                aria-label="Volume"
                className="player-volume-slider rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/60"
                style={{ width: '80px', ['--vol' as string]: volume } as React.CSSProperties}
              />
            </div>
          </div>
          <CustomProgressBar
            videoRef={videoRef}
            duration={videoDuration}
            currentTime={currentTime}
            segments={displayedSegments}
            getScreenshotUrlForTime={(time) => {
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
            onSeek={seek}
            chapters={chapters}
          />
          </div>
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
            onJump={seek}
            duration={videoDuration}
            currentTime={currentTime}
          />
        </>
      )}
    </div>
  );
};
