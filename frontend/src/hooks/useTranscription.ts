/**
 * useTranscription - Custom hook for managing transcription state and processing
 * Handles transcription API calls, processing status, and state management
 */

import { useState, useRef } from "react";
import { match, P } from "ts-pattern";
import {
  transcribeLocalStream,
  type TranscriptionResponse,
} from "../services/api";

type ProcessingStage =
  | "uploading"
  | "transcribing"
  | "translating"
  | "extracting"
  | "complete";

interface ProcessingStatus {
  stage: ProcessingStage;
  progress: number;
}

export const useTranscription = () => {
  const [transcription, setTranscription] = useState<TranscriptionResponse | null>(null);
  const [processingStatus, setProcessingStatus] = useState<ProcessingStatus | null>(null);
  const [elapsedTime, setElapsedTime] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [isPolling] = useState(false); // Read-only for now, polling managed by component
  const processingTimer = useRef<NodeJS.Timeout | null>(null);

  const startTimer = () => {
    if (processingTimer.current) {
      clearInterval(processingTimer.current);
    }
    setElapsedTime(0);
    processingTimer.current = setInterval(() => {
      setElapsedTime((prev) => prev + 1);
    }, 1000);
  };

  const stopTimer = () => {
    if (processingTimer.current) {
      clearInterval(processingTimer.current);
      processingTimer.current = null;
    }
  };

  const resetState = () => {
    setTranscription(null);
    setProcessingStatus(null);
    setError(null);
    setElapsedTime(0);
    stopTimer();
  };

  const handleStartTranscription = async (
    file: File,
    transcriptionMethod: "local",
    _selectedLanguage: string // Prefixed with _ to indicate intentionally unused
  ) => {
    setProcessingStatus({ stage: "uploading", progress: 0 });
    setError(null);
    startTimer();

    try {
      // Use ts-pattern for type-safe transcription method selection
      const result = await match(transcriptionMethod)
        .with("local", async () => {
          // Use streaming version with real-time progress
          const data = await transcribeLocalStream(file, (stage, progress) => {
            setProcessingStatus({
              stage: stage as ProcessingStage,
              progress: progress,
            });
          });

          setTranscription(data);
          setProcessingStatus({ stage: "complete", progress: 100 });
          stopTimer();
          return data;
        })
        .exhaustive(); // Ensures all method types are handled

      return result;
    } catch (error) {
      stopTimer();

      // Use ts-pattern for type-safe error handling
      const errorMessage = match(error)
        .with(P.instanceOf(Error), (err) =>
          match(err.message)
            .when(
              (msg) => msg.toLowerCase().includes("network"),
              () => "Network error. Please check your connection and try again."
            )
            .when(
              (msg) => msg.toLowerCase().includes("timeout"),
              () => "Request timed out. Please try again."
            )
            .when(
              (msg) => msg.toLowerCase().includes("file"),
              () => "File error. Please check the file and try again."
            )
            .otherwise(() => err.message)
        )
        .otherwise(() => "An unexpected error occurred during transcription");

      setError(errorMessage);
      setProcessingStatus({ stage: "complete", progress: 0 });
      throw error;
    }
  };

  return {
    transcription,
    setTranscription,
    processingStatus,
    setProcessingStatus,
    elapsedTime,
    error,
    setError,
    isPolling,
    handleStartTranscription,
    resetState,
  };
};
