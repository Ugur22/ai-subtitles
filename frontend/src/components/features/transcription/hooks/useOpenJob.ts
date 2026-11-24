import { useCallback, useEffect, useRef, useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import toast from "react-hot-toast";
import { useSearchParams } from "react-router-dom";
import { type TranscriptionResponse, getJob, getJobVideoUrl } from "../../../../services/api";
import type { Job } from "../../../../types/job";

interface OpenJobOptions {
  transcription: TranscriptionResponse | null;
  setTranscription: Dispatch<SetStateAction<TranscriptionResponse | null>>;
  setShowTranslation: Dispatch<SetStateAction<boolean>>;
  setShowJobPanel: (show: boolean) => void;
  setVideoUrl: (url: string | null) => void;
  /** Resets the viewer; called when the `?job=` param is removed. */
  closeTranscription: () => void;
  jobs: Job[];
  /** True once the job list reflects the server, so a missing deep-linked job really is gone. */
  jobsAreFresh: boolean;
}

/**
 * Owns the open transcript's job: opening it (from a list click or a `?job=` deep link),
 * closing it when the param is removed, and refreshing an expired video URL once.
 */
export function useOpenJob({
  transcription,
  setTranscription,
  setShowTranslation,
  setShowJobPanel,
  setVideoUrl,
  closeTranscription,
  jobs,
  jobsAreFresh,
}: OpenJobOptions) {
  const [searchParams, setSearchParams] = useSearchParams();
  const openJobId = searchParams.get("job");

  // Ref for the video URL retry on expiry, plus a state mirror so children get reactive props
  const currentJobRef = useRef<{ jobId: string; accessToken?: string } | null>(null);
  const videoRetriedRef = useRef(false);
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

  const closeOpenJob = useCallback(() => setSearchParams({}), [setSearchParams]);

  const previousJobIdRef = useRef(openJobId);
  useEffect(() => {
    if (previousJobIdRef.current && !openJobId) closeTranscription();
    previousJobIdRef.current = openJobId;
  }, [openJobId, closeTranscription]);

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
    } else if (jobsAreFresh) {
      setSearchParams({}, { replace: true });
    }
  }, [openJobId, transcription, jobsAreFresh, jobs, handleViewTranscript, setSearchParams]);

  return { handleViewTranscript, handleVideoError, closeOpenJob, currentJobId, currentAccessToken };
}
