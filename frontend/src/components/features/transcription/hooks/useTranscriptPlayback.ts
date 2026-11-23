import { useCallback, useEffect, useRef, useState } from "react";
import type { RefObject } from "react";
import { timeToSeconds } from "../../../../utils/time";
import type { TranscriptSegment } from "../segments";

const SCROLL_TOP_OFFSET_PX = 100;
const ACTIVE_SEGMENT_RENDER_DELAY_MS = 100;

interface TranscriptPlaybackOptions {
  videoRef: HTMLVideoElement | null;
  transcriptScrollRef: RefObject<HTMLDivElement | null>;
  displayedSegments: TranscriptSegment[];
  seek: (seconds: number) => void;
  play: () => void;
}

function findSegmentIndexAt(segments: TranscriptSegment[], seconds: number): number {
  return segments.findIndex(
    (segment) => seconds >= timeToSeconds(segment.start_time) && seconds <= timeToSeconds(segment.end_time),
  );
}

export function useTranscriptPlayback({
  videoRef,
  transcriptScrollRef,
  displayedSegments,
  seek,
  play,
}: TranscriptPlaybackOptions) {
  const [activeSegmentId, setActiveSegmentId] = useState<string | null>(null);

  const displayedSegmentsRef = useRef(displayedSegments);
  useEffect(() => {
    displayedSegmentsRef.current = displayedSegments;
  }, [displayedSegments]);

  const scrollSegmentIntoView = useCallback((segmentId: string, fallbackToPage: boolean) => {
    const segmentElement = document.getElementById(`transcript-segment-${segmentId}`);
    if (!segmentElement) return;
    const container = transcriptScrollRef.current;
    if (container) {
      const relativeTop = segmentElement.getBoundingClientRect().top - container.getBoundingClientRect().top;
      container.scrollTo({ top: container.scrollTop + relativeTop - SCROLL_TOP_OFFSET_PX, behavior: "smooth" });
    } else if (fallbackToPage) {
      segmentElement.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [transcriptScrollRef]);

  useEffect(() => {
    if (!videoRef) return;
    const handleTimeUpdate = () => {
      if (displayedSegments.length === 0) return;
      const currentSegment = displayedSegments.find(
        (segment) =>
          videoRef.currentTime >= timeToSeconds(segment.start_time) &&
          videoRef.currentTime <= timeToSeconds(segment.end_time),
      );
      setActiveSegmentId(currentSegment?.id ?? null);
    };
    videoRef.addEventListener("timeupdate", handleTimeUpdate);
    return () => videoRef.removeEventListener("timeupdate", handleTimeUpdate);
  }, [videoRef, displayedSegments]);

  const seekToTimestamp = useCallback((timeString: string) => {
    if (!timeString) return;

    const seconds = timeToSeconds(timeString);
    seek(seconds);
    play();

    const index = findSegmentIndexAt(displayedSegments, seconds);
    if (index === -1) return;
    const matchingSegment = displayedSegments[index];
    setActiveSegmentId(matchingSegment.id);
    setTimeout(() => scrollSegmentIntoView(matchingSegment.id, true), ACTIVE_SEGMENT_RENDER_DELAY_MS);
  }, [displayedSegments, seek, play, scrollSegmentIntoView]);

  useEffect(() => {
    if (!videoRef) return;
    const handleSeeked = () => {
      const segments = displayedSegmentsRef.current;
      const index = findSegmentIndexAt(segments, videoRef.currentTime);
      if (index === -1) return;
      setActiveSegmentId(segments[index].id);
      scrollSegmentIntoView(segments[index].id, false);
    };
    videoRef.addEventListener("seeked", handleSeeked);
    return () => videoRef.removeEventListener("seeked", handleSeeked);
  }, [videoRef, scrollSegmentIntoView]);

  return { activeSegmentId, seekToTimestamp };
}
