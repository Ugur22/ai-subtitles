import { useMutation } from "@tanstack/react-query";
import { generateChapters, type ChaptersResponse } from "../services/api";

interface UseChaptersOptions {
  videoHash?: string;
}

export const useChapters = (options: UseChaptersOptions) => {
  const { videoHash } = options;

  const mutation = useMutation<ChaptersResponse, Error, string | undefined>({
    mutationFn: (provider) => {
      if (!videoHash) throw new Error("No video loaded");
      return generateChapters(videoHash, provider);
    },
    onError: (err) => console.error("[useChapters] Generation failed:", err),
  });

  return {
    chapters: mutation.data?.chapters ?? [],
    loading: mutation.isPending,
    error: mutation.error ? mutation.error.message || "Failed to generate chapters" : null,
    generate: (provider?: string) => mutation.mutate(provider),
    reset: mutation.reset,
  };
};
