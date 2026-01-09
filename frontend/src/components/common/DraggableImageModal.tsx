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
      className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50"
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
          <button
            onClick={onClose}
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
