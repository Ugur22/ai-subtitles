import { useEffect } from "react";
import { useMutation } from "@tanstack/react-query";
import { match } from "ts-pattern";
import { indexImages, indexVideo } from "../../../../services/api";

export type IndexingStatus =
  | { kind: "idle" }
  | { kind: "indexing" }
  | { kind: "done"; imagesIndexed: boolean }
  | { kind: "failed" };

export type ReindexStatus = { kind: "idle" | "running" | "started" | "failed" };

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

  const indexingStatus = match(indexing)
    .returnType<IndexingStatus>()
    .with({ status: "idle" }, () => ({ kind: "idle" }))
    .with({ status: "pending" }, () => ({ kind: "indexing" }))
    .with({ status: "success" }, ({ data }) => ({ kind: "done", imagesIndexed: data.imagesIndexed }))
    .with({ status: "error" }, () => ({ kind: "failed" }))
    .exhaustive();

  const reindexStatus = match(reindex.status)
    .returnType<ReindexStatus>()
    .with("idle", () => ({ kind: "idle" }))
    .with("pending", () => ({ kind: "running" }))
    .with("success", () => ({ kind: "started" }))
    .with("error", () => ({ kind: "failed" }))
    .exhaustive();

  const handleReindex = () => {
    if (!videoHash || reindexStatus.kind === "running") return;
    reindex.mutate(videoHash, {
      onSuccess: () => setTimeout(reindex.reset, 8000),
      onError: () => setTimeout(reindex.reset, 5000),
    });
  };

  return { indexingStatus, reindexStatus, handleReindex };
}
