import axios from 'axios';
import { API_BASE_URL } from '../config';

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
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
          // FastAPI typically uses 'detail' field
          message = typeof error.response.data.detail === 'string'
            ? error.response.data.detail
            : JSON.stringify(error.response.data.detail);
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

export const transcribeVideo = async (
  variables: { file: File, language?: string } 
): Promise<TranscriptionResponse> => {
  const { file, language } = variables;
  const formData = new FormData();
  formData.append('file', file);
  
  // Append language if provided
  if (language) {
    formData.append('language', language);
    console.log(`API: Sending transcription request with language: ${language}`);
  } else {
    console.log('API: Sending transcription request with auto-detect language');
  }
  
  // Add a best-guess path based on downloaded files location
  // Since the standard File API doesn't have path info, we'll use a best guess
  try {
    // For macOS, common Downloads path
    const isMac = window.navigator.userAgent.includes('Mac');
    const bestGuessPath = isMac 
      ? `/Users/ugurertas/Downloads/${file.name}`
      : `/home/user/Downloads/${file.name}`;
    formData.append('file_path', bestGuessPath);
  } catch (error) {
    console.warn('Could not determine file path for video:', error);
  }

  try {
    const response = await api.post<TranscriptionResponse>('/transcribe/', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
      onUploadProgress: (progressEvent) => {
        const percentage = (progressEvent.loaded / (progressEvent.total ?? 0)) * 100;
        console.log(`Upload Progress: ${percentage}%`);
      },
      // Increase timeout for large files
      timeout: 3600000, // 1 hour
    });

    return response.data;
  } catch (error) {
    if (axios.isAxiosError(error) && error.code === 'ECONNABORTED') {
      throw new Error('Request timed out. The file might be too large or the server is busy.');
    }
    throw error;
  }
};

export const transcribeLocal = async (
  file: File,
  language?: string,
  forceLanguage: boolean = false
): Promise<TranscriptionResponse> => {
  const formData = new FormData();
  formData.append('file', file);

  // Add language parameter if provided
  if (language) {
    formData.append('language', language);
    formData.append('force_language', forceLanguage.toString());
    console.log(`API: Sending local transcription with language: ${language}, force: ${forceLanguage}`);
  } else {
    console.log('API: Sending local transcription with auto-detect language');
  }

  try {
    const response = await api.post<TranscriptionResponse>('/transcribe_local/', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
      onUploadProgress: (progressEvent) => {
        const percentage = (progressEvent.loaded / (progressEvent.total ?? 0)) * 100;
        console.log(`Upload Progress: ${percentage}%`);
      },
      timeout: 3600000, // 1 hour
    });

    return response.data;
  } catch (error) {
    if (axios.isAxiosError(error) && error.code === 'ECONNABORTED') {
      throw new Error('Request timed out. The file might be too large or the server is busy.');
    }
    throw error;
  }
};

// New SSE-based transcription with real-time progress
export const transcribeLocalStream = async (
  file: File,
  onProgress: (stage: string, progress: number, message?: string) => void,
  language?: string,
  forceLanguage: boolean = false
): Promise<TranscriptionResponse> => {
  const formData = new FormData();
  formData.append('file', file);

  // Add language parameter if provided
  if (language) {
    formData.append('language', language);
    formData.append('force_language', forceLanguage.toString());
    console.log(`API: Sending stream transcription with language: ${language}, force: ${forceLanguage}`);
  } else {
    console.log('API: Sending stream transcription with auto-detect language');
  }

  return new Promise((resolve, reject) => {
    fetch(`${API_BASE_URL}/transcribe_local_stream/`, {
      method: 'POST',
      body: formData,
    })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }

        const reader = response.body?.getReader();
        const decoder = new TextDecoder();

        if (!reader) {
          throw new Error('No response body');
        }

        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();

          if (done) break;

          buffer += decoder.decode(value, { stream: true });

          // Process complete SSE messages
          const lines = buffer.split('\n');
          buffer = lines.pop() || ''; // Keep incomplete line in buffer

          for (const line of lines) {
            if (line.startsWith('data: ')) {
              const data = JSON.parse(line.slice(6));

              // Call progress callback
              onProgress(data.stage, data.progress, data.message);

              // If we got the final result
              if (data.result) {
                resolve(data.result);
                return;
              }

              // If there was an error
              if (data.error) {
                reject(new Error(data.error));
                return;
              }
            }
          }
        }
      })
      .catch((error) => {
        reject(error);
      });
  });
};

