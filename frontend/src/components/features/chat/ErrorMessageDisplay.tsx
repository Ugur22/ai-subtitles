import type { Message } from "./types";

export const ErrorMessageDisplay: React.FC<{
  message: Message;
  onRetry: (q: string) => void;
}> = ({ message, onRetry }) => {
  return (
    <div>
      <div className="flex items-center gap-2 mb-2">
        <svg
          className="w-5 h-5 flex-shrink-0"
          style={{ color: "var(--c-error)" }}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z"
          />
        </svg>
        <span className="font-medium text-sm" style={{ color: "var(--c-error)" }}>
          Something went wrong
        </span>
      </div>
      <p className="text-sm mb-3" style={{ color: "var(--text-secondary)" }}>
        {message.content}
      </p>
      {message.retryQuestion && (
        <button
          onClick={() => onRetry(message.retryQuestion!)}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md transition-colors"
          style={{ color: "var(--c-error)", background: "oklch(65% 0.20 25 / 0.12)" }}
        >
          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
            />
          </svg>
          Retry
        </button>
      )}
    </div>
  );
};
