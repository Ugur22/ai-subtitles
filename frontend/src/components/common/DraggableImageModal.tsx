/**
 * DraggableImageModal - Modal component for displaying enlarged images
 * that can be dragged around the screen for comparison with video
 */

import React, { useState, useEffect, useCallback, useRef } from "react";
import { useSpring, animated } from "react-spring";
import { animationConfig } from "../../utils/animations";

interface DraggableImageModalProps {
  imageUrl: string;
  onClose: () => void;
}

export const DraggableImageModal: React.FC<DraggableImageModalProps> = ({
  imageUrl,
  onClose,
}) => {
  const [isDragging, setIsDragging] = useState(false);
  const [position, setPosition] = useState({ x: 0, y: 0 });
  const [dragOffset, setDragOffset] = useState({ x: 0, y: 0 });
  const [isInitialized, setIsInitialized] = useState(false);
  const [isDimmed, setIsDimmed] = useState(true);
  const modalRef = useRef<HTMLDivElement>(null);

  // Center modal on mount
  useEffect(() => {
    const centerModal = () => {
      if (modalRef.current) {
        const rect = modalRef.current.getBoundingClientRect();
        setPosition({
          x: (window.innerWidth - rect.width) / 2,
          y: (window.innerHeight - rect.height) / 2,
        });
        setIsInitialized(true);
      }
    };

    // Small delay to ensure modal is rendered
    const timer = setTimeout(centerModal, 50);
    return () => clearTimeout(timer);
  }, [imageUrl]);

  // Handle escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  // Mouse event handlers
  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      setIsDragging(true);
      setDragOffset({
        x: e.clientX - position.x,
        y: e.clientY - position.y,
      });
    },
    [position]
  );

  const handleMouseMove = useCallback(
    (e: MouseEvent) => {
      if (!isDragging || !modalRef.current) return;

      const rect = modalRef.current.getBoundingClientRect();
      const minVisible = 100;

      // Calculate new position with boundary constraints
      let newX = e.clientX - dragOffset.x;
      let newY = e.clientY - dragOffset.y;

      // Keep at least minVisible pixels visible on screen
      newX = Math.max(-rect.width + minVisible, Math.min(window.innerWidth - minVisible, newX));
      newY = Math.max(-rect.height + minVisible, Math.min(window.innerHeight - minVisible, newY));

      setPosition({ x: newX, y: newY });
    },
    [isDragging, dragOffset]
  );

  const handleMouseUp = useCallback(() => {
    setIsDragging(false);
  }, []);

  // Add/remove global mouse listeners
  useEffect(() => {
    if (isDragging) {
      window.addEventListener("mousemove", handleMouseMove);
      window.addEventListener("mouseup", handleMouseUp);
    }
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };
  }, [isDragging, handleMouseMove, handleMouseUp]);

  // Touch event handlers for mobile
  const handleTouchStart = useCallback(
    (e: React.TouchEvent) => {
      if (e.touches.length === 1) {
        const touch = e.touches[0];
        setIsDragging(true);
        setDragOffset({
          x: touch.clientX - position.x,
          y: touch.clientY - position.y,
        });
      }
    },
    [position]
  );

  const handleTouchMove = useCallback(
    (e: TouchEvent) => {
      if (!isDragging || !modalRef.current || e.touches.length !== 1) return;

      const touch = e.touches[0];
      const rect = modalRef.current.getBoundingClientRect();
      const minVisible = 100;

      let newX = touch.clientX - dragOffset.x;
      let newY = touch.clientY - dragOffset.y;

      newX = Math.max(-rect.width + minVisible, Math.min(window.innerWidth - minVisible, newX));
      newY = Math.max(-rect.height + minVisible, Math.min(window.innerHeight - minVisible, newY));

      setPosition({ x: newX, y: newY });
    },
    [isDragging, dragOffset]
  );

  const handleTouchEnd = useCallback(() => {
    setIsDragging(false);
  }, []);

  // Add/remove global touch listeners
  useEffect(() => {
    if (isDragging) {
      window.addEventListener("touchmove", handleTouchMove, { passive: false });
      window.addEventListener("touchend", handleTouchEnd);
    }
    return () => {
      window.removeEventListener("touchmove", handleTouchMove);
      window.removeEventListener("touchend", handleTouchEnd);
    };
  }, [isDragging, handleTouchMove, handleTouchEnd]);

  // Backdrop animation (less opaque to see video behind)
  const backdropAnimation = useSpring({
    opacity: 1,
    config: animationConfig.smooth,
    from: { opacity: 0 },
  });

  // Modal position animation (immediate during drag for responsiveness)
  const modalAnimation = useSpring({
    x: position.x,
    y: position.y,
    scale: isInitialized ? 1 : 0.9,
    opacity: isInitialized ? 1 : 0,
    immediate: isDragging,
    config: animationConfig.smooth,
  });

  return (
    <animated.div
      className={`fixed inset-0 z-50 transition-all duration-300 ${
        isDimmed ? "bg-black/50 backdrop-blur-sm" : "bg-transparent"
      }`}
      style={backdropAnimation}
      onClick={onClose}
    >
      <animated.div
        ref={modalRef}
        className="absolute bg-white rounded-2xl shadow-2xl max-w-4xl overflow-hidden"
        style={{
          left: modalAnimation.x,
          top: modalAnimation.y,
          transform: modalAnimation.scale.to((s) => `scale(${s})`),
          opacity: modalAnimation.opacity,
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Drag Handle */}
        <div
          className={`flex items-center justify-between px-4 py-2 bg-gray-100 border-b border-gray-200 select-none ${
            isDragging ? "cursor-grabbing" : "cursor-grab"
          }`}
          onMouseDown={handleMouseDown}
          onTouchStart={handleTouchStart}
        >
          <div className="flex items-center gap-2 text-gray-500 text-sm">
            <svg
              className="w-4 h-4"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth="2"
                d="M4 8h16M4 16h16"
              />
            </svg>
            <span>Drag to move</span>
          </div>

          <div className="flex items-center gap-2">
            {/* Dimming Toggle */}
            <button
              onClick={(e) => {
                e.stopPropagation();
                setIsDimmed(!isDimmed);
              }}
              onMouseDown={(e) => e.stopPropagation()}
              onTouchStart={(e) => e.stopPropagation()}
              className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${
                isDimmed
                  ? "bg-gray-100 text-gray-600 border-2 border-transparent hover:bg-gray-200"
                  : "bg-indigo-100 text-indigo-700 border-2 border-indigo-300"
              }`}
              aria-label={isDimmed ? "Disable dimming" : "Enable dimming"}
            >
              <svg
                className="w-4 h-4"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                {isDimmed ? (
                  // Eye slash (dimming ON - obscured)
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21"
                  />
                ) : (
                  // Eye open (dimming OFF - can see clearly)
                  <>
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"
                    />
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"
                    />
                  </>
                )}
              </svg>
              <span className="hidden sm:inline">
                {isDimmed ? "Dimmed" : "Clear"}
              </span>
            </button>

            {/* Close Button */}
            <button
              onClick={onClose}
              onMouseDown={(e) => e.stopPropagation()}
              onTouchStart={(e) => e.stopPropagation()}
              className="p-1 text-gray-500 hover:text-gray-700 hover:bg-gray-200 rounded-full transition-colors"
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
          </div>
        </div>

        {/* Image Content */}
        <div className="p-3">
          <img
            src={imageUrl}
            alt="Enlarged screenshot"
            className="block max-w-[800px] max-h-[70vh] object-contain rounded-lg"
            draggable={false}
          />
        </div>
      </animated.div>
    </animated.div>
  );
};
