/**
 * ImageModal - Modal component for displaying enlarged images
 * Used for viewing screenshots and other images in full size
 */

import React from "react";
import { useSpring, animated, config as springConfig } from "react-spring";
import { animationConfig } from "../../utils/animations";

interface ImageModalProps {
  imageUrl: string;
  onClose: () => void;
}

export const ImageModal: React.FC<ImageModalProps> = ({ imageUrl, onClose }) => {
  // Prevent closing modal when clicking on the image itself
  const handleImageClick = (e: React.MouseEvent) => {
    e.stopPropagation();
  };

  // Modal animation
  const backdropAnimation = useSpring({
    opacity: 1,
    config: animationConfig.smooth,
    from: { opacity: 0 },
  });

  const modalAnimation = useSpring({
    transform: "scale(1)",
    opacity: 1,
    config: springConfig.stiff,
    from: { transform: "scale(0.95)", opacity: 0 },
  });

  return (
    <animated.div
      className="fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center z-50 p-4"
      style={backdropAnimation}
      onClick={onClose} // Close when clicking backdrop
    >
      <animated.div
        className="relative p-2 rounded-xl max-w-6xl max-h-[90vh]"
        style={{
          ...modalAnimation,
          backgroundColor: 'var(--bg-surface)',
          border: '1px solid var(--border-subtle)',
          boxShadow: '0 24px 64px oklch(0% 0 0 / 0.6)',
        }}
        onClick={handleImageClick}
      >
        <img
          src={imageUrl}
          alt="Enlarged screenshot"
          className="block w-[900px] max-h-[85vh] object-contain rounded-lg"
        />
        <button
          onClick={onClose}
          className="absolute -top-3 -right-3 rounded-full p-1.5 transition-all duration-150 hover:scale-110 focus:outline-none"
          style={{
            backgroundColor: 'var(--bg-overlay)',
            color: 'var(--text-secondary)',
            border: '1px solid var(--border-subtle)',
          }}
          onMouseEnter={e => (e.currentTarget.style.color = 'var(--text-primary)')}
          onMouseLeave={e => (e.currentTarget.style.color = 'var(--text-secondary)')}
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
      </animated.div>
    </animated.div>
  );
};
