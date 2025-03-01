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
  transcription: {
    text: string;
    translated_text: string;
    language: string;
    duration: string;
    segments: Array<{
      id: number;
      start_time: string;
      end_time: string;
      text: string;
      translation: string | null;
    }>;
    processing_time: string;
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

export const transcribeVideo = async (file: File): Promise<TranscriptionResponse> => {
  const formData = new FormData();
  formData.append('file', file);

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

export const searchTranscription = async (
  topic: string,
  semanticSearch: boolean = true
): Promise<SearchResponse> => {
  const response = await api.post<SearchResponse>('/search/', {
    topic,
    semantic_search: semanticSearch,
  });

  return response.data;
};

export const getSubtitles = async (language: 'original' | 'english'): Promise<Blob> => {
  const response = await api.get(`/subtitles/${language}`, {
    responseType: 'blob',
  });

  return response.data;
}; 