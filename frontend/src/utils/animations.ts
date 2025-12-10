import { useSpring, useTrail, config } from 'react-spring';

/**
 * Animation config presets for consistent timing
 */
export const animationConfig = {
  snappy: { ...config.wobbly, duration: 300 },
  smooth: { ...config.molasses, duration: 500 },
  fast: { ...config.stiff, duration: 150 },
  gentle: { ...config.gentle, duration: 400 },
};

/**
 * Segment card hover animation
 * Scales card up slightly on hover
 */
export const useSegmentCardAnimation = (isHovered: boolean) => {
  return useSpring({
    transform: isHovered ? 'scale(1.02)' : 'scale(1)',
    config: animationConfig.smooth,
  });
};

/**
 * Segment card active animation
 * Scales card on click with spring bounce
 */
export const useSegmentCardActiveAnimation = (isActive: boolean) => {
  return useSpring({
    transform: isActive ? 'scale(1.01)' : 'scale(1)',
    boxShadow: isActive
      ? '0 10px 25px rgba(59, 130, 246, 0.3)'
      : '0 2px 8px rgba(0, 0, 0, 0.05)',
    config: animationConfig.snappy,
  });
};

/**
 * Staggered entrance animation for transcript segments
 * Each segment fades and slides in with a delay
 */
export const useTranscriptListAnimation = (itemCount: number) => {
  return useTrail(itemCount, {
    from: { opacity: 0, transform: 'translateY(20px)' },
    to: { opacity: 1, transform: 'translateY(0px)' },
    config: animationConfig.gentle,
  });
};

/**
 * Modal/Dialog spring entrance animation
 * Modal bounces slightly when appearing
 */
export const useModalAnimation = (isOpen: boolean) => {
  return useSpring({
    opacity: isOpen ? 1 : 0,
    transform: isOpen ? 'scale(1)' : 'scale(0.95)',
    config: config.wobbly,
  });
};

/**
 * Button press animation
 * Button slightly compresses when clicked
 */
export const useButtonPressAnimation = (isPressed: boolean) => {
  return useSpring({
    transform: isPressed ? 'scale(0.95)' : 'scale(1)',
    config: animationConfig.fast,
  });
};

/**
 * Loading spinner rotation animation
 * Smooth continuous rotation
 */
export const useSpinnerAnimation = () => {
  return useSpring({
    from: { rotate: 0 },
    to: async (next) => {
      while (true) {
        await next({ rotate: 360 });
      }
    },
    config: { duration: 1000 },
    loop: true,
  });
};

/**
 * Pulse animation for loading states
 * Opacity pulses between values
 */
export const usePulseAnimation = () => {
  return useSpring({
    from: { opacity: 0.6 },
    to: async (next) => {
      while (true) {
        await next({ opacity: 1 });
        await next({ opacity: 0.6 });
      }
    },
    config: { duration: 1500 },
    loop: true,
  });
};

/**
 * Counter animation for statistics
 * Counts from 0 to target number
 */
export const useCounterAnimation = (value: number, duration: number = 1000) => {
  return useSpring({
    from: { count: 0 },
    to: { count: value },
    config: { duration },
  });
};

/**
 * File upload drag animation
 * Icon bounces and area pulses on drag
 */
export const useUploadDragAnimation = (isDragging: boolean) => {
  return useSpring({
    transform: isDragging ? 'scale(1.08)' : 'scale(1)',
    borderColor: isDragging ? 'rgb(99, 102, 241)' : 'rgb(209, 213, 219)',
    backgroundColor: isDragging ? 'rgb(238, 242, 255)' : 'rgb(248, 250, 252)',
    config: animationConfig.snappy,
  });
};

/**
 * Success checkmark animation
 * Checkmark draws itself and bounces
 */
export const useSuccessAnimation = (isSuccess: boolean) => {
  return useSpring({
    opacity: isSuccess ? 1 : 0,
    transform: isSuccess ? 'scale(1)' : 'scale(0)',
    config: config.wobbly,
  });
};

/**
 * Tab indicator animation
 * Animates the underline to new tab position
 */
export const useTabIndicatorAnimation = (position: number, width: number) => {
  return useSpring({
    transform: `translateX(${position}px)`,
    width: width,
    config: animationConfig.smooth,
  });
};
