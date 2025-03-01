import { useState, useRef, useEffect } from 'react';
import { useMutation } from '@tanstack/react-query';
import { transcribeVideo, TranscriptionResponse } from '../../../services/api';
import { SubtitleControls } from './SubtitleControls';
import { SearchPanel } from '../search/SearchPanel';
import { AnalyticsPanel } from '../analytics/AnalyticsPanel';
import ReactPlayer from 'react-player';
import { SummaryPanel } from '../summary/SummaryPanel';
import { extractAudio, getAudioDuration, initFFmpeg } from '../../../utils/ffmpeg';

interface ProcessingStatus {
  stage: 'uploading' | 'extracting' | 'transcribing' | 'complete';
  progress: number;
}

export const TranscriptionUpload = () => {
  const [uploadProgress, setUploadProgress] = useState(0);
  const [transcription, setTranscription] = useState<TranscriptionResponse | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [showTranslation, setShowTranslation] = useState(false);
  const [showSummary, setShowSummary] = useState(false);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [processingStatus, setProcessingStatus] = useState<ProcessingStatus>({
    stage: 'uploading',
    progress: 0
  });
  const fileInputRef = useRef<HTMLInputElement>(null);
  const playerRef = useRef<any>(null);

  const transcribeMutation = useMutation({
    mutationFn: transcribeVideo,
    onSuccess: (data) => {
      setTranscription(data);
      setProcessingStatus({ stage: 'complete', progress: 100 });
      setError(null);
    },
    onError: (error) => {
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

  const handleFileChange = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    setError(null);
    try {
      // Create and store video URL for local playback
      const objectUrl = URL.createObjectURL(file);
      setVideoUrl(objectUrl);
      
      // Start processing
      await processFile(file);
    } catch (error) {
      console.error('Processing failed:', error);
      setError('Failed to process the file. Please try again.');
      setProcessingStatus({ stage: 'uploading', progress: 0 });
    }
  };

  const processFile = async (file: File) => {
    try {
      setProcessingStatus({ stage: 'extracting', progress: 0 });
      
      // Upload file directly to backend
      transcribeMutation.mutate(file);
      
    } catch (error) {
      console.error('File processing failed:', error);
      setError('Failed to process the file. Please try again.');
      throw error;
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
      const file = e.dataTransfer.files[0];
      
      // Create and store video URL for dropped file
      if (file.type.includes('video')) {
        const objectUrl = URL.createObjectURL(file);
        setVideoUrl(objectUrl);
      } else {
        setVideoUrl(null);
      }
      
      try {
        await processFile(file);
      } catch (error) {
        console.error('Processing failed:', error);
      }
    }
  };

  const handleButtonClick = () => {
    fileInputRef.current?.click();
  };

  const startNewTranscription = () => {
    setTranscription(null);
    setShowTranslation(false);
    
    // Clean up video URL
    if (videoUrl) {
      URL.revokeObjectURL(videoUrl);
      setVideoUrl(null);
    }
  };

  // Function to seek to a specific timestamp in the video
  const seekToTimestamp = (timeString: string) => {
    if (!playerRef.current) return;
    
    // Convert "00:00:10" format to seconds
    const timeParts = timeString.split(':');
    const seconds = 
      parseInt(timeParts[0]) * 3600 + 
      parseInt(timeParts[1]) * 60 + 
      parseInt(timeParts[2]);
      
    playerRef.current.seekTo(seconds);
    console.log(`Seeking to timestamp: ${timeString} (${seconds} seconds)`);
  };

  const handleSummaryClick = () => {
    setShowSummary(!showSummary);
  };

  return (
    <div className="h-full text-gray-900">
      {/* Upload Section */}
      {!transcription && (
        <div className="mx-auto max-w-4xl">
          <div className="bg-white rounded-xl shadow-md overflow-hidden">
            <div className="p-8">
              <div className="text-center mb-6">
                <h2 className="text-2xl font-bold text-gray-900 mb-2">
                  Upload Your File
                </h2>
                <p className="text-sm text-gray-600 max-w-lg mx-auto">
                  Upload your video or audio file and our AI will transcribe it with timestamps.
                  <br />
                  <span className="text-xs text-teal-600">
                    Now supports large video files - we'll automatically extract the audio!
                  </span>
                </p>
              </div>
            
              <div 
                className={`
                  relative flex flex-col items-center justify-center
                  w-full max-w-lg mx-auto h-64 border-2 border-dashed rounded-lg
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
                <div className="flex flex-col items-center justify-center pt-5 pb-6 px-4 text-center">
                  <div className="mb-4">
                    <svg
                      className={`w-12 h-12 ${dragActive ? 'text-teal-500' : 'text-teal-400'}`}
                      fill="none"
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                      strokeWidth="1.5"
                    >
                      <path d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                    </svg>
                  </div>
                  <h3 className="text-lg font-medium text-gray-700">
                    {dragActive ? "Drop to upload" : "Drag & drop your file here"}
                  </h3>
                  <p className="text-xs text-gray-500 mt-1">
                    or click to browse files
                  </p>
                  <p className="text-xs text-gray-400 mt-3">
                    Supports MP4, MP3, WAV files up to 5GB
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

              {/* File Format Info */}
              <div className="mt-6 flex justify-center gap-4">
                <div className="flex items-center space-x-1 text-gray-600">
                  <svg className="w-3 h-3 text-teal-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <circle cx="12" cy="12" r="10"></circle>
                    <polyline points="12 6 12 12 16 14"></polyline>
                  </svg>
                  <span className="text-xs">Quick Processing</span>
                </div>
                <div className="flex items-center space-x-1 text-gray-600">
                  <svg className="w-3 h-3 text-teal-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path>
                  </svg>
                  <span className="text-xs">Secure Upload</span>
                </div>
                <div className="flex items-center space-x-1 text-gray-600">
                  <svg className="w-3 h-3 text-teal-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M22 12h-4l-3 9L9 3l-3 9H2"></path>
                  </svg>
                  <span className="text-xs">High Accuracy</span>
                </div>
              </div>

              {/* Processing Status */}
              {(processingStatus.stage !== 'uploading' || processingStatus.progress > 0) && (
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
                      {processingStatus.progress}%
                    </span>
                  </div>
                  <div className="h-1.5 w-full bg-gray-200 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-gradient-to-r from-teal-400 to-cyan-500 rounded-full transition-all duration-300"
                      style={{ width: `${processingStatus.progress}%` }}
                    />
                  </div>
                  <p className="mt-2 text-2xs text-center text-gray-500">
                    {processingStatus.stage === 'extracting'
                      ? 'Extracting audio from video file...'
                      : processingStatus.stage === 'transcribing'
                      ? 'Converting speech to text...'
                      : 'Processing your file...'}
                  </p>
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
        <div className="space-y-6">
          <div className="bg-white rounded-lg p-5 shadow-sm border border-gray-100">
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
                    <span className="font-medium text-gray-700">Processing Time:</span> {transcription.transcription.processing_time}
                  </div>
                </div>
              </div>
              
              <div className="flex items-center gap-3">
                <button 
                  onClick={handleSummaryClick}
                  className={`px-4 py-2 ${showSummary ? 'bg-teal-600' : 'bg-teal-500'} text-white text-sm rounded-lg hover:bg-teal-600 shadow-sm hover:shadow focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-teal-500 flex items-center`}
                >
                  {showSummary ? 'Hide Summary' : 'Show Summary'}
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

          {/* Video Player */}
          {videoUrl && (
            <div className="bg-white rounded-lg shadow-sm border border-gray-100 overflow-hidden">
              <div className="px-5 py-3 border-b border-gray-200">
                <h3 className="text-sm font-medium text-gray-800">Video</h3>
              </div>
              <div className="aspect-video w-full">
                <ReactPlayer
                  ref={playerRef}
                  url={videoUrl}
                  controls
                  width="100%"
                  height="100%"
                  config={{
                    file: {
                      attributes: {
                        controlsList: 'nodownload'
                      }
                    }
                  }}
                />
              </div>
            </div>
          )}
          
          <div className="flex flex-col md:flex-row gap-6">
            <div className={`${showSummary ? 'md:w-2/3' : 'w-full'}`}>
              <div className="bg-white rounded-lg shadow-sm border border-gray-100 overflow-hidden">
                <div className="px-5 py-3 border-b border-gray-200 flex justify-between items-center">
                  <h3 className="text-sm font-medium text-gray-800">Transcript</h3>
                  <div className="flex items-center gap-3">
                    <label className="inline-flex items-center cursor-pointer">
                      <input
                        type="checkbox"
                        checked={showTranslation}
                        onChange={() => setShowTranslation(!showTranslation)}
                        className="sr-only peer"
                      />
                      <div className="relative w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-teal-300 rounded-full peer peer-checked:after:translate-x-full rtl:peer-checked:after:-translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:start-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-teal-600"></div>
                      <span className="ms-3 text-sm font-medium">Show English Translation</span>
                    </label>
                    <span className="px-2 py-1 rounded-full text-xs font-medium bg-teal-100 text-teal-800">
                      {showTranslation ? 'ENGLISH' : transcription.transcription.language.toUpperCase()}
                    </span>
                  </div>
                </div>
                
                {/* Custom display to handle translations */}
                <div className="p-5 space-y-6">
                  {transcription.transcription.segments.map((segment) => (
                    <div key={segment.id} className="py-2 border-b border-gray-100 last:border-0">
                      <div className="flex items-start gap-4">
                        {segment.screenshot_url && (
                          <div className="flex-shrink-0">
                            <img 
                              src={`http://localhost:8000${segment.screenshot_url}`}
                              alt={`Screenshot at ${segment.start_time}`}
                              className="w-40 rounded-md shadow-sm hover:shadow-md transition-shadow"
                              onClick={() => seekToTimestamp(segment.start_time)}
                              style={{ cursor: 'pointer' }}
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
                          <p className="text-gray-800">
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
            </div>
            
            {showSummary && (
              <div className="md:w-1/3">
                <SummaryPanel 
                  isVisible={showSummary} 
                  onSeekTo={seekToTimestamp}
                />
              </div>
            )}
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <SearchPanel />
            <AnalyticsPanel />
          </div>
        </div>
      )}

      {/* Error Display */}
      {error && (
        <div className="mt-6 bg-red-50 border-l-4 border-red-400 p-4 rounded-md mx-auto max-w-4xl">
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
    </div>
  );
}; 