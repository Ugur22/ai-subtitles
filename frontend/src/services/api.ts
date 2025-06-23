import axios from 'axios';

const api = axios.create({
  baseURL: 'http://localhost:8000',
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
      const message = error.response.data.detail || 'An error occurred';
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

export const transcribeLocal = async (file: File): Promise<TranscriptionResponse> => {
  const formData = new FormData();
  formData.append('file', file);

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

export const searchTranscription = async (
  topic: string,
  semanticSearch: boolean = true
): Promise<SearchResponse> => {
  const response = await api.post<SearchResponse>(`/search/?topic=${encodeURIComponent(topic)}&semantic_search=${semanticSearch}`);
  
  return response.data;
};

export const getSubtitles = async (language: 'original' | 'english'): Promise<Blob> => {
  const response = await api.get(`/subtitles/${language}`, {
    responseType: 'blob',
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

export const translateLocalText = async (text: string, sourceLang: string): Promise<string> => {
  const response = await api.post('/translate_local/', {
    text,
    source_lang: sourceLang,
  });
  return response.data.translation;
}; 