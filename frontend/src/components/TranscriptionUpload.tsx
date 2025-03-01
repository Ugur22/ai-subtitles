import { useState, useRef } from 'react';
import axios from 'axios';
import SummaryPanel from './SummaryPanel';

const TranscriptionUpload = () => {
  const [file, setFile] = useState<File | null>(null);
  const [progress, setProgress] = useState(0);
  const [transcriptionData, setTranscriptionData] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [showTranslation, setShowTranslation] = useState(false);
  const [showSummary, setShowSummary] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true);
    } else if (e.type === 'dragleave') {
      setDragActive(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      const file = e.dataTransfer.files[0];
      handleFile(file);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      handleFile(e.target.files[0]);
    }
  };

  const handleFile = async (file: File) => {
    setFile(file);
    setError(null);
    
    const formData = new FormData();
    formData.append('file', file);
    
    try {
      setIsUploading(true);
      
      const response = await axios.post('http://localhost:8000/transcribe/', formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
        onUploadProgress: (progressEvent) => {
          const percentage = Math.round((progressEvent.loaded * 100) / (progressEvent.total || 1));
          setProgress(percentage);
        },
      });
      
      setIsUploading(false);
      setIsTranscribing(true);
      
      // Poll for transcription results
      pollTranscriptionStatus(response.data.task_id);
    } catch (error) {
      setIsUploading(false);
      setIsTranscribing(false);
      console.error('Upload error:', error);
      setError('Failed to upload file. Please try again.');
    }
  };

  const pollTranscriptionStatus = async (taskId: string) => {
    try {
      const response = await axios.get(`http://localhost:8000/transcription_status/?task_id=${taskId}`);
      
      if (response.data.status === 'completed') {
        setTranscriptionData(response.data);
        setIsTranscribing(false);
      } else if (response.data.status === 'failed') {
        setError('Transcription failed. Please try again.');
        setIsTranscribing(false);
      } else {
        // Continue polling
        setTimeout(() => pollTranscriptionStatus(taskId), 2000);
      }
    } catch (error) {
      console.error('Polling error:', error);
      setError('Error checking transcription status. Please try again.');
      setIsTranscribing(false);
    }
  };

  const handleButtonClick = () => {
    fileInputRef.current?.click();
  };
  
  const handleSeekToTimestamp = (timestamp: string) => {
    // This function will be used when we add a video player
    console.log(`Seeking to timestamp: ${timestamp}`);
  };

  const resetTranscription = () => {
    setFile(null);
    setProgress(0);
    setTranscriptionData(null);
    setError(null);
    setIsUploading(false);
    setIsTranscribing(false);
    setShowTranslation(false);
    setShowSummary(false);
  };

  return (
    <div className="container mx-auto p-4">
      {!transcriptionData && !isTranscribing && !isUploading && (
        <div className="max-w-2xl mx-auto mt-8">
          <div className="bg-white rounded-lg shadow-md p-6">
            <h2 className="text-2xl font-bold text-center mb-6">Upload Audio or Video File</h2>
            
            <div 
              className={`
                border-2 border-dashed rounded-lg p-8 text-center
                ${dragActive ? 'border-teal-400 bg-teal-50' : 'border-gray-300 hover:border-teal-400 hover:bg-teal-50'}
                transition-all duration-200 ease-in-out
                cursor-pointer
              `}
              onDragEnter={handleDrag}
              onDragLeave={handleDrag}
              onDragOver={handleDrag}
              onDrop={handleDrop}
              onClick={handleButtonClick}
            >
              <input
                ref={fileInputRef}
                type="file"
                className="hidden"
                accept="video/*,audio/*"
                onChange={handleFileChange}
              />
              
              <div className="flex flex-col items-center">
                <svg className="w-12 h-12 text-teal-500 mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                </svg>
                
                <h3 className="text-lg font-medium text-gray-700 mb-1">
                  {dragActive ? 'Drop the file here' : 'Drag and drop your file here'}
                </h3>
                <p className="text-sm text-gray-500 mb-2">or click to browse files</p>
                <p className="text-xs text-gray-400">Supports MP4, MP3, WAV files up to 5GB</p>
              </div>
            </div>
          </div>
        </div>
      )}
      
      {(isUploading || isTranscribing) && (
        <div className="max-w-2xl mx-auto mt-8">
          <div className="bg-white rounded-lg shadow-md p-6">
            <h2 className="text-xl font-bold text-center mb-6">
              {isUploading ? 'Uploading File...' : 'Transcribing Audio...'}
            </h2>
            
            <div className="w-full bg-gray-200 rounded-full h-2.5 mb-2">
              <div 
                className="bg-teal-500 h-2.5 rounded-full transition-all duration-300" 
                style={{ width: `${isUploading ? progress : 100}%` }}
              ></div>
            </div>
            
            <div className="text-center text-sm text-gray-500 mt-2">
              {isUploading ? `${progress}% Uploaded` : 'Extracting speech to text...'}
            </div>
            
            <p className="text-center text-xs text-gray-400 mt-4">
              {isUploading ? 'Please wait while we upload your file' : 'This might take a minute depending on the file size'}
            </p>
          </div>
        </div>
      )}
      
      {error && (
        <div className="max-w-2xl mx-auto mt-8">
          <div className="bg-red-50 border-l-4 border-red-500 p-4 rounded">
            <div className="flex">
              <div className="flex-shrink-0">
                <svg className="h-5 w-5 text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                </svg>
              </div>
              <div className="ml-3">
                <p className="text-sm text-red-700">{error}</p>
                <div className="mt-2">
                  <button
                    onClick={resetTranscription}
                    className="text-xs font-medium text-red-700 hover:text-red-600"
                  >
                    Try Again
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
      
      {transcriptionData && (
        <div className="mt-8">
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-2xl font-bold text-gray-800">Transcription Results</h2>
            <div className="flex space-x-4">
              {transcriptionData.transcription.translation && (
                <button
                  onClick={() => setShowTranslation(!showTranslation)}
                  className={`px-4 py-2 rounded text-sm font-medium ${
                    showTranslation 
                      ? 'bg-teal-500 text-white' 
                      : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                  }`}
                >
                  {showTranslation ? 'Show Original' : 'Show Translation'}
                </button>
              )}
              <button
                onClick={() => setShowSummary(!showSummary)}
                className={`px-4 py-2 rounded text-sm font-medium ${
                  showSummary 
                    ? 'bg-teal-500 text-white' 
                    : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                }`}
              >
                {showSummary ? 'Hide Summary' : 'Show Summary'}
              </button>
              <button
                onClick={resetTranscription}
                className="px-4 py-2 bg-teal-500 text-white rounded text-sm font-medium hover:bg-teal-600 transition-colors"
              >
                Start New Transcription
              </button>
            </div>
          </div>

          <div className="flex flex-col md:flex-row gap-6">
            <div className={`${showSummary ? 'md:w-2/3' : 'w-full'}`}>
              <div className="bg-white rounded-lg shadow-sm p-6 border border-gray-100">
                <div className="flex justify-between items-center mb-4">
                  <h3 className="text-lg font-medium text-gray-800">
                    {transcriptionData.transcription.language} 
                    {showTranslation && transcriptionData.transcription.translation && ' → English'}
                  </h3>
                </div>
                
                <div className="space-y-4">
                  {transcriptionData.transcription.segments.map((segment: any, index: number) => (
                    <div key={index} className="pb-4 border-b border-gray-100 last:border-0">
                      <div className="flex justify-between items-start mb-1">
                        <span className="text-xs text-teal-600 font-medium">
                          {segment.start_time}
                        </span>
                      </div>
                      <p className="text-gray-700">
                        {showTranslation && segment.translation ? segment.translation : segment.text}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            </div>
            
            {showSummary && (
              <div className="md:w-1/3">
                <SummaryPanel 
                  isVisible={showSummary} 
                  onSeekTo={handleSeekToTimestamp}
                />
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default TranscriptionUpload; 