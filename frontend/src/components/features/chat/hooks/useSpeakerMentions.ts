import { useEffect, useMemo, useState } from "react";
import { getFaceTagSpeakers, listSpeakers } from "../../../../services/api";

export function useSpeakerMentions(videoHash: string | null, transcriptSpeakers: string[]) {
  const [speakers, setSpeakers] = useState<string[]>([]);
  const [showMentions, setShowMentions] = useState(false);
  const [mentionFilter, setMentionFilter] = useState("");
  const [mentionIndex, setMentionIndex] = useState(0);

  useEffect(() => {
    if (!videoHash) return;
    const fetchSpeakers = async () => {
      try {
        const [enrolled, faceTags] = await Promise.all([
          listSpeakers().catch(() => ({ speakers: [] })),
          getFaceTagSpeakers(videoHash).catch(() => ({ speakers: [] })),
        ]);
        const enrolledNames = enrolled.speakers.map((s) => s.name);
        const faceNames = faceTags.speakers.map((s) => s.speaker_name);
        setSpeakers(
          [...new Set([...enrolledNames, ...faceNames])]
            .filter(Boolean)
            .sort()
        );
      } catch (e) {
        console.error("Failed to fetch speakers:", e);
      }
    };
    fetchSpeakers();
  }, [videoHash]);

  const filteredSpeakers = useMemo(() => {
    const names = [...new Set([...transcriptSpeakers, ...speakers])]
      .filter(Boolean)
      .sort();
    if (!mentionFilter) return names;
    const lower = mentionFilter.toLowerCase();
    return names.filter((s) => s.toLowerCase().includes(lower));
  }, [transcriptSpeakers, speakers, mentionFilter]);

  return {
    showMentions,
    setShowMentions,
    setMentionFilter,
    mentionIndex,
    setMentionIndex,
    filteredSpeakers,
  };
}
