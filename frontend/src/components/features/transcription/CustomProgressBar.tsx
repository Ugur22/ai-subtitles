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
  audio_events?: Array<{ event_type: string; confidence: number }>;
  is_silent?: boolean;
}

interface ChapterMarker {
  start: number;
  title: string;
}

interface CustomProgressBarProps {
  videoRef?: HTMLVideoElement;
  duration: number;
  currentTime: number;
  onSeek: (time: number) => void;
  segments?: Segment[];
  chapters?: ChapterMarker[];
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
  happy:     'oklch(75% 0.12 80 / 0.32)',
  sad:       'oklch(70% 0.09 240 / 0.32)',
  angry:     'oklch(65% 0.13 25 / 0.32)',
  fearful:   'oklch(68% 0.10 290 / 0.32)',
  surprised: 'oklch(72% 0.12 55 / 0.32)',
  disgust:   'oklch(68% 0.10 130 / 0.32)',
  neutral:   'oklch(60% 0.01 250 / 0.25)',
  calm:      'oklch(60% 0.01 250 / 0.25)',
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

const AMBIENT_COLORS: Record<string, string> = {
  music:     'oklch(70% 0.12 320 / 0.30)',
  singing:   'oklch(70% 0.12 320 / 0.30)',
  laughter:  'oklch(75% 0.10 75 / 0.30)',
  crying:    'oklch(70% 0.09 240 / 0.30)',
  rain:      'oklch(70% 0.08 220 / 0.30)',
  water:     'oklch(70% 0.08 220 / 0.30)',
  wind:      'oklch(72% 0.05 200 / 0.28)',
  thunder:   'oklch(50% 0.08 270 / 0.32)',
  fire:      'oklch(65% 0.13 35 / 0.32)',
  applause:  'oklch(75% 0.10 75 / 0.30)',
  cheering:  'oklch(75% 0.10 75 / 0.30)',
  crowd:     'oklch(70% 0.08 60 / 0.28)',
  screaming: 'oklch(60% 0.15 25 / 0.36)',
  explosion: 'oklch(60% 0.15 25 / 0.36)',
  gunshot:   'oklch(60% 0.15 25 / 0.36)',
  siren:     'oklch(60% 0.18 20 / 0.40)',
  alarm:     'oklch(60% 0.18 20 / 0.40)',
  breathing: 'oklch(60% 0.01 250 / 0.25)',
  silence:   'oklch(60% 0.01 250 / 0.20)',
  ambient:   'oklch(60% 0.01 250 / 0.25)',
};

const AMBIENT_EMOJI: Record<string, string> = {
  music: "🎵",
  singing: "🎤",
  laughter: "😄",
  crying: "😭",
  rain: "🌧️",
  water: "💧",
  wind: "💨",
  thunder: "⛈️",
  fire: "🔥",
  applause: "👏",
  cheering: "👏",
  crowd: "👥",
  screaming: "😱",
  explosion: "💥",
  gunshot: "💥",
  siren: "🚨",
  alarm: "🚨",
  breathing: "🌬️",
  silence: "🔇",
  ambient: "🔈",
};

const CustomProgressBar: React.FC<CustomProgressBarProps> = ({
  duration,
  currentTime,
  onSeek,
  segments,
  chapters,
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

  const hasOverlayData = useMemo(() => {
    return segments?.some(
      (seg) => seg.speech_emotion?.emotion || seg.audio_events?.length
    ) ?? false;
  }, [segments]);

  const getOverlayAtTime = (time: number): { type: 'emotion' | 'ambient'; label: string; confidence: number } | null => {
    if (!segments) return null;
    for (const seg of segments) {
      const start = seg.start ?? timeToSeconds(seg.start_time);
      const end = seg.end ?? timeToSeconds(seg.end_time);
      if (time >= start && time <= end) {
        if (seg.speech_emotion?.emotion) {
          return { type: 'emotion', label: seg.speech_emotion.emotion, confidence: seg.speech_emotion.confidence };
        }
        if (seg.audio_events?.length) {
          const top = seg.audio_events[0];
          return { type: 'ambient', label: top.event_type, confidence: top.confidence };
        }
      }
    }
    return null;
  };

  const hoverOverlay = hoverTime !== null ? getOverlayAtTime(hoverTime) : null;

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
      <div className="flex items-center text-xs mb-1">
        <span
          className="font-mono tabular-nums px-2 py-1"
          style={{ color: 'var(--player-icon)' }}
        >
          {formatTime(currentTime)}
        </span>
        {hasOverlayData && (
          <button
            onClick={() => setShowEmotions((v) => !v)}
            aria-label={showEmotions ? "Hide audio overlay" : "Show audio overlay"}
            title={showEmotions ? "Hide audio overlay" : "Show audio overlay"}
            className="ml-1 px-1.5 py-1 rounded transition-colors"
            style={
              showEmotions
                ? { background: 'var(--accent-dim)', color: 'var(--accent)' }
                : { background: 'transparent', color: 'var(--text-tertiary)' }
            }
          >
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
              <path strokeLinecap="round" d="M4 12h2M8 8v8M12 5v14M16 9v6M20 12h0" />
            </svg>
          </button>
        )}
        <div className="flex-1" />
        <span
          className="font-mono tabular-nums px-2 py-1"
          style={{ color: 'var(--player-icon)' }}
        >
          {formatTime(duration)}
        </span>
      </div>
      <div
        ref={barRef}
        className={`relative rounded cursor-pointer group transition-all duration-150 ${
          showEmotions && hasOverlayData ? "h-5" : "h-3"
        }`}
        onMouseMove={handleMouseMove}
        onMouseLeave={handleMouseLeave}
        onClick={handleClick}
        onMouseDown={handleMouseDown}
        onMouseUp={handleMouseUp}
        style={{ userSelect: "none", backgroundColor: 'var(--player-track)' }}
      >
        {/* Emotion + ambient overlay — behind progress fill */}
        {showEmotions && hasOverlayData && (
          <div className="absolute inset-0 rounded overflow-hidden pointer-events-none">
            {segments?.map((seg) => {
              let backgroundColor: string | null = null;
              if (seg.speech_emotion?.emotion) {
                backgroundColor =
                  EMOTION_COLORS[seg.speech_emotion.emotion] ??
                  EMOTION_COLORS.neutral;
              } else if (seg.audio_events?.length) {
                const topEvent = seg.audio_events[0].event_type;
                backgroundColor =
                  AMBIENT_COLORS[topEvent] ?? "rgba(156,163,175,0.45)";
              }
              if (!backgroundColor) return null;

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
                    backgroundColor,
                  }}
                />
              );
            })}
          </div>
        )}
        {/* Chapter markers */}
        {chapters && chapters.length > 0 && duration > 0 && (
          <div className="absolute inset-0 pointer-events-none z-[5]">
            {chapters.map((ch, i) => {
              if (i === 0) return null; // Skip first chapter (starts at 0)
              const left = (ch.start / duration) * 100;
              return (
                <div
                  key={i}
                  className="absolute top-0 h-full group/ch pointer-events-auto"
                  style={{ left: `${left}%` }}
                >
                  <div
                    className="w-[2px] h-full"
                    style={{ backgroundColor: 'var(--player-icon)', opacity: 0.55 }}
                  />
                  <div
                    className="absolute bottom-full mb-1 left-1/2 -translate-x-1/2 px-2 py-1 text-[11px] rounded whitespace-nowrap opacity-0 group-hover/ch:opacity-100 transition-opacity pointer-events-none border"
                    style={{
                      background: 'var(--bg-overlay)',
                      color: 'var(--text-primary)',
                      borderColor: 'var(--border-subtle)',
                    }}
                  >
                    {ch.title}
                  </div>
                </div>
              );
            })}
          </div>
        )}
        {/* Progress fill */}
        <div
          className="absolute top-0 left-0 h-full rounded"
          style={{
            width: `${percent * 100}%`,
            backgroundColor: 'var(--accent)',
          }}
        />
        {/* Thumb */}
        <div
          className="absolute top-1/2 w-3 h-3 rounded-full -translate-x-1/2 -translate-y-1/2 transition-transform group-hover:scale-125"
          style={{
            left: `${percent * 100}%`,
            backgroundColor: 'var(--accent)',
            boxShadow: '0 0 0 3px oklch(70% 0.18 145 / 0.25)',
          }}
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
                className="mb-1 w-40 h-24 object-cover rounded shadow-sm border"
                style={{ borderColor: 'var(--border-subtle)' }}
              />
            )}
            <div
              className="px-2 py-1 text-xs rounded shadow-sm flex items-center gap-1.5 border"
              style={{
                background: 'var(--bg-overlay)',
                color: 'var(--text-primary)',
                borderColor: 'var(--border-subtle)',
                marginTop: screenshotUrl ? 0 : 8,
              }}
            >
              <span className="font-mono tabular-nums">{formatTime(hoverTime)}</span>
              {hoverOverlay && (
                <span style={{ color: 'var(--text-tertiary)' }}>
                  · {hoverOverlay.type === 'emotion'
                      ? (EMOTION_EMOJI[hoverOverlay.label] ?? "")
                      : (AMBIENT_EMOJI[hoverOverlay.label] ?? "🔈")}
                  {" "}
                  {hoverOverlay.label}
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
