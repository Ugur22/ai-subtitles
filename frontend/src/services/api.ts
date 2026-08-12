import axios from 'axios';
import { API_BASE_URL } from '../config';
import { generateFileHash } from '../utils/file';

console.log('[API] Creating axios instance with baseURL:', API_BASE_URL);

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
  withCredentials: true, // Enable cookies for auth
});

// Log all outgoing requests for debugging
api.interceptors.request.use((config) => {
  const fullUrl = `${config.baseURL}${config.url}`;
  console.log(`[API] Request: ${config.method?.toUpperCase()} ${fullUrl}`);
  return config;
});

// Add response interceptor for error handling
api.interceptors.response.use(
  response => response,
  error => {
    if (error.response) {
      // The request was made and the server responded with a status code
      // that falls out of the range of 2xx
      let message = 'An error occurred';

      // Handle different error response formats
      if (error.response.data) {
        if (typeof error.response.data === 'string') {
          message = error.response.data;
        } else if (error.response.data.detail) {
          // FastAPI typically uses 'detail' field. For structured errors (e.g.
          // quota 402s: { error, message, upgrade_url }), prefer the human message.
          const detail = error.response.data.detail;
          if (typeof detail === 'string') {
            message = detail;
          } else if (detail && typeof detail === 'object' && detail.message) {
            message = detail.message;
          } else {
            message = JSON.stringify(detail);
          }
        } else if (error.response.data.message) {
          // Some APIs use 'message' field
          message = error.response.data.message;
        } else if (error.response.data.error) {
          // Others use 'error' field
          message = error.response.data.error;
        }
      }

      throw new Error(message);
    } else if (error.request) {
      // The request was made but no response was received
      throw new Error('No response from server. Please check your connection.');
    } else {
      // Something happened in setting up the request that triggered an Error
      throw new Error('Error setting up the request.');
    }
  }
);

export interface TranscriptionResponse {
  filename: string;
  video_hash: string;
  video_url?: string; // Added for direct video access
  file_path?: string; // Optional file path to the original video
  transcription: {
    text: string;
    language: string;
    duration?: string;
    segments: Array<{
      id: string; // Changed to string since we're using UUIDs now
      start: number; // Added raw number values
      end: number;
      start_time: string;
      end_time: string;
      text: string;
      translation?: string | null;
      screenshot_url?: string;  // Optional since it's only present for video files
      speaker?: string;  // Speaker label from diarization
      is_silent?: boolean;  // True for visual-only segments (no speech)
      speech_emotion?: {
        emotion: string;
        confidence: number;
      } | null;
      audio_events?: Array<{ event_type: string; confidence: number }>;
      energy_level?: number;
    }>;
    processing_time?: string;
  };
}

export interface SearchResponse {
  topic: string;
  total_matches: number;
  semantic_search_used: boolean;
  matches: Array<{
    timestamp: {
      start: string;
      end: string;
    };
    original_text: string;
    translated_text: string;
    context: {
      before: string[];
      after: string[];
    };
  }>;
}

export const searchTranscription = async (
  topic: string,
  semanticSearch: boolean = true,
  videoHash?: string
): Promise<SearchResponse> => {
  const params = new URLSearchParams({
    topic,
    semantic_search: semanticSearch.toString()
  });
  if (videoHash) {
    params.append('video_hash', videoHash);
  }
  const response = await api.post<SearchResponse>(`/api/search/?${params.toString()}`);

  return response.data;
};

export const getSubtitles = async (language: 'original' | 'english', videoHash?: string): Promise<Blob> => {
  const params = videoHash ? { video_hash: videoHash } : {};
  const response = await api.get(`/api/subtitles/${language}`, {
    responseType: 'blob',
    params,
  });

  return response.data;
};


// ============================================================================
// Speaker Recognition API
// ============================================================================

export interface SpeakerInfo {
  name: string;
  samples_count: number;
  embedding_shape: number[];
}

