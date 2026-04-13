import React from "react";
import { match } from "ts-pattern";

interface ProcessingStatus {
  stage: "uploading" | "downloading" | "extracting" | "transcribing" | "translating" | "complete";
  progress: number;
}

interface ProcessingOverlayProps {
  isVisible: boolean;
  processingStatus: ProcessingStatus | null;
  elapsedTime: number;
  file: File | null;
  videoRef: HTMLVideoElement | null;
}

const stageOrder = ["uploading", "downloading", "extracting", "transcribing", "translating", "complete"];

const steps: Array<{ stage: "uploading" | "extracting" | "transcribing"; label: string; activeLabel: string; doneLabel: string }> = [
  { stage: "uploading", label: "Upload file", activeLabel: "Uploading file…", doneLabel: "File uploaded" },
  { stage: "extracting", label: "Extract audio", activeLabel: "Extracting audio…", doneLabel: "Audio extracted" },
  { stage: "transcribing", label: "Transcribe speech", activeLabel: "Transcribing speech…", doneLabel: "Speech transcribed" },
];

export const ProcessingOverlay: React.FC<ProcessingOverlayProps> = React.memo(({
  isVisible,
  processingStatus,
  elapsedTime,
  file,
  videoRef,
}) => {
  if (!isVisible) return null;

  const currentStageIndex = processingStatus ? stageOrder.indexOf(processingStatus.stage) : -1;

  const getMainMessage = (stage: ProcessingStatus["stage"]) =>
    match(stage)
      .with("uploading", () => "Uploading file")
      .with("downloading", () => "Downloading from cloud")
      .with("extracting", () => "Preparing audio")
      .with("transcribing", () => "Transcribing")
      .with("translating", () => "Translating")
      .with("complete", () => "Complete")
      .exhaustive();

  const getDescription = (stage: ProcessingStatus["stage"]) =>
    match(stage)
      .with("uploading", () => "Sending your file to cloud storage")
      .with("downloading", () => "Server is downloading the file")
      .with("extracting", () => "Extracting and optimizing audio")
      .with("transcribing", () =>
        videoRef
          ? `Processing ${Math.floor(videoRef.duration / 60)} min of audio. This may take a few minutes.`
          : "Analyzing speech and converting to text"
      )
      .with("translating", () => "Converting text to your preferred language")
      .with("complete", () => "Your transcription is ready!")
      .exhaustive();

  return (
    <div
      className="fixed inset-0 z-50 flex flex-col items-center justify-center"
      style={{ backgroundColor: 'oklch(11% 0.008 250 / 0.92)' }}
    >
      <div style={{
        backgroundColor: 'var(--bg-surface)',
        border: '1px solid var(--border-subtle)',
        borderRadius: '8px',
        padding: '28px 32px',
        maxWidth: '420px',
        width: '100%',
        margin: '0 16px',
      }}>

        {/* File info */}
        {file && (
          <div style={{ marginBottom: '24px', paddingBottom: '20px', borderBottom: '1px solid var(--border-subtle)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <div style={{
                width: '36px', height: '36px', flexShrink: 0,
                backgroundColor: 'var(--accent-dim)', border: '1px solid var(--accent)',
                borderRadius: '6px', display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}>
                <svg style={{ width: '16px', height: '16px', color: 'var(--accent)' }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <p style={{ fontSize: '13px', fontWeight: 500, color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {file.name}
                </p>
                <p style={{ fontSize: '12px', color: 'var(--text-tertiary)', marginTop: '2px' }}>
                  {(file.size / (1024 * 1024)).toFixed(1)} MB
                  {videoRef && ` · ${Math.floor(videoRef.duration / 60)}:${String(Math.floor(videoRef.duration % 60)).padStart(2, "0")}`}
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Steps */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', marginBottom: '24px' }}>
          {steps.map(({ stage, label, activeLabel, doneLabel }) => {
            const stepIndex = stageOrder.indexOf(stage);
            const isActive = processingStatus?.stage === stage;
            const isDone = currentStageIndex > stepIndex;
            const isPending = !isActive && !isDone;

            return (
              <div key={stage} style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                <div style={{
                  width: '24px', height: '24px', borderRadius: '50%', flexShrink: 0,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  backgroundColor: isDone ? 'var(--c-success)' : isActive ? 'var(--accent)' : 'var(--bg-overlay)',
                  border: isPending ? '1px solid var(--border-default)' : 'none',
                  transition: 'background-color 300ms ease',
                }}>
                  {isDone ? (
                    <svg style={{ width: '12px', height: '12px', color: 'oklch(11% 0.008 250)' }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                    </svg>
                  ) : isActive ? (
                    <svg style={{ width: '12px', height: '12px', color: 'var(--accent-text)', animation: 'spin 1s linear infinite' }} fill="none" viewBox="0 0 24 24">
                      <circle style={{ opacity: 0.25 }} cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path style={{ opacity: 0.75 }} fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                  ) : (
                    <span style={{ fontSize: '10px', fontWeight: 600, color: 'var(--text-tertiary)', fontVariantNumeric: 'tabular-nums' }}>
                      {steps.indexOf(steps.find(s => s.stage === stage)!) + 1}
                    </span>
                  )}
                </div>
                <span style={{
                  fontSize: '13px',
                  fontWeight: isActive ? 500 : 400,
                  color: isDone ? 'var(--text-secondary)' : isActive ? 'var(--text-primary)' : 'var(--text-tertiary)',
                  transition: 'color 300ms ease',
                }}>
                  {isDone ? doneLabel : isActive ? activeLabel : label}
                </span>
              </div>
            );
          })}
        </div>

        {/* Current message */}
        {processingStatus?.stage && (
          <div style={{ marginBottom: '20px' }}>
            <p style={{ fontSize: '13px', fontWeight: 500, color: 'var(--text-primary)', marginBottom: '4px' }}>
              {getMainMessage(processingStatus.stage)}
            </p>
            <p style={{ fontSize: '12px', color: 'var(--text-tertiary)' }}>
              {getDescription(processingStatus.stage)}
            </p>
          </div>
        )}

        {/* Elapsed time */}
        {elapsedTime > 0 && (
          <div style={{ marginBottom: '20px' }}>
            <span style={{ fontSize: '12px', color: 'var(--text-tertiary)', fontVariantNumeric: 'tabular-nums' }}>
              {Math.floor(elapsedTime / 60)}:{String(elapsedTime % 60).padStart(2, "0")} elapsed
            </span>
          </div>
        )}

        {/* Progress bar */}
        <div style={{ width: '100%', height: '3px', backgroundColor: 'var(--border-subtle)', borderRadius: '2px', overflow: 'hidden' }}>
          {processingStatus?.stage === "complete" ? (
            <div style={{ height: '100%', width: '100%', backgroundColor: 'var(--c-success)' }} />
          ) : (
            <div
              className="animate-progress-indeterminate"
              style={{ height: '100%', width: '40%', backgroundColor: 'var(--accent)', borderRadius: '2px' }}
            />
          )}
        </div>
      </div>
    </div>
  );
});
