/**
 * JumpToTimeModal - Modal for jumping to specific time in video
 * Allows users to enter time in HH:MM:SS or MM:SS format
 */

import React, { useRef, useState, useEffect } from "react";
import { useSpring, animated, config as springConfig } from "react-spring";
import { animationConfig } from "../../../utils/animations";
import { secondsToTimeString } from "../../../utils/time";

interface JumpToTimeModalProps {
  isOpen: boolean;
  onClose: () => void;
  onJump: (seconds: number) => void;
  duration: number;
  currentTime: number;
  inputRef?: React.RefObject<HTMLInputElement>;
}

/**
 * Parses time input string (HH:MM:SS, MM:SS, or SS) to seconds
 */
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

export const JumpToTimeModal: React.FC<JumpToTimeModalProps> = ({
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

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      handleOk();
    } else if (e.key === "Escape") {
      onClose();
    }
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
          onKeyDown={handleKeyDown}
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
