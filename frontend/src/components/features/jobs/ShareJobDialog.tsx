/**
 * ShareJobDialog - Modal dialog for sharing job results
 * Displays a shareable URL with copy functionality and feedback
 */

import { useState } from "react";
import { Job } from "../../../types/job";

interface ShareJobDialogProps {
  job: Job;
  onClose: () => void;
}

export const ShareJobDialog: React.FC<ShareJobDialogProps> = ({
  job,
  onClose,
}) => {
  const [copied, setCopied] = useState(false);

  const shareUrl = `${window.location.origin}/jobs/${job.job_id}?token=${job.access_token}`;

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(shareUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (error) {
      console.error("Failed to copy to clipboard:", error);
    }
  };

  const handleBackdropClick = (e: React.MouseEvent) => {
    if (e.target === e.currentTarget) {
      onClose();
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      onClose();
    }
  };

  return (
    <div
      className="modal-overlay"
      onClick={handleBackdropClick}
      onKeyDown={handleKeyDown}
      role="dialog"
      aria-modal="true"
      aria-labelledby="share-dialog-title"
    >
      <div className="modal-content p-6">
        <div className="flex items-start justify-between mb-4">
          <h3
            id="share-dialog-title"
            className="text-lg font-semibold"
            style={{ color: 'var(--text-primary)' }}
          >
            Share Transcription
          </h3>
          <button
            onClick={onClose}
            className="transition-colors"
            style={{ color: 'var(--text-tertiary)' }}
            aria-label="Close dialog"
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
                strokeWidth={2}
                d="M6 18L18 6M6 6l12 12"
              />
            </svg>
          </button>
        </div>

        <p className="text-sm mb-4" style={{ color: 'var(--text-secondary)' }}>
          Anyone with this link can view the transcription results. The link
          includes access credentials.
        </p>

        <div className="flex gap-2 mb-4">
          <input
            type="text"
            value={shareUrl}
            readOnly
            className="input-base flex-1 font-mono text-xs"
            onClick={(e) => e.currentTarget.select()}
            aria-label="Shareable URL"
          />
          <button
            onClick={handleCopy}
            className="btn-primary"
            style={
              copied
                ? { background: 'var(--c-success)', color: 'var(--accent-text)' }
                : undefined
            }
            aria-label={copied ? "Copied!" : "Copy URL"}
          >
            {copied ? (
              <span className="flex items-center gap-1.5">
                <svg
                  className="w-4 h-4"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M5 13l4 4L19 7"
                  />
                </svg>
                Copied!
              </span>
            ) : (
              <span className="flex items-center gap-1.5">
                <svg
                  className="w-4 h-4"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"
                  />
                </svg>
                Copy
              </span>
            )}
          </button>
        </div>

        <div
          className="rounded-md p-3 mb-4"
          style={{
            background: 'var(--accent-dim)',
            border: '1px solid var(--accent-border)',
          }}
        >
          <div className="flex gap-2">
            <svg
              className="w-5 h-5 flex-shrink-0"
              style={{ color: 'var(--accent)' }}
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
              />
            </svg>
            <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>
              This link will remain valid as long as the job exists in the
              system (up to 7 days).
            </p>
          </div>
        </div>

        <button onClick={onClose} className="btn-secondary w-full">
          Close
        </button>
      </div>
    </div>
  );
};
