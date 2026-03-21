import React, { useRef, useState, useMemo } from "react";
import { timeToSeconds } from "../../../utils/time";

interface Segment {
  id: string | number;
  start: number;
  end: number;
  start_time: string;
  end_time: string;
  screenshot_url?: string | null;
  speech_emotion?: {
    emotion: string;
    confidence: number;
  } | null;
}

interface CustomProgressBarProps {
  videoRef?: HTMLVideoElement;
  duration: number;
  currentTime: number;
  onSeek: (time: number) => void;
  segments?: Segment[];
  getScreenshotUrlForTime?: (time: number) => string | null;
}

function formatTime(seconds: number) {
  if (isNaN(seconds)) return "00:00";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) {
    return `${h.toString().padStart(2, "0")}:${m.toString().padStart(2, "0")}`;
  } else {
    return `${m}:${s.toString().padStart(2, "0")}`;
  }
}

const EMOTION_COLORS: Record<string, string> = {
  happy: "rgba(250,204,21,0.7)",
  sad: "rgba(96,165,250,0.7)",
  angry: "rgba(248,113,113,0.7)",
  fearful: "rgba(192,132,252,0.7)",
  surprised: "rgba(251,146,60,0.7)",
  disgust: "rgba(74,222,128,0.7)",
  neutral: "rgba(156,163,175,0.35)",
  calm: "rgba(156,163,175,0.35)",
};

const EMOTION_EMOJI: Record<string, string> = {
  happy: "😊",
  sad: "😢",
  angry: "😠",
  fearful: "😨",
  surprised: "😲",
  disgust: "🤢",
  neutral: "😐",
  calm: "😌",
};

const CustomProgressBar: React.FC<CustomProgressBarProps> = ({
  duration,
  currentTime,
  onSeek,
  segments,
  getScreenshotUrlForTime,
}) => {
  const barRef = useRef<HTMLDivElement>(null);
  const [hoverX, setHoverX] = useState<number | null>(null);
  const [hoverTime, setHoverTime] = useState<number | null>(null);
  const [dragging, setDragging] = useState(false);
  const [showEmotions, setShowEmotions] = useState(true);

  let screenshotUrl: string | null = null;
  if (hoverTime !== null && getScreenshotUrlForTime) {
    screenshotUrl = getScreenshotUrlForTime(hoverTime);
  }

  const hasEmotionData = useMemo(() => {
    return segments?.some((seg) => seg.speech_emotion?.emotion) ?? false;
  }, [segments]);

  const getEmotionAtTime = (time: number) => {
    if (!segments) return null;
    for (const seg of segments) {
      const start = seg.start ?? timeToSeconds(seg.start_time);
      const end = seg.end ?? timeToSeconds(seg.end_time);
      if (time >= start && time <= end && seg.speech_emotion?.emotion) {
        return seg.speech_emotion;
      }
    }
    return null;
  };

  const hoverEmotion = hoverTime !== null ? getEmotionAtTime(hoverTime) : null;

  const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!barRef.current || !duration || duration <= 0) return;
    const rect = barRef.current.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const percent = Math.max(0, Math.min(1, x / rect.width));
    setHoverX(x);
    setHoverTime(percent * duration);
    if (dragging) {
      onSeek(percent * duration);
    }
  };

  const handleMouseLeave = () => {
    setHoverX(null);
    setHoverTime(null);
    setDragging(false);
  };

  const handleClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!barRef.current || !duration || duration <= 0) return;
    const rect = barRef.current.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const percent = Math.max(0, Math.min(1, x / rect.width));
    onSeek(percent * duration);
  };

  const handleMouseDown = () => setDragging(true);
  const handleMouseUp = () => setDragging(false);

  const percent = duration ? currentTime / duration : 0;

  return (
    <div className="w-full px-4 pb-2 select-none">
      <div className="flex items-center text-xs font-mono mb-1">
        <span className="text-gray-200 font-semibold drop-shadow-sm p-2">
          {formatTime(currentTime)}
        </span>
        {hasEmotionData && (
          <button
            onClick={() => setShowEmotions((v) => !v)}
            className={`px-1.5 py-0.5 rounded text-xs transition-colors ${
              showEmotions
                ? "bg-orange-500/30 text-orange-300 hover:bg-orange-500/40"
                : "bg-gray-700/50 text-gray-400 hover:bg-gray-700/70"
            }`}
            title={showEmotions ? "Hide emotion overlay" : "Show emotion overlay"}
          >
            🎭
          </button>
        )}
        <div className="flex-1" />
        <span className="text-gray-200 font-semibold drop-shadow-sm p-2">
          {formatTime(duration)}
        </span>
      </div>
      <div
        ref={barRef}
        className={`relative bg-gray-700 rounded cursor-pointer group transition-all duration-200 ${
          showEmotions && hasEmotionData ? "h-5" : "h-3"
        }`}
        onMouseMove={handleMouseMove}
        onMouseLeave={handleMouseLeave}
        onClick={handleClick}
        onMouseDown={handleMouseDown}
        onMouseUp={handleMouseUp}
        style={{ userSelect: "none" }}
      >
        {/* Emotion overlay — behind progress fill */}
        {showEmotions && hasEmotionData && (
          <div className="absolute inset-0 rounded overflow-hidden pointer-events-none">
            {segments?.map((seg) => {
              if (!seg.speech_emotion?.emotion) return null;
              const start = seg.start ?? timeToSeconds(seg.start_time);
              const end = seg.end ?? timeToSeconds(seg.end_time);
              if (!duration) return null;
              const left = (start / duration) * 100;
              const width = ((end - start) / duration) * 100;
              return (
                <div
                  key={seg.id}
                  className="absolute top-0 h-full"
                  style={{
                    left: `${left}%`,
                    width: `${width}%`,
                    backgroundColor:
                      EMOTION_COLORS[seg.speech_emotion.emotion] ??
                      EMOTION_COLORS.neutral,
                  }}
                />
              );
            })}
          </div>
        )}
        {/* Progress fill */}
        <div
          className="absolute top-0 left-0 h-full bg-gradient-to-r from-orange-400 to-rose-500 rounded"
          style={{ width: `${percent * 100}%` }}
        />
        {/* Thumb */}
        <div
          className="absolute top-0 h-full w-3 bg-white rounded-full shadow -translate-x-1/2 border border-orange-500"
          style={{ left: `calc(${percent * 100}% )` }}
        />
        {/* Tooltip and Screenshot Preview */}
        {hoverX !== null && hoverTime !== null && (
          <div
            className="absolute z-20 flex flex-col items-center pointer-events-none"
            style={{
              left: Math.max(
                0,
                Math.min(hoverX, (barRef.current?.offsetWidth || 0) - 80)
              ),
              top: "-7.5rem",
            }}
          >
            {screenshotUrl && (
              <img
                src={screenshotUrl}
                alt="Preview"
                className="mb-1 w-40 h-24 object-cover rounded shadow border border-gray-300 bg-black"
                style={{ background: "#222" }}
              />
            )}
            <div
              className="px-2 py-1 text-xs text-white bg-black bg-opacity-80 rounded shadow flex items-center gap-1"
              style={{ marginTop: screenshotUrl ? 0 : 8 }}
            >
              {formatTime(hoverTime)}
              {hoverEmotion && (
                <span className="ml-1 opacity-90">
                  {EMOTION_EMOJI[hoverEmotion.emotion] ?? ""}{" "}
                  {hoverEmotion.emotion}
                </span>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default CustomProgressBar;
