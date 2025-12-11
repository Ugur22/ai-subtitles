/**
 * useSummaries - Custom hook for managing summary generation and state
 * Handles summary API calls, screenshot fetching, and state management
 */

import { useState } from "react";
import axios from "axios";
import { timeToSeconds } from "../utils/time";
import type { TranscriptionResponse } from "../services/api";

interface SummarySection {
  title: string;
  start: string;
  end: string;
  summary: string;
  screenshot_url?: string | null;
}

interface UseSummariesOptions {
  transcription: TranscriptionResponse | null;
}

export const useSummaries = (options: UseSummariesOptions) => {
  const { transcription } = options;

  const [summaries, setSummaries] = useState<SummarySection[]>([]);
  const [summaryLoading, setSummaryLoading] = useState(false);

  const fetchScreenshotsForSummaries = async (
    summaryData: SummarySection[]
  ): Promise<SummarySection[]> => {
    try {
      // Get the current transcription data
      const response = await axios.get(
        "http://localhost:8000/current_transcription/"
      );

      if (response.status !== 200) {
        console.error(`Error fetching transcription data: ${response.status}`);
        return summaryData;
      }

      const segments = response.data.transcription.segments;

      // Match summary sections with segment screenshots
      const enhancedSummaries = summaryData.map((summary: SummarySection) => {
        // Strategy 1: Find a segment close to the start time (within 5 seconds)
        let matchingSegment = segments.find(
          (segment: any) =>
            Math.abs(
              timeToSeconds(segment.start_time) - timeToSeconds(summary.start)
            ) < 5
        );

        // Strategy 2: Find a segment within the summary time range
        if (!matchingSegment) {
          const summaryStartTime = timeToSeconds(summary.start);
          const summaryEndTime = timeToSeconds(summary.end);

          matchingSegment = segments.find((segment: any) => {
            const segmentTime = timeToSeconds(segment.start_time);
            return (
              segmentTime >= summaryStartTime && segmentTime <= summaryEndTime
            );
          });
        }

        // Strategy 3: Take the closest segment
        if (!matchingSegment) {
          let closestSegment = segments[0];
          let closestDiff = Math.abs(
            timeToSeconds(segments[0].start_time) - timeToSeconds(summary.start)
          );

          for (const segment of segments) {
            const diff = Math.abs(
              timeToSeconds(segment.start_time) - timeToSeconds(summary.start)
            );
            if (diff < closestDiff) {
              closestDiff = diff;
              closestSegment = segment;
            }
          }

          matchingSegment = closestSegment;
        }

        return {
          ...summary,
          screenshot_url: matchingSegment?.screenshot_url || null,
        };
      });

      return enhancedSummaries;
    } catch (error) {
      console.error("Error getting screenshots for summaries:", error);
      return summaryData;
    }
  };

  const generateSummaries = async () => {
    setSummaryLoading(true);
    try {
      console.log("Generating summaries...");
      const response = await axios.post(
        "http://localhost:8000/generate_summary/"
      );

      const summaryData = response.data.summaries || [];
      const responseFilename = response.data.filename;

      // Filename validation
      if (
        transcription &&
        responseFilename &&
        transcription.filename &&
        responseFilename !== transcription.filename
      ) {
        console.warn(
          "Summary filename mismatch:",
          responseFilename,
          "vs",
          transcription.filename
        );
      }

      if (!summaryData || summaryData.length === 0) {
        console.warn("No summary data received");
        return;
      }

      // First set basic summaries
      setSummaries(summaryData);

      // Then enhance with screenshots
      try {
        const enhancedSummaries = await fetchScreenshotsForSummaries(
          summaryData
        );
        setSummaries(enhancedSummaries);
      } catch (screenshotError) {
        console.error(
          "Error adding screenshots to summaries:",
          screenshotError
        );
      }
    } catch (error) {
      console.error("Error generating summaries:", error);
    } finally {
      setSummaryLoading(false);
    }
  };

  const resetSummaries = () => {
    setSummaries([]);
  };

  return {
    summaries,
    setSummaries,
    summaryLoading,
    generateSummaries,
    resetSummaries,
  };
};
