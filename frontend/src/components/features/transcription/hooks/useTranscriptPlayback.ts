import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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

interface SegmentBounds {
  id: string;
  start: number;
  end: number;
}

function findSegmentAt(bounds: SegmentBounds[], seconds: number): SegmentBounds | undefined {
  return bounds.find((segment) => seconds >= segment.start && seconds <= segment.end);
}

export function useTranscriptPlayback({
  videoRef,
  transcriptScrollRef,
  displayedSegments,
  seek,
  play,
}: TranscriptPlaybackOptions) {
  const [activeSegmentId, setActiveSegmentId] = useState<string | null>(null);

  const segmentBounds = useMemo(
    () => displayedSegments.map((segment) => ({
      id: segment.id,
      start: timeToSeconds(segment.start_time),
      end: timeToSeconds(segment.end_time),
    })),
    [displayedSegments],
  );
  const segmentBoundsRef = useRef(segmentBounds);
  useEffect(() => {
    segmentBoundsRef.current = segmentBounds;
  }, [segmentBounds]);

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
      if (segmentBounds.length === 0) return;
      setActiveSegmentId(findSegmentAt(segmentBounds, videoRef.currentTime)?.id ?? null);
    };
    videoRef.addEventListener("timeupdate", handleTimeUpdate);
    return () => videoRef.removeEventListener("timeupdate", handleTimeUpdate);
  }, [videoRef, segmentBounds]);

  const seekToTimestamp = useCallback((timeString: string) => {
    if (!timeString) return;

    const seconds = timeToSeconds(timeString);
    seek(seconds);
    play();

    const matchingSegment = findSegmentAt(segmentBounds, seconds);
    if (!matchingSegment) return;
    setActiveSegmentId(matchingSegment.id);
    setTimeout(() => scrollSegmentIntoView(matchingSegment.id, true), ACTIVE_SEGMENT_RENDER_DELAY_MS);
  }, [segmentBounds, seek, play, scrollSegmentIntoView]);

  useEffect(() => {
    if (!videoRef) return;
    const handleSeeked = () => {
      const matchingSegment = findSegmentAt(segmentBoundsRef.current, videoRef.currentTime);
      if (!matchingSegment) return;
      setActiveSegmentId(matchingSegment.id);
      scrollSegmentIntoView(matchingSegment.id, false);
    };
    videoRef.addEventListener("seeked", handleSeeked);
    return () => videoRef.removeEventListener("seeked", handleSeeked);
  }, [videoRef, scrollSegmentIntoView]);

  return { activeSegmentId, seekToTimestamp };
}
