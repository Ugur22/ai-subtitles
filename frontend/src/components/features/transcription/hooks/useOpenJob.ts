import { useCallback, useEffect, useRef, useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import toast from "react-hot-toast";
import { useSearchParams } from "react-router-dom";
import {
  type TranscriptionResponse,
  getJobVideoUrl,
  getJob,
} from "../../../../services/api";
import type { Job } from "../../../../types/job";

interface OpenJobOptions {
  jobs: Job[];
  jobsFresh: boolean;
  transcription: TranscriptionResponse | null;
  setTranscription: Dispatch<SetStateAction<TranscriptionResponse | null>>;
  setShowTranslation: Dispatch<SetStateAction<boolean>>;
  setVideoUrl: (url: string | null) => void;
  setShowJobPanel: (open: boolean) => void;
  onClose: () => void;
}

/**
 * Opens a job's transcript and video, keeps it in sync with the `?job=` URL
 * param (deep links, back/forward) and refreshes an expired video URL once.
 */
export function useOpenJob({
  jobs,
  jobsFresh,
  transcription,
  setTranscription,
  setShowTranslation,
  setVideoUrl,
  setShowJobPanel,
  onClose,
}: OpenJobOptions) {
  const [searchParams, setSearchParams] = useSearchParams();
  const openJobId = searchParams.get("job");

  // Refs for video URL retry on expiry
  const currentJobRef = useRef<{ jobId: string; accessToken?: string } | null>(null);
  const videoRetriedRef = useRef(false);

  // State mirror of currentJobRef so child components receive reactive props
  const [currentJobId, setCurrentJobId] = useState<string | null>(null);
  const [currentAccessToken, setCurrentAccessToken] = useState<string | undefined>(undefined);

  const handleViewTranscript = useCallback(async (listedJob: Job) => {
    let job = listedJob;
    if (!job.result_json) {
      try {
        job = { ...(await getJob(job.job_id, job.access_token)), access_token: job.access_token };
      } catch (err) {
        console.error("Failed to load job", job.job_id, err);
        toast.error("Could not open this transcript.");
        return;
      }
      if (!job.result_json) return;
    }
    setTranscription(job.result_json);
    setShowTranslation(true);
    setSearchParams({ job: job.job_id }, { replace: searchParams.get("job") === job.job_id });
    setShowJobPanel(false);
    currentJobRef.current = { jobId: job.job_id, accessToken: job.access_token };
    setCurrentJobId(job.job_id);
    setCurrentAccessToken(job.access_token);
    if (job.video_url) {
      videoRetriedRef.current = false;
      setVideoUrl(job.video_url);
      return;
    }
    try {
      const { download_url } = await getJobVideoUrl(job.job_id, job.access_token);
      videoRetriedRef.current = false;
      setVideoUrl(download_url);
    } catch (err) {
      console.error("Failed to load video URL for job", job.job_id, err);
      toast.error("Could not load video. It may have been removed.");
      setVideoUrl(null);
    }
  }, [setTranscription, setShowTranslation, setVideoUrl, setShowJobPanel, searchParams, setSearchParams]);

  const handleVideoError = useCallback(async () => {
    if (videoRetriedRef.current || !currentJobRef.current) return;
    videoRetriedRef.current = true;
    try {
      const { download_url } = await getJobVideoUrl(
        currentJobRef.current.jobId,
        currentJobRef.current.accessToken
      );
      setVideoUrl(download_url);
    } catch (e) {
      console.error("Failed to refresh video URL", e);
    }
  }, [setVideoUrl]);

  const closeJob = useCallback(() => setSearchParams({}), [setSearchParams]);

  const previousJobIdRef = useRef(openJobId);
  useEffect(() => {
    if (previousJobIdRef.current && !openJobId) onClose();
    previousJobIdRef.current = openJobId;
  }, [openJobId, onClose]);

  const deepLinkOpenedRef = useRef<string | null>(null);
  useEffect(() => {
    if (!openJobId) {
      deepLinkOpenedRef.current = null;
      return;
    }
    if (transcription || deepLinkOpenedRef.current === openJobId) return;
    const job = jobs.find((j) => j.job_id === openJobId);
    if (job) {
      deepLinkOpenedRef.current = openJobId;
      handleViewTranscript(job);
    } else if (jobsFresh) {
      setSearchParams({}, { replace: true });
    }
  }, [openJobId, transcription, jobsFresh, jobs, handleViewTranscript, setSearchParams]);

  return {
    handleViewTranscript,
    handleVideoError,
    closeJob,
    currentJobId,
    currentAccessToken,
  };
}
