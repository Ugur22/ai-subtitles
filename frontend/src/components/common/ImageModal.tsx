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
    config: springConfig.wobbly,
    from: { transform: "scale(0.9)", opacity: 0 },
  });

  return (
    <animated.div
      className="fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center z-50 p-4"
      style={backdropAnimation}
      onClick={onClose} // Close when clicking backdrop
    >
      <animated.div
        className="relative bg-white p-3 rounded-2xl shadow-2xl max-w-6xl max-h-[90vh]"
        style={modalAnimation}
        onClick={handleImageClick} // Prevent closing on image container click
      >
        <img
          src={imageUrl}
          alt="Enlarged screenshot"
          className="block w-[900px] max-h-[85vh] object-contain rounded-xl"
        />
        <button
          onClick={onClose}
          className="absolute -top-2 -right-2 bg-white rounded-full p-2 text-gray-700 hover:bg-gray-100 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500 shadow-lg transition-all duration-200 hover:scale-110"
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
