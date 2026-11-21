import { Spinner } from "./controls";
import type { IndexingStatus } from "./hooks/useChatIndexing";

interface ChatStatusBannersProps {
  reindexStatus: string | null;
  indexingStatus: IndexingStatus | null;
}

export const ChatStatusBanners: React.FC<ChatStatusBannersProps> = ({ reindexStatus, indexingStatus }) => (
  <div className="px-4 py-2" style={{ background: "var(--bg-surface)" }}>
    {reindexStatus && (
      <div
        className="mt-2 px-3 py-2 rounded-lg flex items-center gap-2 text-sm border"
        style={
          reindexStatus.includes("failed")
            ? { background: "oklch(65% 0.20 25 / 0.08)", borderColor: "oklch(65% 0.20 25 / 0.25)", color: "oklch(65% 0.20 25)" }
            : { background: "oklch(70% 0.15 145 / 0.08)", borderColor: "oklch(70% 0.15 145 / 0.25)", color: "oklch(70% 0.15 145)" }
        }
      >
        <span>{reindexStatus}</span>
      </div>
    )}

    {indexingStatus && (
      <div className="mt-3 px-3 py-2 rounded-lg flex items-center gap-2 border" style={{ background: "var(--bg-overlay)", borderColor: "var(--border-subtle)" }}>
        {indexingStatus.kind === "indexing" && <Spinner />}
        {indexingStatus.kind === "done" && (
          <svg
            className="w-4 h-4"
            style={{ color: "var(--c-success)" }}
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
        )}
        {indexingStatus.kind === "failed" && (
          <svg
            className="w-4 h-4"
            style={{ color: "var(--c-error)" }}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
            />
          </svg>
        )}
        <p
          className="text-sm"
          style={{
            color: indexingStatus.kind === "done"
              ? "var(--c-success)"
              : indexingStatus.kind === "failed"
                ? "var(--c-error)"
                : "var(--text-secondary)",
          }}
        >
          {indexingStatus.message}
        </p>
      </div>
    )}
  </div>
);
