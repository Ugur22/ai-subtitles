import { useState, useRef, useEffect } from 'react';
import { useMutation } from '@tanstack/react-query';
import { transcribeVideo, TranscriptionResponse, transcribeLocal } from '../../../services/api';
import { SubtitleControls } from './SubtitleControls';
import { SearchPanel } from '../search/SearchPanel';
import { AnalyticsPanel } from '../analytics/AnalyticsPanel';
import ReactPlayer from 'react-player';
import { SummaryPanel } from '../summary/SummaryPanel';
import { SavedTranscriptionsPanel } from './SavedTranscriptionsPanel';
import { extractAudio, getAudioDuration, initFFmpeg } from '../../../utils/ffmpeg';
import axios, { AxiosProgressEvent } from 'axios';
import * as apiService from '../../../services/api';

// Add custom subtitle styles
const subtitleStyles = `
::cue {
  background-color: rgba(0, 0, 0, 0.75);
  color: white;
  font-family: sans-serif;
  font-size: 1em;
  line-height: 1.4;
  text-shadow: 0px 1px 2px rgba(0, 0, 0, 0.8);
  padding: 0.2em 0.5em;
  border-radius: 0.2em;
  white-space: pre-line;
}
`;

type ProcessingStage = 'uploading' | 'transcribing' | 'translating' | 'extracting' | 'complete';

interface ProcessingStatus {
  stage: ProcessingStage;
  progress: number;
}

// Helper to format processing time for better readability
const formatProcessingTime = (timeStr?: string | null): string => {
  // Return a default value if timeStr is undefined or null
  if (!timeStr) {
    return "Unknown";
  }
  
  // Try to extract a numeric value from the time string
  let seconds = 0;
  
  // Try to parse seconds from the string
  if (timeStr.includes('seconds')) {
    seconds = parseFloat(timeStr.replace(' seconds', '').trim());
  } else {
    // If it's a number without units, assume it's seconds
    const parsed = parseFloat(timeStr);
    if (!isNaN(parsed)) {
      seconds = parsed;
    }
  }
  
  // If we've successfully parsed a seconds value
  if (seconds > 0) {
    if (seconds < 5) {
      // Very fast processing
      return `${seconds.toFixed(1)} seconds (super fast!)`;
    } else if (seconds < 60) {
      // Less than a minute, keep as seconds
      return `${seconds.toFixed(1)} seconds`;
    } else {
      // Convert to minutes and seconds
      const minutes = Math.floor(seconds / 60);
      const remainingSeconds = Math.round(seconds % 60);
      
      if (remainingSeconds === 0) {
        // Even minutes
        return minutes === 1 ? "1 minute" : `${minutes} minutes`;
      } else {
        // Minutes and seconds
        return minutes === 1 
          ? `1 minute ${remainingSeconds} seconds` 
          : `${minutes} minutes ${remainingSeconds} seconds`;
      }
    }
  }
  
  // If we couldn't parse it, return the original
  return timeStr;
};

// Function to check if a file exists using the Fetch API
const checkFileExists = async (path: string): Promise<boolean> => {
  try {
    // For local file system access, we need to use the file:// protocol
    const fileUrl = path.startsWith('/') ? `file://${path}` : path;
    const response = await fetch(fileUrl, { method: 'HEAD' });
    return response.ok;
  } catch (error) {
    console.warn('Error checking if file exists:', error);
    return false;
  }
};

// Define the SummarySection interface that was in SummaryPanel.tsx
interface SummarySection {
  title: string;
  start: string;
  end: string;
  summary: string;
  screenshot_url?: string | null;
}

// Simple Image Modal Component
interface ImageModalProps {
  imageUrl: string;
  onClose: () => void;
}

const ImageModal: React.FC<ImageModalProps> = ({ imageUrl, onClose }) => {
  // Prevent closing modal when clicking on the image itself
  const handleImageClick = (e: React.MouseEvent) => {
    e.stopPropagation();
  };

  return (
    <div 
      className="fixed inset-0 bg-black bg-opacity-75 flex items-center justify-center z-50 p-4"
      onClick={onClose} // Close when clicking backdrop
    >
      <div 
        className="relative bg-white p-2 rounded-lg shadow-xl max-w-6xl max-h-[90vh]"
        onClick={handleImageClick} // Prevent closing on image container click
      >
        <img 
          src={imageUrl}
          alt="Enlarged screenshot" 
          className="block w-[900px] max-h-[85vh] object-contain rounded-xl"
        />
        <button
          onClick={onClose}
          className="absolute top-2 right-2 bg-white rounded-full p-1 text-gray-700 hover:bg-gray-200 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-gray-500"
          aria-label="Close image modal"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>
    </div>
  );
};

// Add transcription method type
type TranscriptionMethod = 'local' | 'openai';

// Add translation function
const translateTranscription = async (transcriptionResult: TranscriptionResponse) => {
  try {
    // Only translate if not in English
    if (transcriptionResult.transcription.language.toLowerCase() !== 'en') {
      const batchSize = 5; // Process 5 segments at a time
      const segments = transcriptionResult.transcription.segments;
      const translatedSegments = [...segments]; // Create a copy to modify
      
      // Process segments in batches
      for (let i = 0; i < segments.length; i += batchSize) {
        const batch = segments.slice(i, i + batchSize);
        const batchText = batch.map(s => s.text).join('\n[SEP]\n');
        
        try {
          // Use OpenAI for translation
          const response = await axios.post('http://localhost:8000/translate/', {
            text: batchText,
            source_lang: transcriptionResult.transcription.language
          });

          // Split the translated text back into segments
          const translations = response.data.translation.split('[SEP]').map((t: string) => t.trim());
          
          // Update the segments with their translations
          translations.forEach((translation: string, index: number) => {
            if (i + index < translatedSegments.length) {
              translatedSegments[i + index] = {
                ...translatedSegments[i + index],
                translation: translation
              };
            }
          });
        } catch (error) {
          console.error(`Translation failed for batch ${i}:`, error);
          // Continue with next batch even if this one failed
        }
      }

      return {
        ...transcriptionResult,
        transcription: {
          ...transcriptionResult.transcription,
          segments: translatedSegments
        }
      };
    }
    return transcriptionResult;
  } catch (error) {
    console.error('Translation failed:', error);
    return transcriptionResult;
  }
};

