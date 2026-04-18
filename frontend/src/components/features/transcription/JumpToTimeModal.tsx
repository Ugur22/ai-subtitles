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
  const wasOpenRef = useRef(false);

  useEffect(() => {
    // Only set the input when the modal first opens, not on every currentTime change
    if (isOpen && !wasOpenRef.current) {
      setInput(secondsToTimeString(currentTime));
      setError("");
      setTimeout(() => {
        (inputRef?.current || localInputRef.current)?.focus();
      }, 0);
    }
    wasOpenRef.current = isOpen;
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

  // Modal animation - hooks must be called before any conditional returns
  const backdropAnimation = useSpring({
    opacity: isOpen ? 1 : 0,
    config: animationConfig.smooth,
  });

  const modalAnimation = useSpring({
    transform: isOpen ? "scale(1)" : "scale(0.85)",
    opacity: isOpen ? 1 : 0,
    config: springConfig.wobbly,
  });

  if (!isOpen) return null;

  return (
    <animated.div className="modal-overlay" style={backdropAnimation}>
      <animated.div
        className="modal-content p-8 flex flex-col items-center"
        style={modalAnimation}
      >
        <div className="mb-6 flex flex-col items-center">
          <div
            className="w-12 h-12 mb-4 rounded-lg flex items-center justify-center"
            style={{ background: 'var(--accent)' }}
          >
            <svg
              className="w-6 h-6"
              style={{ color: 'var(--accent-text)' }}
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
          <h2
            className="text-xl font-semibold mb-1"
            style={{ color: 'var(--text-primary)' }}
          >
            Jump to Time
          </h2>
          <p
            className="text-sm text-center leading-relaxed"
            style={{ color: 'var(--text-secondary)' }}
          >
            Enter the time to jump to.{' '}
            <span style={{ color: 'var(--accent)' }} className="font-mono">
              20:35 or 1:30:45
            </span>
          </p>
        </div>
        <input
          ref={inputRef || localInputRef}
          className="input-base text-center text-lg font-mono mb-3"
          placeholder="mm:ss or hh:mm:ss"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          autoFocus
        />
        {error && (
          <div
            className="text-sm mb-4 p-3 rounded-md w-full"
            style={{
              color: 'var(--c-error)',
              background: 'oklch(65% 0.20 25 / 0.10)',
              border: '1px solid oklch(65% 0.20 25 / 0.30)',
            }}
          >
            {error}
          </div>
        )}
        <div className="flex w-full gap-3 mt-2">
          <button className="btn-secondary flex-1" onClick={onClose}>
            Cancel
          </button>
          <button className="btn-primary flex-1" onClick={handleOk}>
            Jump
          </button>
        </div>
      </animated.div>
    </animated.div>
  );
};