export const searchTranscription = async (
  topic: string,
  semanticSearch: boolean = true
): Promise<SearchResponse> => {
  const response = await api.post<SearchResponse>(`/search/?topic=${encodeURIComponent(topic)}&semantic_search=${semanticSearch}`);
  
  return response.data;
};

export const getSubtitles = async (language: 'original' | 'english', videoHash?: string): Promise<Blob> => {
  const params = videoHash ? { video_hash: videoHash } : {};
  const response = await api.get(`/subtitles/${language}`, {
    responseType: 'blob',
    params,
  });

  return response.data;
};

export interface SavedTranscription {
  video_hash: string;
  filename: string;
  created_at: string;
  file_path: string | null;
  thumbnail_url?: string | null;
}

export const getSavedTranscriptions = async (): Promise<{ transcriptions: SavedTranscription[] }> => {
  const response = await api.get('/transcriptions/');
  return response.data;
};

export const loadSavedTranscription = async (videoHash: string): Promise<TranscriptionResponse> => {
  const response = await api.get<TranscriptionResponse>(`/transcription/${videoHash}`);
  return response.data;
};

export const deleteTranscription = async (videoHash: string): Promise<{ success: boolean; message: string }> => {
  const response = await api.delete(`/transcription/${videoHash}`);
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
// GCS Upload & Large File Support
// ============================================================================

import { uploadToGCS, requiresGCSUpload, DIRECT_UPLOAD_LIMIT, formatFileSize } from './gcsUpload';

/**
 * Transcribe a file from GCS with real-time progress updates via SSE.
 * Used for large files (>32MB) that were uploaded directly to GCS.
 */
export const transcribeGCSStream = async (
  gcsPath: string,
  filename: string,
  onProgress: (stage: string, progress: number, message?: string) => void,
  language?: string,
  forceLanguage: boolean = false
): Promise<TranscriptionResponse> => {
  const formData = new FormData();
  formData.append('gcs_path', gcsPath);
  formData.append('filename', filename);

  if (language) {
    formData.append('language', language);
    formData.append('force_language', forceLanguage.toString());
    console.log(`API: Sending GCS stream transcription with language: ${language}, force: ${forceLanguage}`);
  } else {
    console.log('API: Sending GCS stream transcription with auto-detect language');
  }

  return new Promise((resolve, reject) => {
    fetch(`${API_BASE_URL}/transcribe_gcs_stream/`, {
      method: 'POST',
      body: formData,
    })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }

        const reader = response.body?.getReader();
        const decoder = new TextDecoder();

        if (!reader) {
          throw new Error('No response body');
        }

        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();

          if (done) break;

          buffer += decoder.decode(value, { stream: true });

          // Process complete SSE messages
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';

          for (const line of lines) {
            if (line.startsWith('data: ')) {
              try {
                const data = JSON.parse(line.slice(6));

                // Call progress callback
                onProgress(data.stage, data.progress, data.message);

                // If we got the final result
                if (data.result) {
                  resolve(data.result);
                  return;
                }

                // If there was an error
                if (data.error) {
                  reject(new Error(data.error));
                  return;
                }
              } catch (e) {
                console.warn('Failed to parse SSE data:', line);
              }
            }
          }
        }
      })
      .catch((error) => {
        reject(error);
      });
  });
};

/**
 * Smart transcription that automatically handles both small and large files.
 *
 * - Files < 32MB: Direct upload via transcribeLocalStream
 * - Files >= 32MB: Upload to GCS first, then process via transcribeGCSStream
 *
 * Progress is unified:
 * - 0-50%: Uploading (for large files via GCS)
 * - 50-100%: Processing (transcription, screenshots, etc.)
 */
