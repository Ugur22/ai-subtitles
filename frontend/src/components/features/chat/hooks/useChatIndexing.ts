import { useEffect } from "react";
import { useMutation, type MutationStatus } from "@tanstack/react-query";
import { match } from "ts-pattern";
import { indexImages, indexVideo } from "../../../../services/api";
import { useResetAfterSettle } from "../../../../hooks/useResetAfterSettle";

export type IndexingStatus =
  | { kind: "idle" }
  | { kind: "indexing" }
  | { kind: "done"; imagesIndexed: boolean }
  | { kind: "failed" };

export type ReindexStatus = "idle" | "running" | "started" | "failed";

const REINDEX_STATUS: Record<MutationStatus, ReindexStatus> = {
  idle: "idle",
  pending: "running",
  success: "started",
  error: "failed",
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
  const { mutate: startIndexing } = indexing;
  useResetAfterSettle(indexing, { success: 3000, error: 3000 });

  useEffect(() => {
    if (videoHash) startIndexing(videoHash);
  }, [videoHash, startIndexing]);

  const reindex = useMutation({
    mutationFn: (videoHash: string) => indexImages(videoHash, true),
    onError: (error) => console.error("Failed to re-index images:", error),
  });
  useResetAfterSettle(reindex, { success: 8000, error: 5000 });

  const indexingStatus = match(indexing)
    .returnType<IndexingStatus>()
    .with({ status: "idle" }, () => ({ kind: "idle" }))
    .with({ status: "pending" }, () => ({ kind: "indexing" }))
    .with({ status: "success" }, ({ data }) => ({ kind: "done", imagesIndexed: data.imagesIndexed }))
    .with({ status: "error" }, () => ({ kind: "failed" }))
    .exhaustive();

  const reindexStatus = REINDEX_STATUS[reindex.status];

  const handleReindex = () => {
    if (!videoHash || reindexStatus === "running") return;
    reindex.mutate(videoHash);
  };

  return { indexingStatus, reindexStatus, handleReindex };
}
