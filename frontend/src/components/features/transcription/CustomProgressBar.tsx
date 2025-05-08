import React, { useRef, useState } from 'react';

interface Segment {
  id: string | number;
  start_time: string;
  end_time: string;
  screenshot_url?: string | null;
}

interface CustomProgressBarProps {
  videoRef: HTMLVideoElement;
  duration: number;
  currentTime: number;
  onSeek: (time: number) => void;
  segments?: Segment[];
  getScreenshotUrlForTime?: (time: number) => string | null;
}

function formatTime(seconds: number) {
  if (isNaN(seconds)) return '00:00';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) {
    return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}`;
  } else {
    return `${m}:${s.toString().padStart(2, '0')}`;
  }
}

const CustomProgressBar: React.FC<CustomProgressBarProps> = ({ videoRef, duration, currentTime, onSeek, getScreenshotUrlForTime }) => {
  const barRef = useRef<HTMLDivElement>(null);
  const [hoverX, setHoverX] = useState<number | null>(null);
  const [hoverTime, setHoverTime] = useState<number | null>(null);
  const [dragging, setDragging] = useState(false);

  let screenshotUrl: string | null = null;
  if (hoverTime !== null && getScreenshotUrlForTime) {
    screenshotUrl = getScreenshotUrlForTime(hoverTime);
  }

  const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!barRef.current) return;
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
    if (!barRef.current) return;
    const rect = barRef.current.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const percent = Math.max(0, Math.min(1, x / rect.width));
    onSeek(percent * duration);
  };

  const handleMouseDown = () => setDragging(true);
  const handleMouseUp = () => setDragging(false);

  const percent = duration ? (currentTime / duration) : 0;

  return (
    <div className="w-full px-4 pb-2 select-none">
      <div className="flex items-center text-xs font-mono mb-1">
        <span className="text-gray-900 font-semibold drop-shadow-sm p-2">{formatTime(currentTime)}</span>
        <div className="flex-1" />
        <span className="text-gray-900 font-semibold drop-shadow-sm p-2">{formatTime(duration)}</span>
      </div>
      <div
        ref={barRef}
        className="relative h-3 bg-gray-700 rounded cursor-pointer group"
        onMouseMove={handleMouseMove}
        onMouseLeave={handleMouseLeave}
        onClick={handleClick}
        onMouseDown={handleMouseDown}
        onMouseUp={handleMouseUp}
        style={{ userSelect: 'none' }}
      >
        {/* Progress fill */}
        <div
          className="absolute top-0 left-0 h-3 bg-teal-400 rounded"
          style={{ width: `${percent * 100}%` }}
        />
        {/* Thumb */}
        <div
          className="absolute top-0 h-3 w-3 bg-white rounded-full shadow -translate-x-1/2 border border-teal-500"
          style={{ left: `calc(${percent * 100}% )` }}
        />
        {/* Tooltip and Screenshot Preview */}
        {hoverX !== null && hoverTime !== null && (
          <div
            className="absolute z-20 flex flex-col items-center pointer-events-none"
            style={{ left: Math.max(0, Math.min(hoverX, (barRef.current?.offsetWidth || 0) - 80)), top: '-7.5rem' }}
          >
            {screenshotUrl && (
              <img
                src={screenshotUrl}
                alt="Preview"
                className="mb-1 w-40 h-24 object-cover rounded shadow border border-gray-300 bg-black"
                style={{ background: '#222' }}
              />
            )}
            <div
              className="px-2 py-1 text-xs text-white bg-black bg-opacity-80 rounded shadow"
              style={{ marginTop: screenshotUrl ? 0 : 8 }}
            >
              {formatTime(hoverTime)}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default CustomProgressBar; 