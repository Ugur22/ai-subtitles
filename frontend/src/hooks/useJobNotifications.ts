/**
 * useJobNotifications - Custom hook for browser notifications
 * Manages notification permissions and sends completion alerts
 */

import { useState, useEffect, useCallback } from 'react';

const NOTIFICATION_PROMPTED_KEY = 'ai-subs-notification-prompted';

export const useJobNotifications = () => {
  const [permission, setPermission] = useState<NotificationPermission>('default');
  const [hasPrompted, setHasPrompted] = useState(false);

  // Initialize permission state on mount
  useEffect(() => {
    if ('Notification' in window) {
      setPermission(Notification.permission);
      const prompted = localStorage.getItem(NOTIFICATION_PROMPTED_KEY) === 'true';
      setHasPrompted(prompted);
    }
  }, []);

  /**
   * Request notification permission from the user
   * Only call this after user interaction (e.g., button click)
   */
  const requestPermission = useCallback(async (): Promise<boolean> => {
    if (!('Notification' in window)) {
      console.warn('Browser does not support notifications');
      return false;
    }

    try {
      const result = await Notification.requestPermission();
      setPermission(result);

      // Mark that we've prompted the user
      localStorage.setItem(NOTIFICATION_PROMPTED_KEY, 'true');
      setHasPrompted(true);

      return result === 'granted';
    } catch (error) {
      console.error('Failed to request notification permission:', error);
      return false;
    }
  }, []);

  /**
   * Check if we should prompt the user for notification permission
   * Only prompt after first job completes (lower friction)
   */
  const shouldPrompt = useCallback((): boolean => {
    return (
      'Notification' in window &&
      permission === 'default' &&
      !hasPrompted
    );
  }, [permission, hasPrompted]);

  /**
   * Send a browser notification for job completion
   * Automatically checks permission before sending
   */
  const notifyJobComplete = useCallback((filename: string) => {
    if (!('Notification' in window)) {
      return;
    }

    if (permission !== 'granted') {
      console.debug('Notification permission not granted, skipping notification');
      return;
    }

    try {
      // Check if user is currently viewing the page
      // Skip notification if they're actively looking at it
      if (document.visibilityState === 'visible' && document.hasFocus()) {
        console.debug('User is viewing the page, skipping notification');
        return;
      }

      const notification = new Notification('Transcription Complete!', {
        body: `${filename} is ready to view`,
        icon: '/icon.png',
        badge: '/badge.png',
        tag: 'job-complete', // Replace previous notifications
        requireInteraction: true, // Keep notification visible until user interacts
        silent: false,
      });

      // Auto-focus the window when notification is clicked
      notification.onclick = () => {
        window.focus();
        notification.close();
      };
    } catch (error) {
      console.error('Failed to send notification:', error);
    }
  }, [permission]);

  /**
   * Send a notification for job failure
   */
  const notifyJobFailed = useCallback((filename: string) => {
    if (!('Notification' in window) || permission !== 'granted') {
      return;
    }

    try {
      const notification = new Notification('Transcription Failed', {
        body: `${filename} encountered an error during processing`,
        icon: '/icon.png',
        badge: '/badge.png',
        tag: 'job-failed',
        requireInteraction: true,
      });

      notification.onclick = () => {
        window.focus();
        notification.close();
      };
    } catch (error) {
      console.error('Failed to send failure notification:', error);
    }
  }, [permission]);

  return {
    permission,
    hasPrompted,
    requestPermission,
    shouldPrompt,
    notifyJobComplete,
    notifyJobFailed,
  };
};
