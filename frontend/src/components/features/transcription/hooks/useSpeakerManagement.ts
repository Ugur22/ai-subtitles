import { useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import toast from "react-hot-toast";
import {
  type TranscriptionResponse,
  updateSpeakerName,
  enrollSpeaker,
  autoIdentifySpeakers,
  listSpeakers,
  deleteSpeaker,
  type SpeakerInfo,
} from "../../../../services/api";
import { timeToSeconds } from "../../../../utils/time";
import { formatSpeakerLabel } from "../../../../utils/speaker";
import type { TranscriptSegment } from "../segments";

export type EnrollableSegment = Pick<TranscriptSegment, "start_time" | "end_time" | "speaker">;

interface SpeakerManagementOptions {
  transcription: TranscriptionResponse | null;
  setTranscription: Dispatch<SetStateAction<TranscriptionResponse | null>>;
  filteredSpeaker: string | null;
  setFilteredSpeaker: Dispatch<SetStateAction<string | null>>;
}

export function useSpeakerManagement({
  transcription,
  setTranscription,
  filteredSpeaker,
  setFilteredSpeaker,
}: SpeakerManagementOptions) {
  const [editingSegmentId, setEditingSegmentId] = useState<string | null>(null);
  const [editSpeakerName, setEditSpeakerName] = useState("");
  const [isRenamingSpeaker, setIsRenamingSpeaker] = useState(false);
  const [speakerDropdownOpen, setSpeakerDropdownOpen] = useState(false);

  const [enrollModalSegment, setEnrollModalSegment] = useState<EnrollableSegment | null>(null);
  const [enrollSpeakerName, setEnrollSpeakerName] = useState('');
  const [enrollSubmitting, setEnrollSubmitting] = useState(false);

  const [autoIdentifyConfirmOpen, setAutoIdentifyConfirmOpen] = useState(false);
  const [autoIdentifyRunning, setAutoIdentifyRunning] = useState(false);

  const [enrolledSpeakers, setEnrolledSpeakers] = useState<SpeakerInfo[]>([]);
  const [enrolledLoading, setEnrolledLoading] = useState(false);
  const [showEnrolledInDropdown, setShowEnrolledInDropdown] = useState(false);
  const [confirmingDeleteEnrolled, setConfirmingDeleteEnrolled] = useState<string | null>(null);

  const handleSpeakerRename = async (originalSpeaker: string) => {
    if (!editSpeakerName.trim() || !transcription) return;

    setIsRenamingSpeaker(true);
    try {
      await updateSpeakerName(
        transcription.video_hash,
        originalSpeaker,
        editSpeakerName.trim()
      );

      const updatedSegments = transcription.transcription.segments.map(
        (seg) => {
          if (seg.speaker === originalSpeaker) {
            return { ...seg, speaker: editSpeakerName.trim() };
          }
          return seg;
        }
      );

      setTranscription({
        ...transcription,
        transcription: {
          ...transcription.transcription,
          segments: updatedSegments,
        },
      });

      if (filteredSpeaker === originalSpeaker) {
        setFilteredSpeaker(editSpeakerName.trim());
      }

      setEditingSegmentId(null);
      setEditSpeakerName("");
    } catch (err) {
      console.error("Failed to rename speaker:", err);
      alert("Failed to rename speaker");
    } finally {
      setIsRenamingSpeaker(false);
    }
  };

  const handleEnrollSpeaker = (segment: EnrollableSegment) => {
    setEnrollSpeakerName(formatSpeakerLabel(segment.speaker || "Unknown"));
    setEnrollModalSegment(segment);
  };

  const handleEnrollConfirm = async () => {
    if (!enrollModalSegment || !transcription || !enrollSpeakerName.trim()) return;
    setEnrollSubmitting(true);
    try {
      const startTime = timeToSeconds(enrollModalSegment.start_time);
      const endTime = timeToSeconds(enrollModalSegment.end_time);
      await enrollSpeaker(
        enrollSpeakerName.trim(),
        transcription.video_hash,
        startTime,
        endTime
      );
      toast.success(`${enrollSpeakerName.trim()} enrolled successfully`);
      setEnrollModalSegment(null);
      setEnrollSpeakerName('');
    } catch (error: unknown) {
      console.error("Failed to enroll speaker:", error);
      toast.error(error instanceof Error ? error.message : "Failed to enroll speaker");
    } finally {
      setEnrollSubmitting(false);
    }
  };

  const handleAutoIdentifySpeakers = () => {
    if (!transcription) return;
    setAutoIdentifyConfirmOpen(true);
    setSpeakerDropdownOpen(false);
  };

  const handleAutoIdentifyConfirm = async () => {
    if (!transcription) return;
    setAutoIdentifyRunning(true);
    try {
      const result = await autoIdentifySpeakers(transcription.video_hash, 0.7);
      toast.success(
        `Identified ${result.identified_segments}/${result.total_segments} segments — refreshing…`,
        { duration: 3000 }
      );
      setAutoIdentifyConfirmOpen(false);
      setTimeout(() => window.location.reload(), 1500);
    } catch (error: unknown) {
      console.error("Failed to auto-identify speakers:", error);
      toast.error(error instanceof Error ? error.message : "Failed to auto-identify speakers");
      setAutoIdentifyRunning(false);
    }
  };

  const fetchEnrolledSpeakers = async () => {
    setEnrolledLoading(true);
    try {
      const { speakers } = await listSpeakers();
      setEnrolledSpeakers(speakers || []);
    } catch (error) {
      console.error("Failed to fetch enrolled speakers:", error);
    } finally {
      setEnrolledLoading(false);
    }
  };

  const handleDeleteEnrolledSpeaker = async (name: string) => {
    try {
      await deleteSpeaker(name);
      setConfirmingDeleteEnrolled(null);
      await fetchEnrolledSpeakers();
    } catch {
      toast.error("Failed to remove speaker");
    }
  };

  return {
    editingSegmentId,
    setEditingSegmentId,
    editSpeakerName,
    setEditSpeakerName,
    isRenamingSpeaker,
    handleSpeakerRename,
    speakerDropdownOpen,
    setSpeakerDropdownOpen,
    enrollModalSegment,
    setEnrollModalSegment,
    enrollSpeakerName,
    setEnrollSpeakerName,
    enrollSubmitting,
    handleEnrollSpeaker,
    handleEnrollConfirm,
    autoIdentifyConfirmOpen,
    setAutoIdentifyConfirmOpen,
    autoIdentifyRunning,
    handleAutoIdentifySpeakers,
    handleAutoIdentifyConfirm,
    enrolledSpeakers,
    enrolledLoading,
    showEnrolledInDropdown,
    setShowEnrolledInDropdown,
    confirmingDeleteEnrolled,
    setConfirmingDeleteEnrolled,
    fetchEnrolledSpeakers,
    handleDeleteEnrolledSpeaker,
  };
}

export type SpeakerManagementState = ReturnType<typeof useSpeakerManagement>;
