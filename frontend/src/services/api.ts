import axios from 'axios';

const api = axios.create({
  baseURL: 'http://localhost:8000',
  headers: {
    'Content-Type': 'application/json',
  },
});

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

  const response = await api.post<TranscriptionResponse>('/transcribe/', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
    onUploadProgress: (progressEvent) => {
      const percentage = (progressEvent.loaded / (progressEvent.total ?? 0)) * 100;
      console.log(`Upload Progress: ${percentage}%`);
    },
  });

  return response.data;
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