export const enrollSpeaker = async (
  speakerName: string,
  videoHash: string,
  startTime: number,
  endTime: number
): Promise<{ success: boolean; message: string; speaker_info: SpeakerInfo }> => {
  const formData = new FormData();
  formData.append('speaker_name', speakerName);
  formData.append('video_hash', videoHash);
  formData.append('start_time', startTime.toString());
  formData.append('end_time', endTime.toString());

  const response = await api.post('/api/speaker/enroll', formData);
  return response.data;
};

export const listSpeakers = async (): Promise<{ speakers: SpeakerInfo[]; count: number }> => {
  const response = await api.get('/api/speaker/list');
  return response.data;
};

export const deleteSpeaker = async (speakerName: string): Promise<{ success: boolean; message: string }> => {
  const response = await api.delete(`/api/speaker/${speakerName}`);
  return response.data;
};

export const autoIdentifySpeakers = async (
  videoHash: string,
  threshold: number = 0.7
): Promise<{ success: boolean; total_segments: number; identified_segments: number; message: string }> => {
  const response = await api.post(`/api/speaker/transcription/${videoHash}/auto_identify_speakers?threshold=${threshold}`);
  return response.data;
};

export const translateLocalText = async (text: string, sourceLang: string): Promise<string> => {
  const response = await api.post('/translate_local/', {
    text,
    source_lang: sourceLang,
  });
  return response.data.translation;
};

export const updateSpeakerName = async (
  videoHash: string,
  originalSpeaker: string,
  newSpeakerName: string
): Promise<{
  success: boolean;
  message: string;
  updated_count: number;
  video_hash: string;
}> => {
  const response = await api.post<{
    success: boolean;
    message: string;
    updated_count: number;
    video_hash: string;
  }>(`/api/speaker/transcription/${videoHash}/speaker`, {
    original_speaker: originalSpeaker,
    new_speaker_name: newSpeakerName,
  });
  return response.data;
};

// ============================================================================
// Background Job Processing API
// ============================================================================

import type {
  Job,
  JobSubmitResponse,
  JobSubmitParams,
  JobListResponse,
  JobShareResponse,
} from '../types/job';
import { uploadMedia } from './gcsUpload';

/**
 * Submit a new transcription job to be processed in the background
 */
export const submitJob = async (params: JobSubmitParams): Promise<JobSubmitResponse> => {
  const response = await api.post<JobSubmitResponse>('/api/jobs/submit', params);
  return response.data;
};

/**
 * Get the status and details of a specific job
 * Requires the access token for authentication
 */
export const getJob = async (jobId: string, token: string): Promise<Job> => {
  const response = await api.get<Job>(`/api/jobs/${jobId}`, {
    params: { token },
  });
  return response.data;
};

/**
 * Get a paginated list of jobs for the authenticated user.
 * @param tokens - Deprecated; ignored by the backend for authenticated lists
 * @param page - Page number (1-indexed)
 * @param perPage - Number of jobs per page (default 10)
 */
export const getJobs = async (
  tokens: string[],
  page: number = 1,
  perPage: number = 10
): Promise<JobListResponse> => {
  const params: Record<string, string | number> = {
    page,
    per_page: perPage,
  };
  if (tokens.length > 0) {
    params.tokens = tokens.join(',');
  }
  const response = await api.get<JobListResponse>('/api/jobs', { params });
  return response.data;
};

/**
 * Cancel a pending job
 * Only works for jobs with status 'pending' (not yet processing)
 */
export const cancelJob = async (jobId: string, token: string): Promise<Job> => {
  const response = await api.delete<Job>(`/api/jobs/${jobId}`, {
    params: { token },
  });
  return response.data;
};

/**
 * Retry a failed job with the same settings
 * Resets the job to 'pending' status and triggers background processing
 */
export const retryJob = async (jobId: string, token: string): Promise<Job> => {
  const response = await api.post<Job>(`/api/jobs/${jobId}/retry`, null, {
    params: { token },
  });
  return response.data;
};

/**
 * Get a shareable URL for a job
 * The URL includes the access token and can be shared with others
 */
