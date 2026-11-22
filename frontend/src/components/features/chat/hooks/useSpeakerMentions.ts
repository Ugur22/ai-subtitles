import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getFaceTagSpeakers, listSpeakers } from "../../../../services/api";
import { queryKeys } from "../../../../lib/queryKeys";

export function useSpeakerMentions(videoHash: string | null, transcriptSpeakers: string[]) {
  const [showMentions, setShowMentions] = useState(false);
  const [mentionFilter, setMentionFilter] = useState("");
  const [mentionIndex, setMentionIndex] = useState(0);

  const enrolled = useQuery({
    queryKey: queryKeys.speakers,
    queryFn: listSpeakers,
    enabled: Boolean(videoHash),
  });
  const faceTags = useQuery({
    queryKey: queryKeys.faceTagSpeakers(videoHash),
    queryFn: () => getFaceTagSpeakers(videoHash!),
    enabled: Boolean(videoHash),
  });

  const filteredSpeakers = useMemo(() => {
    const enrolledNames = enrolled.data?.speakers.map((s) => s.name) ?? [];
    const faceNames = faceTags.data?.speakers.map((s) => s.speaker_name) ?? [];
    const names = [...new Set([...transcriptSpeakers, ...enrolledNames, ...faceNames])]
      .filter(Boolean)
      .sort();
    if (!mentionFilter) return names;
    const lower = mentionFilter.toLowerCase();
    return names.filter((s) => s.toLowerCase().includes(lower));
  }, [transcriptSpeakers, enrolled.data, faceTags.data, mentionFilter]);

  return {
    showMentions,
    setShowMentions,
    setMentionFilter,
    mentionIndex,
    setMentionIndex,
    filteredSpeakers,
  };
}
