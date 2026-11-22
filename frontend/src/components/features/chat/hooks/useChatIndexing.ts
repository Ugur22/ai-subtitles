import { useEffect } from "react";
import { useMutation } from "@tanstack/react-query";
import { indexImages, indexVideo } from "../../../../services/api";

export type IndexingStatus = {
  kind: "indexing" | "done" | "failed";
  message: string;
};

const indexForChat = async (videoHash: string): Promise<{ imagesIndexed: boolean }> => {
  await indexVideo(videoHash);
  try {
    await indexImages(videoHash);
    return { imagesIndexed: true };
  } catch (imageError) {
    console.warn("Failed to index images:", imageError);
    return { imagesIndexed: false };
  }
};

export function useChatIndexing(videoHash: string | null) {
  const indexing = useMutation({
    mutationFn: indexForChat,
    onError: (error) => console.error("Failed to index video:", error),
  });
  const { mutate: startIndexing, reset: clearIndexing } = indexing;

  useEffect(() => {
    if (!videoHash) return;
    startIndexing(videoHash, { onSettled: () => setTimeout(clearIndexing, 3000) });
  }, [videoHash, startIndexing, clearIndexing]);

  const reindex = useMutation({
    mutationFn: (videoHash: string) => indexImages(videoHash, true),
    onError: (error) => console.error("Failed to re-index images:", error),
  });

  const indexingStatus: IndexingStatus | null =
    indexing.isPending ? { kind: "indexing", message: "Indexing video for chat…" }
    : indexing.isSuccess ? { kind: "done", message: indexing.data.imagesIndexed ? "Video and images indexed" : "Video indexed, images skipped" }
    : indexing.isError ? { kind: "failed", message: "Indexing failed" }
    : null;

  const reindexStatus =
    reindex.isSuccess ? "Re-indexing started — visual search will update in a few minutes."
    : reindex.isError ? "Re-indexing failed. Please try again."
    : null;

  const handleReindex = () => {
    if (!videoHash || reindex.isPending) return;
    reindex.mutate(videoHash, {
      onSuccess: () => setTimeout(reindex.reset, 8000),
      onError: () => setTimeout(reindex.reset, 5000),
    });
  };

  return { indexingStatus, reindexing: reindex.isPending, reindexStatus, handleReindex };
}
