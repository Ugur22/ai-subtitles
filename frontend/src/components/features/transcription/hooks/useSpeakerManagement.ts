import { useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import toast from "react-hot-toast";
import {
  type TranscriptionResponse,
  updateSpeakerName,
  enrollSpeaker,
  autoIdentifySpeakers,
  deleteSpeaker,
} from "../../../../services/api";
import { queryKeys, speakersQuery } from "../../../../lib/queryKeys";
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
  const queryClient = useQueryClient();
  const [editingSegmentId, setEditingSegmentId] = useState<string | null>(null);
  const [editSpeakerName, setEditSpeakerName] = useState("");
  const [speakerDropdownOpen, setSpeakerDropdownOpen] = useState(false);

  const [enrollModalSegment, setEnrollModalSegment] = useState<EnrollableSegment | null>(null);
  const [enrollSpeakerName, setEnrollSpeakerName] = useState('');

  const [autoIdentifyConfirmOpen, setAutoIdentifyConfirmOpen] = useState(false);

  const [showEnrolledInDropdown, setShowEnrolledInDropdown] = useState(false);
  const [confirmingDeleteEnrolled, setConfirmingDeleteEnrolled] = useState<string | null>(null);

  const enrolledQuery = useQuery({
    ...speakersQuery,
    enabled: showEnrolledInDropdown,
  });
  const enrolledSpeakers = enrolledQuery.data?.speakers ?? [];
  const invalidateSpeakers = () => queryClient.invalidateQueries({ queryKey: queryKeys.speakers });

  const renameMutation = useMutation({
    mutationFn: ({ videoHash, from, to }: { videoHash: string; from: string; to: string }) =>
      updateSpeakerName(videoHash, from, to),
    onSuccess: (_data, { from, to }) => {
      setTranscription((current) => current && {
        ...current,
        transcription: {
          ...current.transcription,
          segments: current.transcription.segments.map((seg) =>
            seg.speaker === from ? { ...seg, speaker: to } : seg
          ),
        },
      });
      if (filteredSpeaker === from) setFilteredSpeaker(to);
      setEditingSegmentId(null);
      setEditSpeakerName("");
    },
    onError: (err) => {
      console.error("Failed to rename speaker:", err);
      alert("Failed to rename speaker");
    },
  });

  const handleSpeakerRename = (originalSpeaker: string) => {
    if (!editSpeakerName.trim() || !transcription) return;
    renameMutation.mutate({
      videoHash: transcription.video_hash,
      from: originalSpeaker,
      to: editSpeakerName.trim(),
    });
  };

  const enrollMutation = useMutation({
    mutationFn: ({ name, videoHash, segment }: { name: string; videoHash: string; segment: EnrollableSegment }) =>
      enrollSpeaker(name, videoHash, timeToSeconds(segment.start_time), timeToSeconds(segment.end_time)),
    onSuccess: (_data, { name }) => {
      toast.success(`${name} enrolled successfully`);
      setEnrollModalSegment(null);
      setEnrollSpeakerName('');
      void invalidateSpeakers();
    },
    onError: (error) => {
      console.error("Failed to enroll speaker:", error);
      toast.error(error instanceof Error ? error.message : "Failed to enroll speaker");
    },
  });

  const handleEnrollSpeaker = (segment: EnrollableSegment) => {
    setEnrollSpeakerName(formatSpeakerLabel(segment.speaker || "Unknown"));
    setEnrollModalSegment(segment);
  };

  const handleEnrollConfirm = () => {
    if (!enrollModalSegment || !transcription || !enrollSpeakerName.trim()) return;
    enrollMutation.mutate({
      name: enrollSpeakerName.trim(),
      videoHash: transcription.video_hash,
      segment: enrollModalSegment,
    });
  };

  const autoIdentifyMutation = useMutation({
    mutationFn: (videoHash: string) => autoIdentifySpeakers(videoHash, 0.7),
    onSuccess: (result) => {
      toast.success(
        `Identified ${result.identified_segments}/${result.total_segments} segments — refreshing…`,
        { duration: 3000 }
      );
      setAutoIdentifyConfirmOpen(false);
      setTimeout(() => window.location.reload(), 1500);
    },
    onError: (error) => {
      console.error("Failed to auto-identify speakers:", error);
      toast.error(error instanceof Error ? error.message : "Failed to auto-identify speakers");
    },
  });

  const handleAutoIdentifySpeakers = () => {
    if (!transcription) return;
    setAutoIdentifyConfirmOpen(true);
    setSpeakerDropdownOpen(false);
  };

  const handleAutoIdentifyConfirm = () => {
    if (!transcription) return;
    autoIdentifyMutation.mutate(transcription.video_hash);
  };

  const deleteMutation = useMutation({
    mutationFn: deleteSpeaker,
    onSuccess: () => {
      setConfirmingDeleteEnrolled(null);
      return invalidateSpeakers();
    },
    onError: () => toast.error("Failed to remove speaker"),
  });

  return {
    editingSegmentId,
    setEditingSegmentId,
    editSpeakerName,
    setEditSpeakerName,
    isRenamingSpeaker: renameMutation.isPending,
    handleSpeakerRename,
    speakerDropdownOpen,
    setSpeakerDropdownOpen,
    enrollModalSegment,
    setEnrollModalSegment,
    enrollSpeakerName,
    setEnrollSpeakerName,
    enrollSubmitting: enrollMutation.isPending,
    handleEnrollSpeaker,
    handleEnrollConfirm,
    autoIdentifyConfirmOpen,
    setAutoIdentifyConfirmOpen,
    autoIdentifyRunning: autoIdentifyMutation.isPending || autoIdentifyMutation.isSuccess,
    handleAutoIdentifySpeakers,
    handleAutoIdentifyConfirm,
    enrolledSpeakers,
    enrolledLoading: enrolledQuery.isFetching,
    showEnrolledInDropdown,
    setShowEnrolledInDropdown,
    confirmingDeleteEnrolled,
    setConfirmingDeleteEnrolled,
    handleDeleteEnrolledSpeaker: (name: string) => deleteMutation.mutate(name),
  };
}

export type SpeakerManagementState = ReturnType<typeof useSpeakerManagement>;
