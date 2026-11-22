import { match } from "ts-pattern";
import { Spinner } from "./controls";
import type { IndexingStatus, ReindexStatus } from "./hooks/useChatIndexing";

interface ChatStatusBannersProps {
  reindexStatus: ReindexStatus;
  indexingStatus: IndexingStatus;
}

const SUCCESS_TONE = { background: "oklch(70% 0.15 145 / 0.08)", borderColor: "oklch(70% 0.15 145 / 0.25)", color: "oklch(70% 0.15 145)" };
const FAILURE_TONE = { background: "oklch(65% 0.20 25 / 0.08)", borderColor: "oklch(65% 0.20 25 / 0.25)", color: "oklch(65% 0.20 25)" };

const CheckIcon = () => (
  <svg className="w-4 h-4" style={{ color: "var(--c-success)" }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
  </svg>
);

const WarningIcon = () => (
  <svg className="w-4 h-4" style={{ color: "var(--c-error)" }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth={2}
      d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
    />
  </svg>
);

const IndexingBanner: React.FC<{ icon: React.ReactNode; color: string; message: string }> = ({ icon, color, message }) => (
  <div className="mt-3 px-3 py-2 rounded-lg flex items-center gap-2 border" style={{ background: "var(--bg-overlay)", borderColor: "var(--border-subtle)" }}>
    {icon}
    <p className="text-sm" style={{ color }}>{message}</p>
  </div>
);

const ReindexBanner: React.FC<{ tone: React.CSSProperties; message: string }> = ({ tone, message }) => (
  <div className="mt-2 px-3 py-2 rounded-lg flex items-center gap-2 text-sm border" style={tone}>
    <span>{message}</span>
  </div>
);

export const ChatStatusBanners: React.FC<ChatStatusBannersProps> = ({ reindexStatus, indexingStatus }) => (
  <div className="px-4 py-2" style={{ background: "var(--bg-surface)" }}>
    {match(reindexStatus)
      .with({ kind: "idle" }, { kind: "running" }, () => null)
      .with({ kind: "started" }, () => (
        <ReindexBanner tone={SUCCESS_TONE} message="Re-indexing started — visual search will update in a few minutes." />
      ))
      .with({ kind: "failed" }, () => (
        <ReindexBanner tone={FAILURE_TONE} message="Re-indexing failed. Please try again." />
      ))
      .exhaustive()}

    {match(indexingStatus)
      .with({ kind: "idle" }, () => null)
      .with({ kind: "indexing" }, () => (
        <IndexingBanner icon={<Spinner />} color="var(--text-secondary)" message="Indexing video for chat…" />
      ))
      .with({ kind: "done" }, ({ imagesIndexed }) => (
        <IndexingBanner
          icon={<CheckIcon />}
          color="var(--c-success)"
          message={imagesIndexed ? "Video and images indexed" : "Video indexed, images skipped"}
        />
      ))
      .with({ kind: "failed" }, () => (
        <IndexingBanner icon={<WarningIcon />} color="var(--c-error)" message="Indexing failed" />
      ))
      .exhaustive()}
  </div>
);
