import React from "react";
import { Job } from "../../../types/job";
import { formatRelativeTime } from "../../../utils/time";

interface RecentTranscriptionsProps {
  jobs: Job[];
  onViewJob: (job: Job) => void;
  onViewAll: () => void;
  isLoading?: boolean;
}

const SkeletonRow: React.FC = () => (
  <div
    style={{
      display: "flex",
      alignItems: "center",
      gap: "12px",
      width: "100%",
      padding: "10px 12px",
    }}
  >
    <div
      className="recent-skeleton"
      style={{
        width: "32px",
        height: "32px",
        borderRadius: "8px",
        flexShrink: 0,
      }}
    />
    <div style={{ flex: 1, minWidth: 0 }}>
      <div
        className="recent-skeleton"
        style={{
          height: "12px",
          width: "70%",
          borderRadius: "4px",
          marginBottom: "6px",
        }}
      />
      <div
        className="recent-skeleton"
        style={{
          height: "10px",
          width: "35%",
          borderRadius: "4px",
        }}
      />
    </div>
  </div>
);

export const RecentTranscriptions: React.FC<RecentTranscriptionsProps> = ({
  jobs,
  onViewJob,
  onViewAll,
  isLoading = false,
}) => {
  const recent = jobs
    .filter((j) => j.status === "completed")
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    .slice(0, 5);

  if (!isLoading && recent.length === 0) return null;

  return (
    <div style={{ maxWidth: "720px", margin: "48px auto 0", padding: "0 24px" }}>
      {/* Header */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: "12px",
        }}
      >
        <span
          style={{
            fontSize: "11px",
            fontWeight: 600,
            textTransform: "uppercase",
            letterSpacing: "0.06em",
            color: "var(--text-tertiary)",
          }}
        >
          Recent
        </span>
        {!isLoading && (
          <button
            onClick={onViewAll}
            className="btn-ghost"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "4px",
              padding: "4px 8px",
              fontSize: "12px",
              fontWeight: 500,
            }}
          >
            View all
            <svg
              style={{ width: "12px", height: "12px" }}
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              strokeWidth={2}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
            </svg>
          </button>
        )}
      </div>

      {/* Rows */}
      <div style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
        {isLoading && recent.length === 0 && (
          <>
            <SkeletonRow />
            <SkeletonRow />
            <SkeletonRow />
          </>
        )}
        {recent.map((job) => {
          const duration = job.result_json?.transcription?.duration;
          return (
            <button
              key={job.job_id}
              onClick={() => onViewJob(job)}
              style={{
                display: "flex",
                alignItems: "center",
                gap: "12px",
                width: "100%",
                padding: "10px 12px",
                borderRadius: "8px",
                border: "1px solid transparent",
                backgroundColor: "transparent",
                cursor: "pointer",
                textAlign: "left",
                transition: "background-color 150ms ease",
              }}
              onMouseEnter={(e) => {
                (e.currentTarget as HTMLButtonElement).style.backgroundColor = "var(--bg-subtle)";
              }}
              onMouseLeave={(e) => {
                (e.currentTarget as HTMLButtonElement).style.backgroundColor = "transparent";
              }}
            >
              {/* File icon tile */}
              <div
                style={{
                  width: "32px",
                  height: "32px",
                  borderRadius: "8px",
                  backgroundColor: "var(--accent-dim)",
                  border: "1px solid var(--accent-border)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  flexShrink: 0,
                }}
              >
                <svg
                  style={{ width: "14px", height: "14px", color: "var(--accent)" }}
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                  strokeWidth={1.8}
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M9 19V6l2 5 2-10 2 11 2-3v10"
                  />
                </svg>
              </div>

              {/* Text column */}
              <div style={{ flex: 1, minWidth: 0 }}>
                <p
                  style={{
                    fontSize: "14px",
                    fontWeight: 500,
                    color: "var(--text-primary)",
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    margin: 0,
                  }}
                >
                  {job.filename}
                </p>
                <p
                  style={{
                    fontSize: "12px",
                    color: "var(--text-tertiary)",
                    marginTop: "2px",
                    margin: 0,
                  }}
                >
                  {formatRelativeTime(job.created_at)}
                  {duration ? ` · ${duration}` : ""}
                </p>
              </div>

              {/* Chevron */}
              <svg
                style={{
                  width: "14px",
                  height: "14px",
                  color: "var(--text-tertiary)",
                  flexShrink: 0,
                }}
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
                strokeWidth={2}
              >
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
              </svg>
            </button>
          );
        })}
      </div>
    </div>
  );
};
