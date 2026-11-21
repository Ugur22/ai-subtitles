import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { API_BASE_URL } from "../../../../config";

export type IndexingStatus = {
  kind: "indexing" | "done" | "failed";
  message: string;
};

export function useChatIndexing(videoHash: string | null) {
  const [indexingStatus, setIndexingStatus] = useState<IndexingStatus | null>(null);
  const [reindexing, setReindexing] = useState(false);
  const [reindexStatus, setReindexStatus] = useState<string | null>(null);

  const indexVideo = useCallback(async () => {
    if (!videoHash) return;

    setIndexingStatus({ kind: "indexing", message: "Indexing video for chat…" });
    try {
      await axios.post(`${API_BASE_URL}/api/index_video/`, null, {
        params: { video_hash: videoHash },
        withCredentials: true,
      });

      try {
        await axios.post(`${API_BASE_URL}/api/index_images/`, null, {
          params: { video_hash: videoHash },
          withCredentials: true,
        });
        setIndexingStatus({ kind: "done", message: "Video and images indexed" });
      } catch (imageError) {
        console.warn("Failed to index images:", imageError);
        setIndexingStatus({ kind: "done", message: "Video indexed, images skipped" });
      }

      setTimeout(() => setIndexingStatus(null), 3000);
    } catch (error) {
      console.error("Failed to index video:", error);
      setIndexingStatus({ kind: "failed", message: "Indexing failed" });
      setTimeout(() => setIndexingStatus(null), 3000);
    }
  }, [videoHash]);

  useEffect(() => {
    if (videoHash) {
      indexVideo();
    }
  }, [videoHash, indexVideo]);

  const handleReindex = async () => {
    if (!videoHash || reindexing) return;
    setReindexing(true);
    setReindexStatus(null);
    try {
      await axios.post(`${API_BASE_URL}/api/index_images/`, null, {
        params: { video_hash: videoHash, force_reindex: true },
        timeout: 15000,
        withCredentials: true,
      });
      setReindexStatus("Re-indexing started — visual search will update in a few minutes.");
      setTimeout(() => setReindexStatus(null), 8000);
    } catch (error) {
      console.error("Failed to re-index images:", error);
      setReindexStatus("Re-indexing failed. Please try again.");
      setTimeout(() => setReindexStatus(null), 5000);
    } finally {
      setReindexing(false);
    }
  };

  return { indexingStatus, reindexing, reindexStatus, handleReindex };
}
