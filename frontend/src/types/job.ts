/**
 * TypeScript types for background job processing
 * Defines job status, data structures, and API responses
 */

import { TranscriptionResponse } from '../services/api';

/**
 * Job status lifecycle:
 * pending -> processing -> completed
 *                       -> failed (can be retried)
 * cancelled (terminal, only from pending)
 */
export type JobStatus = 'pending' | 'processing' | 'completed' | 'failed' | 'cancelled';

/**
 * Main job interface matching backend database schema
 */
export interface Job {
  job_id: string;
  access_token: string;
  status: JobStatus;
  filename: string;
  file_size_bytes: number;
  video_hash: string | null;
  gcs_path: string | null;
  progress: number;
  progress_stage: string | null;
  progress_message: string | null;
  error_message: string | null;
  error_code: string | null;
  result_json: TranscriptionResponse | null;
  result_srt: string | null;
  result_vtt: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  last_seen: string | null;
  retry_count: number;

  // Processing parameters
  num_speakers: number | null;
  min_speakers: number | null;
  max_speakers: number | null;
  language: string | null;
  force_language: boolean;

  // Deduplication metadata
  cached?: boolean;
  cached_at?: string;
}

/**
 * Response from job submission endpoint
 */
export interface JobSubmitResponse {
  job_id: string;
  access_token: string;
  cached: boolean;
  cached_at?: string;
  estimated_duration_seconds?: number;
}

/**
 * Minimal job info stored in localStorage for recovery
 */
export interface StoredJob {
  job_id: string;
  access_token: string;
}

/**
 * Paginated job list response
 */
export interface JobListResponse {
  jobs: Job[];
  total: number;
  page: number;
  per_page: number;
}

/**
 * Job submission parameters
 */
export interface JobSubmitParams {
  filename: string;
  gcs_path: string;
  file_size_bytes: number;
  video_hash: string;
  language?: string;
  force_language?: boolean;
  num_speakers?: number;
  min_speakers?: number;
  max_speakers?: number;
}

/**
 * Share URL response
 */
export interface JobShareResponse {
  share_url: string;
}