export const TranscriptionUpload = () => {
  const [uploadProgress, setUploadProgress] = useState(0);
  const [transcription, setTranscription] = useState<TranscriptionResponse | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [showTranslation, setShowTranslation] = useState(false);
  const [showSummary, setShowSummary] = useState(false);
  const [showSearch, setShowSearch] = useState(true);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [processingStatus, setProcessingStatus] = useState<ProcessingStatus | null>(null);
  const [hideProgressBar, setHideProgressBar] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const playerRef = useRef<any>(null);
  const [file, setFile] = useState<File | null>(null);
  const [videoRef, setVideoRef] = useState<HTMLVideoElement | null>(null);
  const [showSubtitles, setShowSubtitles] = useState(true);
  const [subtitleTrackUrl, setSubtitleTrackUrl] = useState<string | null>(null);
  const [translatedSubtitleUrl, setTranslatedSubtitleUrl] = useState<string | null>(null);
  const [progressSimulation, setProgressSimulation] = useState<NodeJS.Timeout | null>(null);
  const [activeSegmentId, setActiveSegmentId] = useState<number | null>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [elapsedTime, setElapsedTime] = useState(0);
  const [processingTimer, setProcessingTimer] = useState<NodeJS.Timeout | null>(null);
  const [showProgressBar, setShowProgressBar] = useState(false);
  const [isNewTranscription, setIsNewTranscription] = useState(false);
  const [showSavedTranscriptions, setShowSavedTranscriptions] = useState(false);
  const [summaries, setSummaries] = useState<SummarySection[]>([]);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [selectedLanguage, setSelectedLanguage] = useState<string>('');
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [modalImageUrl, setModalImageUrl] = useState<string | null>(null);
  const [transcriptionMethod, setTranscriptionMethod] = useState<TranscriptionMethod>('local');
  const [isVideoSeeking, setIsVideoSeeking] = useState(false);

  const transcribeMutation = useMutation({
    mutationFn: transcribeVideo,
    onMutate: () => {
      // Reset the flag when starting a new transcription
      setIsNewTranscription(false);
      
      // Show progress bar when starting a new transcription
      setHideProgressBar(false);
      
      // Start with uploading status
      setProcessingStatus({ stage: 'uploading', progress: 0 });
      
      // Start the timer for elapsed time
      if (processingTimer) {
        clearInterval(processingTimer);
      }
      
      setElapsedTime(0);
      const timer = setInterval(() => {
        setElapsedTime(prev => prev + 1);
      }, 1000);
      
      setProcessingTimer(timer);
    },
    onSuccess: (data) => {
      // Clear simulation on success
      if (progressSimulation) {
        clearInterval(progressSimulation);
        setProgressSimulation(null);
      }
      
      // Clear processing timer
      if (processingTimer) {
        clearInterval(processingTimer);
        setProcessingTimer(null);
      }
      
      setTranscription(data);
      setProcessingStatus({ stage: 'complete', progress: 100 });
      setError(null);
    },
    onError: (error) => {
      // Clear simulation on error
      if (progressSimulation) {
        clearInterval(progressSimulation);
        setProgressSimulation(null);
      }
      
      // Clear processing timer
      if (processingTimer) {
        clearInterval(processingTimer);
        setProcessingTimer(null);
      }
      
      console.error('Transcription error:', error);
      setError('Failed to transcribe the file. Please try again.');
      setProcessingStatus({ stage: 'uploading', progress: 0 });
    }
  });

  // Clean up object URL when component unmounts or videoUrl changes
  useEffect(() => {
    return () => {
      if (videoUrl) {
        URL.revokeObjectURL(videoUrl);
      }
    };
  }, [videoUrl]);

  // Cleanup function for progress simulation
  useEffect(() => {
    return () => {
      if (progressSimulation) {
        clearInterval(progressSimulation);
      }
    };
  }, [progressSimulation]);

  // Add time update handler to track current video position
  useEffect(() => {
    if (videoRef) {
      const handleTimeUpdate = () => {
        setCurrentTime(videoRef.currentTime);
        
        // Find the currently active segment based on video time
        if (transcription) {
          const currentSegment = transcription.transcription.segments.find(segment => {
            const startSeconds = convertTimeToSeconds(segment.start_time);
            const endSeconds = convertTimeToSeconds(segment.end_time);
            return videoRef.currentTime >= startSeconds && videoRef.currentTime <= endSeconds;
          });
          
          setActiveSegmentId(currentSegment?.id ?? null);
        }
      };
      
      videoRef.addEventListener('timeupdate', handleTimeUpdate);
      
      return () => {
        videoRef.removeEventListener('timeupdate', handleTimeUpdate);
      };
    }
  }, [videoRef, transcription]);
  
  // Helper to convert HH:MM:SS to seconds
  const convertTimeToSeconds = (timeString: string): number => {
    const [hours, minutes, seconds] = timeString.split(':').map(Number);
    return hours * 3600 + minutes * 60 + seconds;
  };

  const handleLanguageChange = (event: React.ChangeEvent<HTMLSelectElement>) => {
    setSelectedLanguage(event.target.value);
  };

  const handleFileChange = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = event.target.files?.[0];
    if (selectedFile) {
      setFile(selectedFile);
      // Create URL for video preview if it's a video file
      if (selectedFile.type.startsWith('video/')) {
        const url = URL.createObjectURL(selectedFile);
        setVideoUrl(url);
      } else {
        setVideoUrl(null); // Clear video URL for non-video files
      }
      // Don't start processing immediately
      // await processFile(file);
      // Reset any previous errors or results
      setError(null);
      setTranscription(null);
      setProcessingStatus(null);
      setElapsedTime(0);
      if (processingTimer) clearInterval(processingTimer);
    }
  };

  const processFile = async (fileToProcess: File) => {
    try {
      setProcessingStatus({ stage: 'uploading', progress: 0 });
      setError(null);
      
      // Choose transcription method based on user selection
      const transcriptionResult = await (transcriptionMethod === 'local' 
        ? transcribeLocal(fileToProcess)
        : transcribeVideo({ file: fileToProcess, language: selectedLanguage }));
      
      // Translate if needed
      const translatedResult = await translateTranscription(transcriptionResult);
      
      setTranscription(translatedResult);
      setProcessingStatus({ stage: 'complete', progress: 100 });
      
    } catch (error) {
      setError(error instanceof Error ? error.message : 'An error occurred during transcription');
      setProcessingStatus({ stage: 'complete', progress: 0 });
    }
  };

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true);
    } else if (e.type === 'dragleave') {
      setDragActive(false);
    }
  };

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      const droppedFile = e.dataTransfer.files[0];
      setFile(droppedFile);
      
      // Create and store video URL for dropped file if it's a video
      if (droppedFile.type.startsWith('video/')) {
        const objectUrl = URL.createObjectURL(droppedFile);
        setVideoUrl(objectUrl);
      } else {
        setVideoUrl(null);
      }
      
      // Don't start processing immediately
      // try {
      //   await processFile(file);
      // } catch (error) {
      //   console.error('Processing failed:', error);
      // }
      // Reset any previous errors or results
      setError(null);
      setTranscription(null);
      setProcessingStatus(null);
      setElapsedTime(0);
      if (processingTimer) clearInterval(processingTimer);
    }
  };

  const handleButtonClick = () => {
    fileInputRef.current?.click();
  };

  // New handler to start the transcription process
  const handleStartTranscriptionClick = () => {
    if (file) {
      processFile(file); // Pass the file from state
    } else {
      setError("No file selected to transcribe.");
    }
  };

  const startNewTranscription = () => {
    // Set flag to hide progress bar
    setIsNewTranscription(true);
    
    setTranscription(null);
    setVideoUrl(null);
    setFile(null);
    setShowTranslation(false);
    setShowSubtitles(false);
    setUploadProgress(0);
    setElapsedTime(0);
    setSelectedLanguage('');
    
    if (processingTimer) {
      clearInterval(processingTimer);
      setProcessingTimer(null);
    }
    
    setTimeout(() => {
      setShowSubtitles(true);
    }, 500);
  };

  // Function to delete previous screenshots
  const cleanupPreviousScreenshots = async () => {
    try {
      await axios.post('http://localhost:8000/cleanup_screenshots/');
      console.log('Previous screenshots cleaned up successfully');
    } catch (error) {
      console.error('Failed to cleanup screenshots:', error);
      // Non-critical error, don't show to user
    }
  };

  const seekToTimestamp = (timeString: string) => {
    if (!videoRef || !timeString) return;
    
    const seconds = timeToSeconds(timeString);
    videoRef.currentTime = seconds;
    videoRef.play().catch((err: Error) => console.error("Error playing video:", err));
    
    // Find the corresponding segment in the transcript
    if (transcription && transcription.transcription.segments) {
      const segments = transcription.transcription.segments;
      const matchingSegmentId = segments.findIndex(segment => {
        const segmentStartSeconds = timeToSeconds(segment.start_time);
        const segmentEndSeconds = timeToSeconds(segment.end_time);
        return seconds >= segmentStartSeconds && seconds <= segmentEndSeconds;
      });
      
      // If a matching segment is found, scroll to it
      if (matchingSegmentId !== -1) {
        setActiveSegmentId(matchingSegmentId);
        
        // Use setTimeout to ensure the DOM has updated with the active segment
        setTimeout(() => {
          const segmentElement = document.getElementById(`transcript-segment-${matchingSegmentId}`);
          if (segmentElement) {
            // Find the scrollable container instead of scrolling the whole page
            const transcriptContainer = document.querySelector('.flex-grow.overflow-auto');
            if (transcriptContainer) {
              // Calculate position relative to the container
              const containerRect = transcriptContainer.getBoundingClientRect();
              const elementRect = segmentElement.getBoundingClientRect();
              const relativeTop = elementRect.top - containerRect.top;
              
              // Scroll the container, not the element
              transcriptContainer.scrollTo({
                top: transcriptContainer.scrollTop + relativeTop - 100, // 100px from top for better visibility
                behavior: 'smooth'
              });
            } else {
              // Fallback to the previous behavior
              segmentElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }
          }
        }, 100);
      }
    }
  };

  const handleSummaryClick = () => {
    setShowSearch(false);
    setShowSavedTranscriptions(false);
    setShowSummary(!showSummary);
  };

  const handleSearchClick = () => {
    setShowSearch(!showSearch);
  };

  const handleSavedTranscriptionsClick = () => {
    setShowSavedTranscriptions(!showSavedTranscriptions);
  };

  // Handle when a saved transcription is loaded
  const handleTranscriptionLoaded = async (videoHash?: string) => {
    try {
      let data;
      
      if (videoHash) {
        // Load a specific saved transcription
        const response = await axios.get(`http://localhost:8000/transcription/${videoHash}`);
        data = response.data;
      } else {
        // Load the current transcription
        const response = await axios.get('http://localhost:8000/current_transcription/');
        data = response.data;
      }
      
      console.log("Loaded transcription data:", data);
      
      // Check if translations are needed
      if (data.transcription.language.toLowerCase() !== 'en') {
        // Check if any segments are missing translations
        const needsTranslation = data.transcription.segments.some((segment: { translation: string | null }) => !segment.translation);
        if (needsTranslation) {
          console.log("Some segments are missing translations, translating...");
          data = await translateTranscription(data);
        }
      }
      
      // Reset state for new transcription
      setTranscription(data);
      setFile(null);
      setProcessingStatus({ stage: 'complete', progress: 100 });
      setShowSavedTranscriptions(false);
      
      // Reset summaries for the new transcription
      setSummaries([]);
      
      // Load video if video_hash exists
      if (data.video_hash) {
        const videoPath = `http://localhost:8000/video/${data.video_hash}`;
        console.log("Setting video URL:", videoPath);
        setVideoUrl(videoPath);
      } else if (data.file_path) {
        // Fallback to try to extract hash from file_path
        const pathParts = data.file_path.split('/');
        const fileName = pathParts[pathParts.length - 1];
        const hashMatch = fileName.match(/^([a-f0-9]+)\./i);
        
        if (hashMatch && hashMatch[1]) {
          const extractedHash = hashMatch[1];
          const videoPath = `http://localhost:8000/video/${extractedHash}`;
          console.log("Setting video URL (extracted from filename):", videoPath);
          setVideoUrl(videoPath);
        } else {
          console.error("Could not determine video hash from:", data);
          setError("Could not load video: Missing video identifier");
        }
      } else {
        console.error("No video_hash or file_path in transcription data:", data);
        setError("Could not load video: Missing file information");
      }
    } catch (error) {
      console.error("Error loading transcription:", error);
      setError("Failed to load the transcription. Please try again.");
    }
  };

  // Generate WebVTT content from transcript segments
  const generateWebVTT = (segments: any[], useTranslation: boolean = false): string => {
    let vttContent = 'WEBVTT\n\n';
    
    // Get language to optimize chunking
    const language = transcription?.transcription.language || 'en';
    
    // Determine optimal chunk size based on language complexity
    // Some languages are more information-dense and need fewer words per line
    const getOptimalChunkSize = (lang: string): number => {
      const langSettings: {[key: string]: number} = {
        'en': 7,     // English - standard
        'de': 5,     // German - longer words
        'ja': 12,    // Japanese - character-based
        'zh': 12,    // Chinese - character-based
        'ko': 10,    // Korean - character-based
        'it': 6,     // Italian
        'fr': 6,     // French
        'es': 6,     // Spanish
        'ru': 5,     // Russian - longer words
      };
      
      return langSettings[lang.toLowerCase()] || 6; // Default to 6 words
    };
    
    // Base chunk size on language
    const maxWordsPerChunk = getOptimalChunkSize(language);
    
    segments.forEach((segment, index) => {
      // Convert HH:MM:SS format to HH:MM:SS.000 (WebVTT requires milliseconds)
      const startTime = segment.start_time.includes('.') 
        ? segment.start_time 
        : `${segment.start_time}.000`;
        
      const endTime = segment.end_time.includes('.') 
        ? segment.end_time 
        : `${segment.end_time}.000`;
      
      // Use translation if available and requested
      const text = useTranslation && segment.translation 
        ? segment.translation 
        : segment.text;
      
      // Smart chunking based on:
      // 1. Respect sentence boundaries (., ?, !)
      // 2. Respect clause boundaries (,, :, ;) 
      // 3. Keep important phrases together
      
      // Split into natural language chunks
      const breakText = (text: string): string[] => {
        if (text.length <= 42) { // Short text - no need to break
          return [text];
        }
        
        // Try to break at sentence boundaries first
        const sentenceBreaks = text.match(/[.!?]+(?=\s|$)/g);
        if (sentenceBreaks && sentenceBreaks.length > 1) {
          // Multiple sentences - break at sentence boundaries
          return text.split(/(?<=[.!?])\s+/g).filter(s => s.trim().length > 0);
        }
        
        // Try to break at clause boundaries
        const clauseMatches = text.match(/[,;:]+(?=\s|$)/g);
        if (clauseMatches && clauseMatches.length > 0) {
          // Break at clauses
          return text.split(/(?<=[,;:])\s+/g).filter(s => s.trim().length > 0);
        }
        
        // Last resort: break by word count
        const words = text.split(' ');
        const chunks = [];
        
        for (let i = 0; i < words.length; i += maxWordsPerChunk) {
          chunks.push(words.slice(i, i + maxWordsPerChunk).join(' '));
        }
        
        return chunks;
      };
      
      const textChunks = breakText(text);
      
      // If only one chunk, display as is
      if (textChunks.length === 1) {
        vttContent += `${index + 1}\n`;
        vttContent += `${startTime} --> ${endTime}\n`;
        vttContent += `${text}\n\n`;
      } else {
        // Multiple chunks - distribute timing
        const segmentDurationMs = timeToMs(endTime) - timeToMs(startTime);
        const msPerChunk = segmentDurationMs / textChunks.length;
        
        textChunks.forEach((chunk, chunkIndex) => {
          const chunkStartMs = timeToMs(startTime) + (chunkIndex * msPerChunk);
          const chunkEndMs = chunkIndex === textChunks.length - 1 
            ? timeToMs(endTime)  // Last chunk ends at segment end
            : chunkStartMs + msPerChunk;
          
          vttContent += `${index + 1}.${chunkIndex + 1}\n`;
          vttContent += `${msToTime(chunkStartMs)} --> ${msToTime(chunkEndMs)}\n`;
          vttContent += `${chunk}\n\n`;
        });
      }
    });
    
    return vttContent;
  };
  
  // Helper function to convert HH:MM:SS.mmm to milliseconds
  const timeToMs = (timeString: string): number => {
    const [time, ms = '0'] = timeString.split('.');
    const [hours, minutes, seconds] = time.split(':').map(Number);
    
    return (hours * 3600 + minutes * 60 + seconds) * 1000 + parseInt(ms.padEnd(3, '0').substring(0, 3));
  };
  
  // Helper function to convert milliseconds to HH:MM:SS.mmm format
  const msToTime = (ms: number): string => {
    const totalSeconds = Math.floor(ms / 1000);
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    const milliseconds = ms % 1000;
    
    return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}.${String(milliseconds).padStart(3, '0')}`;
  };
  
  // Create and add subtitles to video
  const createSubtitleTracks = () => {
    if (!transcription) return;
    
    try {
      // Generate original language WebVTT
      const vttContent = generateWebVTT(transcription.transcription.segments);
      const vttBlob = new Blob([vttContent], { type: 'text/vtt' });
      const vttUrl = URL.createObjectURL(vttBlob);
      setSubtitleTrackUrl(vttUrl);
      
      // Generate translated WebVTT if translations are available
      const hasTranslations = transcription.transcription.segments.some(segment => segment.translation);
      
      if (hasTranslations) {
        const translatedVttContent = generateWebVTT(transcription.transcription.segments, true);
        const translatedVttBlob = new Blob([translatedVttContent], { type: 'text/vtt' });
        const translatedVttUrl = URL.createObjectURL(translatedVttBlob);
        setTranslatedSubtitleUrl(translatedVttUrl);
      }
    } catch (error) {
      console.error('Error creating subtitles:', error);
    }
  };
  
  // Create subtitles when transcription is available
  useEffect(() => {
    if (transcription) {
      createSubtitleTracks();
      
      // Add custom subtitle styles to document head
      const styleElement = document.createElement('style');
      styleElement.innerHTML = subtitleStyles;
      document.head.appendChild(styleElement);
      
      return () => {
        if (subtitleTrackUrl) {
          URL.revokeObjectURL(subtitleTrackUrl);
        }
        if (translatedSubtitleUrl) {
          URL.revokeObjectURL(translatedSubtitleUrl);
        }
        // Remove custom styles when component unmounts
        document.head.removeChild(styleElement);
      };
    }
  }, [transcription]);
  
  // Update subtitles when translation toggle changes
  useEffect(() => {
    if (videoRef) {
      const trackElements = videoRef.textTracks;
      
      if (trackElements.length > 0) {
        // Hide all tracks first
        for (let i = 0; i < trackElements.length; i++) {
          trackElements[i].mode = 'hidden';
        }
        
        // Show the active track if subtitles are enabled
        if (showSubtitles) {
          const trackIndex = showTranslation && trackElements.length > 1 ? 1 : 0;
          trackElements[trackIndex].mode = 'showing';
        }
      }
    }
  }, [showTranslation, showSubtitles, videoRef]);
  
  // Toggle subtitles visibility
  const toggleSubtitles = () => {
    setShowSubtitles(!showSubtitles);
  };

  // Cleanup function for timers when component unmounts
  useEffect(() => {
    return () => {
      if (progressSimulation) {
        clearInterval(progressSimulation);
      }
      if (processingTimer) {
        clearInterval(processingTimer);
      }
    };
  }, [progressSimulation, processingTimer]);

  // Update the handle functions for processing status to handle null
  const updateUploadProgress = (progress: number) => {
    setUploadProgress(progress);
    setProcessingStatus(prevStatus => 
      prevStatus ? {
        ...prevStatus,
        progress: Math.min(99, progress)
      } : { stage: 'uploading', progress: Math.min(99, progress) }
    );
  };

  const handleExtractingAudio = () => {
    setProcessingStatus(prevStatus => 
      prevStatus ? {
        ...prevStatus,
        stage: 'extracting',
        progress: 0
      } : { stage: 'extracting', progress: 0 }
    );
  };

  const handleTranscribing = () => {
    setProcessingStatus(prevStatus => 
      prevStatus ? {
        ...prevStatus,
        stage: 'transcribing',
        progress: 0
      } : { stage: 'transcribing', progress: 0 }
    );
  };

  // Function to fetch the current transcription data from the backend
  const fetchCurrentTranscription = async (): Promise<TranscriptionResponse | null> => {
    try {
      const response = await fetch('http://localhost:8000/current_transcription/');
      
      if (!response.ok) {
        console.error('Failed to fetch current transcription', response.statusText);
        return null;
      }
      
      const data = await response.json();
      setTranscription(data);
      // Reset summaries when loading a new transcription to prevent showing summaries from previous videos
      setSummaries([]);
      setProcessingStatus({ stage: 'complete', progress: 100 });
      
      // Set video URL if video_hash is available
      if (data.video_hash) {
        const videoPath = `http://localhost:8000/video/${data.video_hash}`;
        console.log("Setting video URL from current transcription:", videoPath);
        setVideoUrl(videoPath);
      }
      
      return data;
    } catch (error) {
      console.error('Error fetching current transcription:', error);
      return null;
    }
  };

  // Add a function to generate summaries here (moved from SummaryPanel)
  const generateSummaries = async () => {
    setSummaryLoading(true);
    try {
      console.log("Generating summaries...");
      const response = await axios.post('http://localhost:8000/generate_summary/');
      console.log("Summary response:", response.data);
      
      const summaryData = response.data.summaries || [];
      const responseFilename = response.data.filename;
      
      // More detailed logging to debug the issue
      console.log("Current transcription:", transcription?.filename);
      console.log("Response filename:", responseFilename);
      
      // Only perform the filename check if both filenames are defined and don't match
      // This ensures we still show summaries even if one of the filenames is undefined
      if (transcription && responseFilename && transcription.filename && 
          responseFilename !== transcription.filename) {
        console.warn("Summary filename mismatch:", responseFilename, "vs", transcription.filename);
        // Continue anyway - don't return early
      }
      
      console.log("Received summary data:", summaryData);
      
      if (!summaryData || summaryData.length === 0) {
        console.warn("No summary data received");
        setSummaryLoading(false);
        return;
      }
      
      console.log("Now fetching screenshots for summaries...");
      
      // First set the basic summaries without screenshots
      setSummaries(summaryData);
      
      // Then try to enhance them with screenshots
      try {
        const enhancedSummaries = await fetchScreenshotsForSummaries(summaryData);
        console.log("Final enhanced summaries:", enhancedSummaries);
        setSummaries(enhancedSummaries);
      } catch (screenshotError) {
        console.error("Error adding screenshots to summaries:", screenshotError);
        // We still have the basic summaries displayed
      }
      
    } catch (error) {
      console.error('Error generating summaries:', error);
      // Handle error (you can add error state if needed)
    } finally {
      setSummaryLoading(false);
    }
  };
  
  // Add the helper function to fetch screenshots (moved from SummaryPanel)
  const fetchScreenshotsForSummaries = async (summaryData: SummarySection[]) => {
    try {
      // Get the current transcription data
      const response = await axios.get('http://localhost:8000/current_transcription/');
      
      if (response.status !== 200) {
        console.error(`Error fetching transcription data: ${response.status}`);
        return summaryData;
      }
      
      const segments = response.data.transcription.segments;
      
      console.log("Fetched transcription data successfully");
      console.log("Number of segments with screenshots:", segments.filter((s: any) => s.screenshot_url).length);
      
      // Match summary sections with segment screenshots
      const enhancedSummaries = summaryData.map((summary: SummarySection) => {
        // Find the best matching segment for this summary
        // Strategy 1: Find a segment that's very close to the start time of the summary (within 5 seconds)
        let matchingSegment = segments.find((segment: any) => 
          Math.abs(timeToSeconds(segment.start_time) - timeToSeconds(summary.start)) < 5
        );
        
        // Strategy 2: If no exact match found, try to find a segment that's contained within the summary time range
        if (!matchingSegment) {
          const summaryStartTime = timeToSeconds(summary.start);
          const summaryEndTime = timeToSeconds(summary.end);
          
          matchingSegment = segments.find((segment: any) => {
            const segmentTime = timeToSeconds(segment.start_time);
            return segmentTime >= summaryStartTime && segmentTime <= summaryEndTime;
          });
        }
        
        // Strategy 3: If still no match, just take the closest segment
        if (!matchingSegment) {
          let closestSegment = segments[0];
          let closestDiff = Math.abs(timeToSeconds(segments[0].start_time) - timeToSeconds(summary.start));
          
          for (const segment of segments) {
            const diff = Math.abs(timeToSeconds(segment.start_time) - timeToSeconds(summary.start));
            if (diff < closestDiff) {
              closestDiff = diff;
              closestSegment = segment;
            }
          }
          
          matchingSegment = closestSegment;
        }
        
        return {
          ...summary,
          screenshot_url: matchingSegment?.screenshot_url || null
        };
      });
      
      return enhancedSummaries;
    } catch (error) {
      console.error('Error getting screenshots for summaries:', error);
      return summaryData; // Return original data if something fails
    }
  };

  // Add the timeToSeconds function that was missing
  const timeToSeconds = (timeStr: string): number => {
    try {
      // Handle different time formats: HH:MM:SS or HH:MM:SS.mmm
      const parts = timeStr.split(':');
      if (parts.length !== 3) {
        console.error(`Invalid time format: ${timeStr}`);
        return 0;
      }
      
      const hours = parseInt(parts[0], 10);
      const minutes = parseInt(parts[1], 10);
      // Handle seconds with milliseconds
      const seconds = parseFloat(parts[2]);
      
      return hours * 3600 + minutes * 60 + seconds;
    } catch (error) {
      console.error(`Error converting time ${timeStr} to seconds:`, error);
      return 0;
    }
  };

  // Language options (ISO 639-1 codes)
  const languageOptions = [
    { value: '', label: 'Auto-detect Language' },
    { value: 'en', label: 'English' },
    { value: 'es', label: 'Spanish' },
    { value: 'fr', label: 'French' },
    { value: 'de', label: 'German' },
    { value: 'it', label: 'Italian' },
    { value: 'ja', label: 'Japanese' },
    { value: 'ko', label: 'Korean' },
    { value: 'pt', label: 'Portuguese' },
    { value: 'ru', label: 'Russian' },
    { value: 'zh', label: 'Chinese' },
    // Add more languages as needed
  ];

  // Function to open the modal
  const openImageModal = (imageUrl: string | undefined) => {
    if (imageUrl) {
      setModalImageUrl(imageUrl);
      setIsModalOpen(true);
    }
  };

  // Add this after the useEffect hooks
  useEffect(() => {
    if (videoRef) {
      // Add seeking event listeners
      const handleSeeking = () => {
        setIsVideoSeeking(true);
      };

      const handleSeeked = () => {
        setIsVideoSeeking(false);
        // Update active segment based on current time
        if (transcription?.transcription.segments) {
          const currentTime = videoRef.currentTime;
          const segments = transcription.transcription.segments;
          const matchingSegment = segments.find(segment => {
            const segmentStartSeconds = timeToSeconds(segment.start_time);
            const segmentEndSeconds = timeToSeconds(segment.end_time);
            return currentTime >= segmentStartSeconds && currentTime <= segmentEndSeconds;
          });
          
          if (matchingSegment) {
            setActiveSegmentId(matchingSegment.id);
            // Scroll to the active segment
            const segmentElement = document.getElementById(`transcript-segment-${matchingSegment.id}`);
            if (segmentElement) {
              const transcriptContainer = document.querySelector('.flex-grow.overflow-auto');
              if (transcriptContainer) {
                const containerRect = transcriptContainer.getBoundingClientRect();
                const elementRect = segmentElement.getBoundingClientRect();
                const relativeTop = elementRect.top - containerRect.top;
                
                transcriptContainer.scrollTo({
                  top: transcriptContainer.scrollTop + relativeTop - 100,
                  behavior: 'smooth'
                });
              }
            }
          }
        }
      };

      videoRef.addEventListener('seeking', handleSeeking);
      videoRef.addEventListener('seeked', handleSeeked);

      return () => {
        videoRef.removeEventListener('seeking', handleSeeking);
        videoRef.removeEventListener('seeked', handleSeeked);
      };
    }
  }, [videoRef, transcription]);

  return (
    <div className="h-full text-gray-900">
      {/* Upload Section */}
      {!transcription && (
        <div className="mx-auto max-w-4xl">
          <div className="bg-white rounded-xl shadow-md overflow-hidden">
            <div className="p-5">
              <div className="text-center mb-4">
                <h2 className="text-xl font-bold text-gray-900 mb-1">
                  Upload Your File
                </h2>
                <p className="text-xs text-gray-600 max-w-lg mx-auto">
                  Upload your video or audio file and our AI will transcribe it with timestamps.
                  <br />
                  <span className="text-2xs text-teal-600">
                    Now supports large video files - we'll automatically extract the audio!
                  </span>
                </p>
              </div>
            
              <div 
                className={`
                  relative flex flex-col items-center justify-center
                  w-full max-w-lg mx-auto h-48 border-2 border-dashed rounded-lg
                  transition-all duration-300 ease-in-out
                  ${dragActive 
                    ? 'border-teal-500 bg-teal-50' 
                    : 'border-gray-300 bg-white hover:bg-teal-50 hover:border-teal-300'
                  }
                  ${transcribeMutation.isPending ? 'opacity-70 pointer-events-none' : ''}
                `}
                onDragEnter={handleDrag}
                onDragLeave={handleDrag}
                onDragOver={handleDrag}
                onDrop={handleDrop}
                onClick={handleButtonClick}
              >
                <div className="flex flex-col items-center justify-center pt-3 pb-4 px-4 text-center">
                  <div className="mb-2">
                    <svg
                      className={`w-10 h-10 ${dragActive ? 'text-teal-500' : 'text-teal-400'}`}
                      fill="none"
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                      strokeWidth="1.5"
                    >
                      <path d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                    </svg>
                  </div>
                  <h3 className="text-base font-medium text-gray-700">
                    {dragActive ? "Drop to upload" : "Drag & drop your file here"}
                  </h3>
                  <p className="text-2xs text-gray-500">
                    or click to browse files
                  </p>
                  <p className="text-2xs text-gray-400 mt-1">
                    Supports MP4, MP3, WAV files up to 10GB
                  </p>
                </div>
                <input
                  ref={fileInputRef}
                  type="file"
                  className="hidden"
                  accept="video/*,audio/*"
                  onChange={handleFileChange}
                  disabled={transcribeMutation.isPending}
                />
              </div>

              {/* Show selected file info if a file is staged */}
              {file && !transcription && (
                <div className="mt-4 max-w-lg mx-auto text-center p-3 bg-gray-50 rounded border border-gray-200">
                  <p className="text-sm font-medium text-gray-700">Selected file:</p>
                  <p className="text-xs text-gray-600 truncate">{file.name} ({(file.size / (1024 * 1024)).toFixed(2)} MB)</p>
                </div>
              )}

              {/* --> Add Language Selection Here <-- */}
              <div className="mt-4 max-w-lg mx-auto">
                <label htmlFor="language-select" className="block text-sm font-medium text-gray-700 mb-1">
                  Source Language (Optional)
                </label>
                <select 
                  id="language-select"
                  value={selectedLanguage}
                  onChange={handleLanguageChange}
                  disabled={transcribeMutation.isPending} // Disable when processing
                  className={`mt-1 block w-full pl-3 pr-10 py-2 text-base border-gray-300 focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm rounded-md shadow-sm ${transcribeMutation.isPending ? 'bg-gray-100 cursor-not-allowed' : ''}`}
                >
                  {languageOptions.map(option => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
                <p className="mt-1 text-xs text-gray-500">
                  Select the primary language spoken in the file. Leave as 'Auto-detect' if unsure.
                </p>
              </div>
              {/* --- End Language Selection --- */}

              {/* Add Start Transcription Button - visible only when a file is selected and not processing */}            
              {file && !transcribeMutation.isPending && !transcription && (
                  <div className="mt-6 max-w-lg mx-auto text-center">
                      <button 
                          onClick={handleStartTranscriptionClick}
                          className="px-6 py-3 bg-gradient-to-r from-teal-500 to-cyan-500 text-white font-semibold rounded-lg shadow-md hover:from-teal-600 hover:to-cyan-600 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-teal-500 transition duration-300 ease-in-out"
                      >
                          Start Transcription
                      </button>
                      
                      {/* Move transcription method toggle here */}
                      <div className="mt-4">
                        <label className="block text-sm font-medium text-gray-700 mb-2">
                          Transcription Method
                        </label>
                        <div className="flex justify-center space-x-4">
                          <label className="inline-flex items-center">
                            <input
                              type="radio"
                              className="form-radio"
                              name="transcriptionMethod"
                              value="local"
                              checked={transcriptionMethod === 'local'}
                              onChange={(e) => setTranscriptionMethod(e.target.value as TranscriptionMethod)}
                            />
                            <span className="ml-2">Local (Faster, Free)</span>
                          </label>
                          <label className="inline-flex items-center">
                            <input
                              type="radio"
                              className="form-radio"
                              name="transcriptionMethod"
                              value="openai"
                              checked={transcriptionMethod === 'openai'}
                              onChange={(e) => setTranscriptionMethod(e.target.value as TranscriptionMethod)}
                            />
                            <span className="ml-2">OpenAI (More Accurate)</span>
                          </label>
                        </div>
                      </div>
                  </div>
              )}

              {/* Load Saved Button */}
              <div className="mt-3 text-center">
                <button
                  onClick={handleSavedTranscriptionsClick}
                  className="text-sm text-blue-600 hover:text-blue-800 font-medium flex items-center justify-center mx-auto"
                  disabled={transcribeMutation.isPending}
                >
                  <svg className="w-4 h-4 mr-1" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M19 14l-7 7m0 0l-7-7m7 7V3"></path>
                  </svg>
                  {showSavedTranscriptions ? 'Hide Saved' : 'Load Saved Transcription'}
                </button>
              </div>

              {/* Saved Transcriptions Panel */}
              {showSavedTranscriptions && (
                <div className="mt-4 max-w-lg mx-auto">
                  <SavedTranscriptionsPanel onTranscriptionLoaded={handleTranscriptionLoaded} />
                </div>
              )}

              {/* File Format Info */}
              <div className="mt-4 flex justify-center gap-3">
                <div className="flex items-center space-x-1 text-gray-600">
                  <svg className="w-3 h-3 text-teal-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <circle cx="12" cy="12" r="10"></circle>
                    <polyline points="12 6 12 12 16 14"></polyline>
                  </svg>
                  <span className="text-2xs">Quick Processing</span>
                </div>
                <div className="flex items-center space-x-1 text-gray-600">
                  <svg className="w-3 h-3 text-teal-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path>
                  </svg>
                  <span className="text-2xs">Secure Upload</span>
                </div>
                <div className="flex items-center space-x-1 text-gray-600">
                  <svg className="w-3 h-3 text-teal-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M22 12h-4l-3 9L9 3l-3 9H2"></path>
                  </svg>
                  <span className="text-2xs">High Accuracy</span>
                </div>
              </div>

              {/* Processing Status - Keep only this one */}
              {!isNewTranscription && processingStatus && (
                <div className="w-full max-w-lg mx-auto mt-6 p-4 rounded-lg border border-gray-100">
                  <div className="flex justify-between items-center mb-2">
                    <span className="text-sm font-medium text-teal-700 flex items-center">
                      {processingStatus.stage === 'extracting' ? (
                        <>
                          <svg className="animate-spin -ml-1 mr-2 h-3 w-3 text-teal-500" fill="none" viewBox="0 0 24 24">
                            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                          </svg>
                          Extracting audio...
                        </>
                      ) : processingStatus.stage === 'transcribing' ? (
                        <>
                          <svg className="animate-spin -ml-1 mr-2 h-3 w-3 text-teal-500" fill="none" viewBox="0 0 24 24">
                            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                          </svg>
                          Transcribing audio...
                        </>
                      ) : (
                        'Processing...'
                      )}
                    </span>
                    <span className="text-xs font-medium text-teal-700">
                      {processingStatus.stage === 'extracting' ? (
                        'Step 1 of 3'
                      ) : processingStatus.stage === 'transcribing' ? (
                        'Step 2 of 3'
                      ) : processingStatus.stage === 'complete' ? (
                        'Step 3 of 3'
                      ) : (
                        `${processingStatus.progress}%`
                      )}
                    </span>
                  </div>
                  <div className="h-1.5 w-full bg-gray-200 rounded-full overflow-hidden">
                    {processingStatus.stage === 'extracting' ? (
                      <div className="h-full w-full bg-teal-400 rounded-full animate-pulse opacity-60"></div>
                    ) : (
                      <div
                        className="h-full bg-gradient-to-r from-teal-400 to-cyan-500 rounded-full transition-all duration-300"
                        style={{ width: `${processingStatus.progress}%` }}
                      />
                    )}
                  </div>
                  <div className="mt-2 flex justify-between text-2xs text-gray-500">
                    <p className="text-center">
                      {processingStatus.stage === 'extracting'
                        ? 'Extracting audio from video file. This may take several minutes depending on file size...'
                        : processingStatus.stage === 'transcribing'
                        ? 'Converting speech to text...'
                        : 'Processing your file...'}
                    </p>
                    <p className="text-right font-medium">
                      {elapsedTime > 0 && `Time elapsed: ${formatProcessingTime(elapsedTime.toString())}`}
                    </p>
                  </div>
                </div>
              )}
            </div>
          </div>
          
          {/* Features Cards */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-8">
            <div className="bg-white p-5 rounded-lg shadow-sm border border-gray-100">
              <div className="flex items-center mb-3">
                <div className="w-8 h-8 rounded-full bg-teal-100 flex items-center justify-center mr-3">
                  <svg className="w-4 h-4 text-teal-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"></path>
                    <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"></path>
                  </svg>
                </div>
                <h3 className="text-sm font-medium text-gray-900">Accurate Transcription</h3>
              </div>
              <p className="text-xs text-gray-600">Our AI model is trained on diverse speech patterns for high accuracy.</p>
            </div>
            
            <div className="bg-white p-5 rounded-lg shadow-sm border border-gray-100">
              <div className="flex items-center mb-3">
                <div className="w-8 h-8 rounded-full bg-teal-100 flex items-center justify-center mr-3">
                  <svg className="w-4 h-4 text-teal-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M8 3v3a2 2 0 01-2 2H3m18 0h-3a2 2 0 01-2-2V3m0 18v-3a2 2 0 012-2h3M3 16h3a2 2 0 012 2v3"></path>
                  </svg>
                </div>
                <h3 className="text-sm font-medium text-gray-900">Subtitle Export</h3>
              </div>
              <p className="text-xs text-gray-600">Export to SRT, VTT, and other formats compatible with video platforms.</p>
            </div>
            
            <div className="bg-white p-5 rounded-lg shadow-sm border border-gray-100">
              <div className="flex items-center mb-3">
                <div className="w-8 h-8 rounded-full bg-teal-100 flex items-center justify-center mr-3">
                  <svg className="w-4 h-4 text-teal-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M3 18v-6a9 9 0 0118 0v6"></path>
                    <path d="M21 19a2 2 0 01-2 2h-1a2 2 0 01-2-2v-3a2 2 0 012-2h3zM3 19a2 2 0 002 2h1a2 2 0 002-2v-3a2 2 0 00-2-2H3z"></path>
                  </svg>
                </div>
                <h3 className="text-sm font-medium text-gray-900">Multi-language Support</h3>
              </div>
              <p className="text-xs text-gray-600">Automatic language detection with support for over 30 languages.</p>
            </div>
          </div>
        </div>
      )}

      {/* Results Section */}
      {transcription && (
        <div className="space-y-6 h-screen flex flex-col overflow-hidden w-full">
          <div className="bg-white rounded-lg p-5 shadow-sm border border-gray-100 flex-shrink-0">
            <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
              <div>
                <div className="flex items-center">
                  <div className="w-8 h-8 rounded-full bg-teal-100 flex items-center justify-center mr-3">
                    <svg className="w-4 h-4 text-teal-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M22 11.08V12a10 10 0 11-5.93-9.14"></path>
                      <polyline points="22 4 12 14.01 9 11.01"></polyline>
                    </svg>
                  </div>
                  <h2 className="text-lg font-semibold text-gray-900">
                    Transcription Complete
                  </h2>
                </div>
                <div className="mt-2 ml-11 grid grid-cols-2 gap-x-4 gap-y-1">
                  <div className="text-xs text-gray-500">
                    <span className="font-medium text-gray-700">File:</span> {transcription.filename}
                  </div>
                  <div className="text-xs text-gray-500">
                    <span className="font-medium text-gray-700">Duration:</span> {transcription.transcription.duration}
                  </div>
                  <div className="text-xs text-gray-500">
                    <span className="font-medium text-gray-700">Language:</span> {transcription.transcription.language}
                  </div>
                  <div className="text-xs text-gray-500">
                    <span className="font-medium text-gray-700">Processing Time:</span> 
                    <span className="ml-1 px-1.5 py-0.5 bg-teal-50 text-teal-700 rounded-md font-medium">
                      {formatProcessingTime(transcription.transcription.processing_time)}
                    </span>
                  </div>
                </div>
              </div>
              
              <div className="flex items-center gap-3">
                <button 
                  onClick={handleSearchClick}
                  className={`px-4 py-2 ${showSearch ? 'bg-blue-600' : 'bg-blue-500'} text-white text-sm rounded-lg hover:bg-blue-600 shadow-sm hover:shadow focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 flex items-center space-x-1`}
                >
                  <svg className="w-4 h-4 mr-1" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                  </svg>
                  <span>{showSearch ? 'Hide Search' : 'Show Search'}</span>
                </button>
                
                <button 
                  onClick={startNewTranscription}
                  className="px-4 py-2 bg-gradient-to-r from-teal-500 to-cyan-500 text-white text-sm rounded-lg hover:from-teal-600 hover:to-cyan-600 shadow-sm hover:shadow focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-teal-500 flex items-center"
                >
                  <svg className="w-4 h-4 mr-2" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <polyline points="23 4 23 10 17 10"></polyline>
                    <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path>
                  </svg>
                  New Transcription
                </button>
                <SubtitleControls filename={transcription.filename} />
              </div>
            </div>
          </div>

          {/* New Three-Column Layout */}
          <div className="flex flex-col lg:flex-row flex-grow overflow-hidden w-full">
            {/* Main Column: Video and Transcript/Summary */}
            <div className={`flex-grow flex flex-col overflow-hidden ${
              showSearch 
                ? 'lg:w-3/4' 
                : 'lg:w-full'
            }`}>
              {/* Video Player (Top) */}
              {videoUrl && (
                <div className="bg-white rounded-lg shadow-sm border border-gray-100 overflow-hidden flex-shrink-0 mb-4">
                  <div className="px-5 py-3 border-b border-gray-200 flex justify-between items-center">
                    <h3 className="text-sm font-medium text-gray-800">Video</h3>
                    <div className="flex items-center space-x-2">
                      <button 
                        onClick={toggleSubtitles}
                        className={`px-3 py-1 text-xs rounded-md flex items-center gap-1 ${
                          showSubtitles 
                            ? 'bg-teal-100 text-teal-700' 
                            : 'bg-gray-100 text-gray-700'
                        }`}
                      >
                        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 8h10M7 12h4m1 8l-4-4H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-3l-4 4z" />
                        </svg>
                        {showSubtitles ? 'Subtitles On' : 'Subtitles Off'}
                      </button>
                      {showSubtitles && (
                        <button 
                          onClick={() => setShowTranslation(!showTranslation)}
                          className="px-2 py-1 rounded-full text-xs font-medium bg-teal-50 text-teal-700 hover:bg-teal-100 transition-colors duration-200 flex items-center gap-1"
                        >
                          {showTranslation ? 'ENGLISH' : transcription?.transcription.language.toUpperCase()}
                          <svg className="w-3 h-3 ml-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16V4m0 0L3 8m4-4l4 4m6 0v12m0 0l4-4m-4 4l-4-4" />
                          </svg>
                        </button>
                      )}
                    </div>
                  </div>
                  <div className="w-full bg-black flex justify-center">
                    <video
                      ref={setVideoRef}
                      src={videoUrl}
                      controls
                      className="w-full max-h-[50vh] object-contain"
                      onTimeUpdate={() => {
                        if (!isVideoSeeking && videoRef) {
                          const currentTime = videoRef.currentTime;
                          // Update active segment based on current time
                          if (transcription?.transcription.segments) {
                            const segments = transcription.transcription.segments;
                            const matchingSegment = segments.find(segment => {
                              const segmentStartSeconds = timeToSeconds(segment.start_time);
                              const segmentEndSeconds = timeToSeconds(segment.end_time);
                              return currentTime >= segmentStartSeconds && currentTime <= segmentEndSeconds;
                            });
                            
                            if (matchingSegment) {
                              setActiveSegmentId(matchingSegment.id);
                            }
                          }
                        }
                      }}
                    >
                      {subtitleTrackUrl && (
                        <track 
                          src={subtitleTrackUrl} 
                          kind="subtitles" 
                          srcLang={transcription?.transcription.language || 'en'} 
                          label={transcription?.transcription.language?.toUpperCase() || 'Original'} 
                          default={showSubtitles && !showTranslation}
                        />
                      )}
                      {translatedSubtitleUrl && (
                        <track 
                          src={translatedSubtitleUrl} 
                          kind="subtitles" 
                          srcLang="en" 
                          label="ENGLISH" 
                          default={showSubtitles && showTranslation}
                        />
                      )}
                    </video>
                  </div>
                </div>
              )}
              
              {/* Tabs for Transcript and Summary */}
              <div className="bg-white rounded-lg shadow-sm border border-gray-100 overflow-hidden flex-grow flex flex-col">
                <div className="flex border-b border-gray-200 sticky top-0 bg-white z-10">
                  <button
                    onClick={() => setShowSummary(false)}
                    className={`px-5 py-3 text-sm font-medium ${!showSummary ? 'text-teal-600 border-b-2 border-teal-500' : 'text-gray-500 hover:text-gray-700'}`}
                  >
                    Transcript
                  </button>
                  <button
                    onClick={() => setShowSummary(true)}
                    className={`px-5 py-3 text-sm font-medium ${showSummary ? 'text-teal-600 border-b-2 border-teal-500' : 'text-gray-500 hover:text-gray-700'}`}
                  >
                    Summary
                  </button>
                </div>
                
                <div className="flex-grow overflow-auto">
                  {!showSummary && (
                    <div className="h-full">
                      {/* Transcript content */}
                      <div className="px-5 py-3 border-b border-gray-200 flex justify-between items-center">
                        <div className="flex items-center space-x-2">
                          <button
                            onClick={() => setShowTranslation(!showTranslation)}
                            className={`px-2 py-1 rounded text-xs 
                              ${showTranslation ? 'bg-blue-100 text-blue-700' : 'bg-gray-100 text-gray-600'}`}
                          >
                            {showTranslation ? 'Show Original' : 'Show Translation'}
                          </button>
                        </div>
                      </div>
                      <div className="p-4 space-y-2">
                        {transcription.transcription.segments.map((segment, index) => (
                          <div 
                            key={segment.id}
                            id={`transcript-segment-${segment.id}`}
                            className={`py-2 border-b border-gray-100 last:border-0 transition-colors duration-200 ${
                              activeSegmentId === segment.id ? 'bg-teal-50' : ''
                            }`}
                          >
                            <div className="flex items-start gap-4">
                              {segment.screenshot_url && (
                                <div className="flex-shrink-0">
                                  <img 
                                    src={`http://localhost:8000${segment.screenshot_url}`}
                                    alt={`Screenshot at ${segment.start_time}`}
                                    className="w-40 rounded-md shadow-sm hover:shadow-md transition-shadow hover:scale-105 cursor-pointer"
                                    onClick={() => openImageModal(`http://localhost:8000${segment.screenshot_url}`)}
                                  />
                                </div>
                              )}
                              <div className="flex-grow">
                                <div 
                                  className="flex items-center mb-1 text-xs text-teal-600 font-medium cursor-pointer hover:underline"
                                  onClick={() => seekToTimestamp(segment.start_time)}
                                >
                                  <svg className="w-3 h-3 mr-1" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                    <circle cx="12" cy="12" r="10"></circle>
                                    <polyline points="12 6 12 12 16 14"></polyline>
                                  </svg>
                                  {segment.start_time} - {segment.end_time}
                                  <span className="ml-auto px-2 py-0.5 rounded-full text-2xs bg-teal-50">Speaker 1</span>
                                </div>
                                <p className={`text-gray-800 ${activeSegmentId === segment.id ? 'font-medium' : ''}`}>
                                  {showTranslation && segment.translation ? segment.translation : segment.text}
                                </p>
                                {/* Show both when a translation is available */}
                                {showTranslation && segment.translation && segment.translation !== segment.text && (
                                  <p className="text-xs text-gray-500 mt-1 italic">
                                    Original: {segment.text}
                                  </p>
                                )}
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  
                  {/* Summary Panel */}
                  {showSummary && (
                    <div className="h-full">
                      <SummaryPanel 
                        isVisible={showSummary}
                        onSeekTo={seekToTimestamp}
                        summaries={summaries}
                        setSummaries={setSummaries}
                        loading={summaryLoading}
                        generateSummaries={generateSummaries}
                      />
                    </div>
                  )}
                </div>
              </div>
            </div>
            
            {/* Right Column: Search & Analysis Panels */}
            {showSearch && (
              <div className="w-full lg:w-1/4 lg:min-w-[250px] overflow-y-auto bg-white rounded-lg shadow-sm border border-gray-100 mt-4 lg:mt-0 lg:ml-4">
                <div className="sticky top-0 bg-white z-10 border-b border-gray-200">
                  <div className="px-4 py-3 flex items-center justify-between">
                    <h3 className="text-sm font-medium text-gray-800">Search & Analysis</h3>
                  </div>
                </div>
                
                <div className="p-4 overflow-y-auto h-full">
                  <SearchPanel onSeekToTimestamp={seekToTimestamp} />
                  <div className="mt-4">
                    <AnalyticsPanel onSeekToTimestamp={seekToTimestamp} />
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Error Display */}
      {error && (
        <div className="mt-6 bg-red-50 border-l-4 border-red-400 p-4 rounded-md w-full">
          <div className="flex">
            <div className="flex-shrink-0">
              <svg className="h-5 w-5 text-red-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="10"></circle>
                <line x1="12" y1="8" x2="12" y2="12"></line>
                <line x1="12" y1="16" x2="12.01" y2="16"></line>
              </svg>
            </div>
            <div className="ml-3">
              <h3 className="text-sm font-medium text-red-800">Transcription Failed</h3>
              <p className="mt-1 text-xs text-red-700">
                {error}
              </p>
              <div className="mt-2">
                <button 
                  onClick={() => transcribeMutation.reset()}
                  className="text-xs font-medium text-red-700 hover:text-red-600 focus:outline-none"
                >
                  Try again
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Image Modal */} 
      {isModalOpen && modalImageUrl && (
        <ImageModal 
          imageUrl={modalImageUrl} 
          onClose={() => setIsModalOpen(false)} 
        />
      )}
    </div>
  );
}; 