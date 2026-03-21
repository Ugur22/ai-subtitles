import { useState } from "react";
import { generateChapters, type Chapter, type ChaptersResponse } from "../services/api";

interface UseChaptersOptions {
  videoHash?: string;
}

export const useChapters = (options: UseChaptersOptions) => {
  const { videoHash } = options;

  const [chapters, setChapters] = useState<Chapter[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const generate = async (provider?: string) => {
    if (!videoHash) {
      setError("No video loaded");
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const response: ChaptersResponse = await generateChapters(videoHash, provider);
      setChapters(response.chapters);
    } catch (err) {
      console.error("[useChapters] Generation failed:", err);
      setError(err instanceof Error ? err.message : "Failed to generate chapters");
    } finally {
      setLoading(false);
    }
  };

  const reset = () => {
    setChapters([]);
    setError(null);
  };

  return {
    chapters,
    setChapters,
    loading,
    error,
    generate,
    reset,
  };
};