export const getShareUrl = async (jobId: string, token: string): Promise<JobShareResponse> => {
  const response = await api.get<JobShareResponse>(`/api/jobs/${jobId}/share`, {
    params: { token },
  });
  return response.data;
};

/**
 * Permanently delete a job and all associated data
 * This removes the job from database and deletes files from GCS
 * Only works for completed or failed jobs
 */
export const deleteJobPermanent = async (jobId: string, token: string): Promise<void> => {
  await api.delete(`/api/jobs/${jobId}/permanent`, { params: { token } });
};

/**
 * Fetch a short-lived signed GCS URL for a completed job's video.
 * Authorized by cookie session (owner) or per-job access token.
 */
export const getJobVideoUrl = async (
  jobId: string,
  token?: string | null
): Promise<{ download_url: string; expires_in: number }> => {
  const response = await api.get<{ download_url: string; expires_in: number }>(
    `/api/jobs/${jobId}/video_url`,
    token ? { params: { token } } : undefined
  );
  return response.data;
};

/**
 * Fetch a short-lived signed GCS URL for a completed job's screenshot.
 * Authorized by cookie session (owner) or per-job access token.
 */
export const getJobScreenshotUrl = async (
  jobId: string,
  gcsPath: string,
  token?: string | null
): Promise<{ download_url: string; expires_in: number }> => {
  const response = await api.get<{ download_url: string; expires_in: number }>(
    `/api/jobs/${jobId}/screenshot_url`,
    { params: { gcs_path: gcsPath, ...(token ? { token } : {}) } }
  );
  return response.data;
};

/**
 * Submission progress stages
 */
export type SubmissionStage = 'hashing' | 'uploading' | 'submitting' | 'complete';

export interface SubmissionProgress {
  stage: SubmissionStage;
  progress: number;
  message: string;
}

/**
 * Background job submission options
 */
export interface BackgroundJobOptions {
  file: File;
  durationSeconds?: number;
  language?: string;
  forceLanguage?: boolean;
  numSpeakers?: number;
  minSpeakers?: number;
  maxSpeakers?: number;
  onProgress?: (progress: SubmissionProgress) => void;
}

/**
 * Submit a file for background transcription processing.
 *
 * This function handles the complete flow:
 * 1. Generate file hash for deduplication
 * 2. Upload file to GCS (if large) or via backend
 * 3. Submit job to the background processing queue
 * 4. Return job_id and access_token for tracking
 *
 * The submitted job can be tracked after the user closes the browser.
 */
export const submitBackgroundJob = async (
  options: BackgroundJobOptions
): Promise<JobSubmitResponse> => {
  const { file, durationSeconds, language, forceLanguage = false, numSpeakers, minSpeakers, maxSpeakers, onProgress } = options;

  const report = (stage: SubmissionStage, progress: number, message: string) => {
    if (onProgress) {
      onProgress({ stage, progress, message });
    }
    console.log(`[BackgroundJob] ${stage}: ${progress}% - ${message}`);
  };

  // Step 1: Generate file hash (for deduplication)
  report('hashing', 0, 'Calculating file hash...');

  const videoHash = await generateFileHash(file, (hashProgress) => {
    // Hash is 0-10% of overall progress
    report('hashing', Math.round(hashProgress * 0.1), `Calculating hash: ${hashProgress}%`);
  });

  report('hashing', 10, `Hash calculated: ${videoHash.substring(0, 12)}...`);

  // Step 2: Upload through the environment's media storage adapter.
  report('uploading', 10, 'Uploading file...');

  const gcsPath = await uploadMedia(file, (loaded, total, percentage) => {
    // Upload is 10-80% of overall progress
    const mappedProgress = 10 + Math.round(percentage * 0.7);
    const loadedMB = (loaded / (1024 * 1024)).toFixed(1);
    const totalMB = (total / (1024 * 1024)).toFixed(1);
    report('uploading', mappedProgress, `Uploading: ${loadedMB} / ${totalMB} MB`);
  });

  report('uploading', 80, 'Upload complete');

  // Step 3: Submit job to backend
  report('submitting', 80, 'Submitting job...');

  const jobParams: JobSubmitParams = {
    filename: file.name,
    gcs_path: gcsPath,
    file_size_bytes: file.size,
    video_hash: videoHash,
    duration_seconds: durationSeconds,
    language,
    force_language: forceLanguage,
    num_speakers: numSpeakers,
    min_speakers: minSpeakers,
    max_speakers: maxSpeakers,
  };

  const response = await submitJob(jobParams);

  report('complete', 100, response.cached ? 'Found cached result!' : 'Job submitted successfully');

  return response;
};

