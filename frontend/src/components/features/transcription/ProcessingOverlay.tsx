import React from "react";
import { FaSpinner } from "react-icons/fa";
import { match } from "ts-pattern";

interface ProcessingStatus {
  stage: "uploading" | "extracting" | "transcribing" | "translating" | "complete";
  progress: number;
}

interface ProcessingOverlayProps {
  isVisible: boolean;
  processingStatus: ProcessingStatus | null;
  elapsedTime: number;
  file: File | null;
  videoRef: HTMLVideoElement | null;
}

export const ProcessingOverlay: React.FC<ProcessingOverlayProps> = React.memo(({
  isVisible,
  processingStatus,
  elapsedTime,
  file,
  videoRef,
}) => {
  if (!isVisible) return null;

  // Helper functions using ts-pattern for cleaner conditional logic
  const getMainMessage = (stage: ProcessingStatus["stage"]) =>
    match(stage)
      .with("uploading", () => "Uploading your file...")
      .with("extracting", () => "Preparing audio...")
      .with("transcribing", () => "AI is transcribing...")
      .with("translating", () => "Translating content...")
      .with("complete", () => "Processing complete!")
      .exhaustive();

  const getDescription = (stage: ProcessingStatus["stage"]) =>
    match(stage)
      .with("uploading", () => "Sending your file to our servers")
      .with("extracting", () => "Extracting and optimizing audio for processing")
      .with("transcribing", () =>
        videoRef
          ? `Processing ${Math.floor(
              videoRef.duration / 60
            )} minutes of audio. This may take 2-4 minutes.`
          : "Analyzing speech patterns and converting to text"
      )
      .with("translating", () => "Converting text to your preferred language")
      .with("complete", () => "Your transcription is ready!")
      .exhaustive();

  const getStageLabel = (stage: ProcessingStatus["stage"], isActive: boolean) =>
    match({ stage, isActive })
      .with({ stage: "uploading", isActive: true }, () => "Uploading...")
      .with({ stage: "uploading", isActive: false }, () => "Upload complete")
      .with({ stage: "extracting", isActive: true }, () => "Extracting audio...")
      .with({ stage: "extracting", isActive: false }, () => "Prepare audio")
      .with({ stage: "transcribing", isActive: true }, () => "Transcribing speech...")
      .with({ stage: "transcribing", isActive: false }, () => "Transcription complete")
      .otherwise(() => "Transcribe audio");

  return (
    <div className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-black/70 backdrop-blur-md">
      <div className="bg-white rounded-3xl p-10 shadow-2xl max-w-lg w-full mx-4">
        {/* File Info Header */}
        {file && (
          <div className="mb-6 pb-6 border-b border-gray-200">
            <div className="flex items-center gap-3">
              <div className="flex-shrink-0 w-12 h-12 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-xl flex items-center justify-center">
                <svg
                  className="w-6 h-6 text-white"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M7 4v16M17 4v16M3 8h4m10 0h4M3 12h18M3 16h4m10 0h4M4 20h16a1 1 0 001-1V5a1 1 0 00-1-1H4a1 1 0 00-1 1v14a1 1 0 001 1z"
                  />
                </svg>
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold text-gray-900 truncate">
                  {file.name}
                </p>
                <p className="text-xs text-gray-500">
                  {(file.size / (1024 * 1024)).toFixed(1)} MB
                  {videoRef &&
                    ` • ${Math.floor(videoRef.duration / 60)}:${String(
                      Math.floor(videoRef.duration % 60)
                    ).padStart(2, "0")} duration`}
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Processing Stages */}
        <div className="mb-6 space-y-3">
          {/* Stage 1: Upload */}
          <div className="flex items-center gap-3">
            <div
              className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center ${
                processingStatus?.stage === "uploading"
                  ? "bg-indigo-500 text-white"
                  : "bg-green-500 text-white"
              }`}
            >
              {processingStatus?.stage === "uploading" ? (
                <FaSpinner className="animate-spin" size={14} />
              ) : (
                <svg
                  className="w-4 h-4"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={3}
                    d="M5 13l4 4L19 7"
                  />
                </svg>
              )}
            </div>
            <div className="flex-1">
              <p
                className={`text-sm font-medium ${
                  processingStatus?.stage === "uploading"
                    ? "text-indigo-600"
                    : "text-gray-600"
                }`}
              >
                {processingStatus?.stage &&
                  getStageLabel(processingStatus.stage, processingStatus.stage === "uploading")}
              </p>
            </div>
          </div>

          {/* Stage 2: Extracting */}
          <div className="flex items-center gap-3">
            <div
              className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center ${
                processingStatus?.stage === "extracting"
                  ? "bg-indigo-500 text-white"
                  : processingStatus?.stage &&
                    ["transcribing", "translating", "complete"].includes(
                      processingStatus.stage
                    )
                  ? "bg-green-500 text-white"
                  : "bg-gray-200 text-gray-400"
              }`}
            >
              {processingStatus?.stage === "extracting" ? (
                <FaSpinner className="animate-spin" size={14} />
              ) : processingStatus?.stage &&
                ["transcribing", "translating", "complete"].includes(
                  processingStatus.stage
                ) ? (
                <svg
                  className="w-4 h-4"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={3}
                    d="M5 13l4 4L19 7"
                  />
                </svg>
              ) : (
                <span className="text-xs font-semibold">2</span>
              )}
            </div>
            <div className="flex-1">
              <p
                className={`text-sm font-medium ${
                  processingStatus?.stage === "extracting"
                    ? "text-indigo-600"
                    : processingStatus?.stage &&
                      ["transcribing", "translating", "complete"].includes(
                        processingStatus.stage
                      )
                    ? "text-gray-600"
                    : "text-gray-400"
                }`}
              >
                {processingStatus?.stage &&
                  getStageLabel(processingStatus.stage, processingStatus.stage === "extracting")}
              </p>
            </div>
          </div>

          {/* Stage 3: Transcribing */}
          <div className="flex items-center gap-3">
            <div
              className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center ${
                processingStatus?.stage === "transcribing"
                  ? "bg-indigo-500 text-white"
                  : processingStatus?.stage === "complete"
                  ? "bg-green-500 text-white"
                  : "bg-gray-200 text-gray-400"
              }`}
            >
              {processingStatus?.stage === "transcribing" ? (
                <FaSpinner className="animate-spin" size={14} />
              ) : processingStatus?.stage === "complete" ? (
                <svg
                  className="w-4 h-4"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={3}
                    d="M5 13l4 4L19 7"
                  />
                </svg>
              ) : (
                <span className="text-xs font-semibold">3</span>
              )}
            </div>
            <div className="flex-1">
              <p
                className={`text-sm font-medium ${
                  processingStatus?.stage === "transcribing"
                    ? "text-indigo-600"
                    : processingStatus?.stage === "complete"
                    ? "text-gray-600"
                    : "text-gray-400"
                }`}
              >
                {processingStatus?.stage &&
                  getStageLabel(processingStatus.stage, processingStatus.stage === "transcribing")}
              </p>
            </div>
          </div>
        </div>

        {/* Main Message */}
        <div className="mb-6">
          <div className="flex items-center justify-center gap-3 mb-3">
            <div className="animate-spin">
              <FaSpinner size={24} className="text-indigo-600" />
            </div>
            <h3 className="text-lg font-bold text-gray-900">
              {processingStatus?.stage && getMainMessage(processingStatus.stage)}
            </h3>
          </div>
          <p className="text-sm text-center text-gray-600">
            {processingStatus?.stage && getDescription(processingStatus.stage)}
          </p>
        </div>

        {/* Elapsed Time */}
        {elapsedTime > 0 && (
          <div className="mb-6 text-center">
            <div className="inline-flex items-center gap-2 px-4 py-2 bg-gray-100 rounded-full">
              <svg
                className="w-4 h-4 text-gray-600"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"
                />
              </svg>
              <span className="text-sm font-medium text-gray-700">
                {Math.floor(elapsedTime / 60)}:
                {String(elapsedTime % 60).padStart(2, "0")} elapsed
              </span>
            </div>
          </div>
        )}

        {/* Progress Bar */}
        <div className="w-full h-2 bg-gray-200 rounded-full overflow-hidden">
          <div
            className="h-full bg-gradient-to-r from-indigo-500 to-purple-600 transition-all duration-300"
            style={{
              width: `${processingStatus?.progress || 0}%`,
            }}
          />
        </div>

        {/* Helpful Tip */}
        <div className="mt-6 pt-6 border-t border-gray-200">
          <p className="text-xs text-center text-gray-500">
            💡 Tip: Processing time varies based on audio length and quality
          </p>
        </div>
      </div>
    </div>
  );
});