export const transcribeSmartStream = async (
  file: File,
  onProgress: (stage: string, progress: number, message?: string) => void,
  language?: string,
  forceLanguage: boolean = false
): Promise<TranscriptionResponse> => {
  const fileSize = file.size;
  const fileSizeFormatted = formatFileSize(fileSize);

  console.log(`[Smart] File size: ${fileSizeFormatted}, requires GCS: ${requiresGCSUpload(fileSize)}`);

  if (requiresGCSUpload(fileSize)) {
    // Large file: Upload to GCS first, then process
    console.log(`[Smart] Large file detected (${fileSizeFormatted}), using GCS upload`);

    onProgress('uploading', 0, `Preparing to upload ${fileSizeFormatted}...`);

    // Upload to GCS with progress tracking (0-50%)
    const gcsPath = await uploadToGCS(file, (loaded, total, percentage) => {
      // Map GCS upload progress to 0-50%
      const mappedProgress = Math.round(percentage * 0.5);
      const loadedFormatted = formatFileSize(loaded);
      const totalFormatted = formatFileSize(total);
      onProgress('uploading', mappedProgress, `Uploading ${loadedFormatted} / ${totalFormatted}`);
    });

    console.log(`[Smart] GCS upload complete: ${gcsPath}`);
    onProgress('uploading', 50, 'Upload complete, starting transcription...');

    // Process via GCS stream endpoint (50-100%)
    return transcribeGCSStream(
      gcsPath,
      file.name,
      (stage, progress, message) => {
        // Map backend progress (0-100) to 50-100%
        const mappedProgress = 50 + Math.round(progress * 0.5);
        onProgress(stage, mappedProgress, message);
      },
      language,
      forceLanguage
    );
  } else {
    // Small file: Direct upload
    console.log(`[Smart] Small file (${fileSizeFormatted}), using direct upload`);
    return transcribeLocalStream(file, onProgress, language, forceLanguage);
  }
};

/**
 * Get the maximum file size that can be uploaded directly (without GCS)
 */
export const getDirectUploadLimit = (): number => DIRECT_UPLOAD_LIMIT;

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
 * Get a paginated list of jobs using stored access tokens
 * @param tokens - Array of access tokens for jobs to fetch
 * @param page - Page number (1-indexed)
 * @param perPage - Number of jobs per page (default 10)
 */
export const getJobs = async (
  tokens: string[],
  page: number = 1,
  perPage: number = 10
): Promise<JobListResponse> => {
  const response = await api.get<JobListResponse>('/api/jobs', {
    params: {
      tokens: tokens.join(','),
      page,
      per_page: perPage,
    },
  });
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
 * Unlike SSE-based transcription, this allows the user to close their browser
 * and receive notifications when processing is complete.
 */
export const submitBackgroundJob = async (
  options: BackgroundJobOptions
): Promise<JobSubmitResponse> => {
  const { file, language, forceLanguage = false, numSpeakers, minSpeakers, maxSpeakers, onProgress } = options;

  const report = (stage: SubmissionStage, progress: number, message: string) => {
    if (onProgress) {
      onProgress({ stage, progress, message });
    }
    console.log(`[BackgroundJob] ${stage}: ${progress}% - ${message}`);
  };

  // Step 1: Generate file hash (for deduplication)
  report('hashing', 0, 'Calculating file hash...');

  // Import hash utility dynamically to avoid circular deps
  const { generateFileHash } = await import('../utils/file');
  const videoHash = await generateFileHash(file, (hashProgress) => {
    // Hash is 0-10% of overall progress
    report('hashing', Math.round(hashProgress * 0.1), `Calculating hash: ${hashProgress}%`);
  });

  report('hashing', 10, `Hash calculated: ${videoHash.substring(0, 12)}...`);

  // Step 2: Upload to GCS
  report('uploading', 10, 'Uploading file...');

  // Always use GCS for background jobs (ensures file is available for async processing)
  const gcsPath = await uploadToGCS(file, (loaded, total, percentage) => {
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