// ============================================================================
// Face Tagging (for scene search boosting)
// ============================================================================

export interface FaceBbox {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface DetectedFace {
  bbox: FaceBbox;
  confidence: number;
  speaker_name?: string;
  match_confidence?: number;
  already_tagged?: boolean;
  face_tag_id?: string;
}

export interface FaceTagSpeaker {
  speaker_name: string;
  count: number;
}

export const detectFaces = async (
  videoHash: string,
  screenshotUrl: string
): Promise<{ faces: DetectedFace[]; count: number }> => {
  const response = await api.post(`/api/face-tags/${videoHash}/detect`, {
    screenshot_url: screenshotUrl,
  });
  return response.data;
};

export const tagFace = async (
  videoHash: string,
  screenshotUrl: string,
  speakerName: string,
  bbox: FaceBbox
): Promise<{ success: boolean; face_tag_id: string; speaker_name: string }> => {
  const response = await api.post(`/api/face-tags/${videoHash}/tag`, {
    screenshot_url: screenshotUrl,
    speaker_name: speakerName,
    bbox_x: bbox.x,
    bbox_y: bbox.y,
    bbox_w: bbox.w,
    bbox_h: bbox.h,
  });
  return response.data;
};

export const getFaceTagSpeakers = async (
  videoHash: string
): Promise<{ speakers: FaceTagSpeaker[]; total: number }> => {
  const response = await api.get(`/api/face-tags/${videoHash}/speakers`);
  return response.data;
};

export const deleteFaceTag = async (
  videoHash: string,
  faceTagId: string
): Promise<{ success: boolean }> => {
  const response = await api.delete(`/api/face-tags/${videoHash}/${faceTagId}`);
  return response.data;
};

// ============================================================================
// Visual Scene Search API
// ============================================================================

export interface ImageSearchResult {
  screenshot_path: string;
  segment_id: string;
  start: number;
  end: number;
  speaker: string;
  similarity: number;
}

export interface ImageSearchResponse {
  results: ImageSearchResult[];
  video_hash: string;
  query: string;
}

export const searchImages = async (
  query: string,
  videoHash?: string,
  nResults: number = 12
): Promise<ImageSearchResponse> => {
  const response = await api.post<ImageSearchResponse>('/api/search_images/', {
    query,
    video_hash: videoHash,
    n_results: nResults,
  });
  return response.data;
};

export const indexImages = async (videoHash: string, forceReindex: boolean = false): Promise<void> => {
  await api.post('/api/index_images/', null, {
    params: { video_hash: videoHash, force_reindex: forceReindex },
    timeout: forceReindex ? 300000 : undefined, // 5 min for re-indexing
  });
};

// ============================================================================
// Auto Chapter Markers API
// ============================================================================

export interface Chapter {
  start: number;
  end: number;
  start_time: string;
  end_time: string;
  title: string;
  summary: string;
  segment_count: number;
}

export interface ChaptersResponse {
  chapters: Chapter[];
  video_hash: string;
  total_duration: number;
}

export const generateChapters = async (
  videoHash: string,
  provider?: string,
  minChapterDuration?: number
): Promise<ChaptersResponse> => {
  const params: Record<string, string | number> = {};
  if (provider) params.provider = provider;
  if (minChapterDuration) params.min_chapter_duration = minChapterDuration;

  const response = await api.post<ChaptersResponse>(
    `/api/chapters/generate/${videoHash}`,
    null,
    { params }
  );
  return response.data;
};
