import React from "react";
import { match } from "ts-pattern";
import { SavedTranscriptionsPanel } from "./SavedTranscriptionsPanel";

interface ProcessingStatus {
  stage:
    | "uploading"
    | "extracting"
    | "transcribing"
    | "translating"
    | "complete";
  progress: number;
}

interface LanguageOption {
  value: string;
  label: string;
}

interface UploadZoneProps {
  file: File | null;
  dragActive: boolean;
  isTranscribing: boolean;
  fileInputRef: React.RefObject<HTMLInputElement | null>;
  handleDrag: (e: React.DragEvent) => void;
  handleDrop: (e: React.DragEvent) => void;
  handleButtonClick: () => void;
  fileUploadHandleChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  selectedLanguage: string;
  handleLanguageChange: (e: React.ChangeEvent<HTMLSelectElement>) => void;
  transcriptionMethod: string;
  setTranscriptionMethod: React.Dispatch<React.SetStateAction<"local">>;
  handleStartTranscriptionClick: () => void;
  showSavedTranscriptions: boolean;
  handleSavedTranscriptionsClick: () => void;
  handleTranscriptionLoaded: (videoHash?: string) => Promise<void>;
  openImageModal: (url: string) => void;
  isNewTranscription: boolean;
  processingStatus: ProcessingStatus | null;
  elapsedTime: number;
  languageOptions: LanguageOption[];
}

export const UploadZone: React.FC<UploadZoneProps> = React.memo(
  ({
    file,
    dragActive,
    isTranscribing,
    fileInputRef,
    handleDrag,
    handleDrop,
    handleButtonClick,
    fileUploadHandleChange,
    selectedLanguage,
    handleLanguageChange,
    transcriptionMethod,
    setTranscriptionMethod,
    handleStartTranscriptionClick,
    showSavedTranscriptions,
    handleSavedTranscriptionsClick,
    handleTranscriptionLoaded,
    openImageModal,
    isNewTranscription: _isNewTranscription,
    processingStatus: _processingStatus,
    elapsedTime: _elapsedTime,
    languageOptions,
  }) => {
    // Note: _isNewTranscription, _processingStatus, _elapsedTime are available for future use
    // Helper functions using ts-pattern for cleaner conditional logic
    const getFileIcon = (fileType: string) =>
      match(fileType)
        .when(
          (type) => type.startsWith("video/"),
          () => (
            <svg
              className="h-6 w-6 text-white"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"
              />
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
              />
            </svg>
          )
        )
        .otherwise(() => (
          <svg
            className="h-6 w-6 text-white"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M9 19V6a2 2 0 012-2h4a2 2 0 012 2v13m-6 0a2 2 0 002 2h4a2 2 0 002-2m0 0V9a2 2 0 00-2-2h-4a2 2 0 00-2 2v13"
            />
          </svg>
        ));

    return (
      <div className="mx-auto max-w-5xl">
        <div className="mb-8">
          <div className="flex items-center gap-3 mb-4">
            <div className="w-12 h-12 bg-gradient-to-br from-indigo-600 to-purple-600 rounded-xl flex items-center justify-center">
              <svg
                className="w-6 h-6 text-white"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M14.828 14.828a4 4 0 01-5.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                />
              </svg>
            </div>
            <div>
              <h1 className="text-4xl font-bold text-gray-900">AI Subs</h1>
              <p className="text-sm text-gray-500">
                Intelligent Transcription & Subtitle Generation
              </p>
            </div>
          </div>
        </div>

        <div className="bg-white rounded-2xl shadow-lg border border-gray-200 overflow-hidden">
          <div className="p-8 md:p-10">
            <div className="text-center mb-10">
              <h2 className="text-2xl md:text-3xl font-bold text-gray-900 mb-3">
                Transform Your Media Into Text
              </h2>
              <p className="text-gray-600 max-w-2xl mx-auto leading-relaxed">
                Upload a video or audio file and our advanced AI will
                automatically transcribe it with accurate timestamps.
                <br />
                <span className="inline-block mt-2 text-indigo-600 font-semibold">
                  ⚡ Supports large files • 30+ languages • Instant results
                </span>
              </p>
            </div>

            <div
              className={`
                    relative flex flex-col items-center justify-center
                    w-full max-w-2xl mx-auto h-72 border-3 border-dashed rounded-3xl
                    transition-all duration-300 ease-in-out cursor-pointer
                    ${
                      dragActive
                        ? "border-indigo-500 bg-indigo-50 shadow-xl scale-[1.02]"
                        : "border-gray-300 bg-gray-50 hover:bg-indigo-50/70 hover:border-indigo-400 hover:scale-[1.01]"
                    }
                    ${isTranscribing ? "opacity-60 pointer-events-none" : ""}
                  `}
              onDragEnter={handleDrag}
              onDragLeave={handleDrag}
              onDragOver={handleDrag}
              onDrop={handleDrop}
              onClick={handleButtonClick}
            >
              <div className="flex flex-col items-center justify-center py-8 px-8 text-center">
                <div className="mb-6">
                  <div
                    className={`w-20 h-20 rounded-2xl flex items-center justify-center mb-4 transition-all duration-300 ${
                      dragActive
                        ? "bg-gradient-to-br from-indigo-500 to-purple-600 scale-110 shadow-lg"
                        : "bg-gradient-to-br from-indigo-100 to-purple-100"
                    }`}
                  >
                    <svg
                      className={`w-10 h-10 transition-colors duration-300 ${
                        dragActive ? "text-white" : "text-indigo-600"
                      }`}
                      fill="none"
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                      strokeWidth="1.5"
                    >
                      <path d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                    </svg>
                  </div>
                </div>
                <h3 className="text-2xl font-bold text-gray-900 mb-2">
                  {dragActive ? "Release to upload" : "Drop your file here"}
                </h3>
                <p className="text-gray-600 mb-1 text-base font-medium">
                  or <span className="text-indigo-600 underline">browse</span>{" "}
                  your computer
                </p>
                <p className="text-xs text-gray-500 mt-2">
                  MP4 • MP3 • WAV • WebM • AVI • MKV and more (up to 10GB)
                </p>
              </div>
              <input
                ref={fileInputRef}
                type="file"
                className="hidden"
                accept="video/*,audio/*,.mp4,.mpeg,.mpga,.m4a,.wav,.webm,.mp3,.mov,.mkv"
                onChange={fileUploadHandleChange}
                disabled={isTranscribing}
              />
            </div>

            {/* Show selected file info if a file is staged */}
            {file && (
              <div className="mt-8 max-w-2xl mx-auto p-6 bg-gradient-to-r from-emerald-50 via-cyan-50 to-blue-50 rounded-2xl border-2 border-emerald-200 shadow-sm">
                <div className="flex items-start gap-4">
                  <div className="flex-shrink-0">
                    <div className="flex items-center justify-center h-12 w-12 rounded-xl bg-gradient-to-br from-emerald-500 to-cyan-500 shadow-md">
                      {getFileIcon(file.type)}
                    </div>
                  </div>
                  <div className="flex-grow">
                    <h4 className="text-sm font-bold text-gray-900 truncate">
                      {file.name}
                    </h4>
                    <p className="text-sm text-gray-600 mt-1">
                      📊 Size: {(file.size / (1024 * 1024)).toFixed(2)} MB
                    </p>
                    <p className="text-xs text-emerald-700 font-medium mt-2">
                      ✓ File ready to transcribe
                    </p>
                  </div>
                </div>
              </div>
            )}

            {/* Language and Method Selection */}
            <div className="mt-8 max-w-2xl mx-auto grid grid-cols-1 md:grid-cols-2 gap-6">
              {/* Language Selection */}
              <div>
                <label
                  htmlFor="language-select"
                  className="block text-sm font-semibold text-gray-900 mb-2"
                >
                  🌐 Source Language
                </label>
                <select
                  id="language-select"
                  value={selectedLanguage}
                  onChange={handleLanguageChange}
                  disabled={isTranscribing}
                  className="input-base w-full"
                >
                  {languageOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
                <p className="mt-2 text-xs text-gray-500">
                  Auto-detect if you're not sure
                </p>
              </div>

              {/* Transcription Method */}
              <div>
                <label className="block text-sm font-semibold text-gray-900 mb-2">
                  ⚡ Processing Method
                </label>
                <div className="flex items-center h-11 px-4 border-2 border-gray-300 rounded-lg bg-white hover:border-indigo-400 transition-colors">
                  <input
                    type="radio"
                    id="local-method"
                    className="w-4 h-4 accent-indigo-600 cursor-pointer"
                    name="transcriptionMethod"
                    value="local"
                    checked={transcriptionMethod === "local"}
                    onChange={(e) =>
                      setTranscriptionMethod(e.target.value as "local")
                    }
                  />
                  <label
                    htmlFor="local-method"
                    className="ml-3 text-sm font-medium text-gray-700 cursor-pointer flex-grow"
                  >
                    Local (Faster, Free)
                  </label>
                </div>
                <p className="mt-2 text-xs text-gray-500">
                  Processes on your device
                </p>
              </div>
            </div>

            {/* Start Transcription Button */}
            {file && !isTranscribing && (
              <div className="mt-10 max-w-2xl mx-auto text-center">
                <button
                  onClick={handleStartTranscriptionClick}
                  className="w-full md:w-auto px-8 py-4 bg-gradient-to-r from-indigo-600 to-purple-600 text-white font-bold rounded-xl shadow-lg
                                 hover:from-indigo-700 hover:to-purple-700 hover:shadow-xl
                                 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500
                                 transition-all duration-200 active:scale-95
                                 flex items-center justify-center gap-2 text-lg"
                >
                  <svg
                    className="w-5 h-5"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M13 10V3L4 14h7v7l9-11h-7z"
                    />
                  </svg>
                  Start Transcribing
                </button>
              </div>
            )}

            {/* Load Saved Button */}
            <div className="mt-3 text-center">
              <button
                onClick={handleSavedTranscriptionsClick}
                className="text-sm text-blue-600 hover:text-blue-800 font-medium flex items-center justify-center mx-auto"
                disabled={isTranscribing}
              >
                <svg
                  className="w-4 h-4 mr-1"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                >
                  <path d="M19 14l-7 7m0 0l-7-7m7 7V3"></path>
                </svg>
                {showSavedTranscriptions
                  ? "Hide Saved"
                  : "Load Saved Transcription"}
              </button>
            </div>

            {/* Saved Transcriptions Panel */}
            {showSavedTranscriptions && (
              <div className="mt-4 max-w-lg mx-auto">
                <SavedTranscriptionsPanel
                  onTranscriptionLoaded={handleTranscriptionLoaded}
                  onImageClick={openImageModal}
                />
              </div>
            )}

            {/* File Format Info */}
            <div className="mt-4 flex justify-center gap-3">
              <div className="flex items-center space-x-1 text-gray-600">
                <svg
                  className="w-3 h-3 text-teal-500"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                >
                  <circle cx="12" cy="12" r="10"></circle>
                  <polyline points="12 6 12 12 16 14"></polyline>
                </svg>
                <span className="text-2xs">Quick Processing</span>
              </div>
              <div className="flex items-center space-x-1 text-gray-600">
                <svg
                  className="w-3 h-3 text-teal-500"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                >
                  <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path>
                </svg>
                <span className="text-2xs">Secure Upload</span>
              </div>
              <div className="flex items-center space-x-1 text-gray-600">
                <svg
                  className="w-3 h-3 text-teal-500"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                >
                  <path d="M22 12h-4l-3 9L9 3l-3 9H2"></path>
                </svg>
                <span className="text-2xs">High Accuracy</span>
              </div>
            </div>
          </div>
        </div>

        {/* Features Cards */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mt-10 pt-2">
          <div className="group bg-white p-6 rounded-xl shadow-sm border border-gray-200 hover:shadow-lg hover:-translate-y-1 transition-all duration-300">
            <div className="flex items-start gap-4">
              <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-violet-100 to-violet-200 flex items-center justify-center flex-shrink-0 group-hover:scale-110 transition-transform">
                <svg
                  className="w-6 h-6 text-violet-600"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                  strokeWidth="1.5"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                  />
                </svg>
              </div>
              <div className="flex-grow">
                <h3 className="text-sm font-bold text-gray-900 mb-1">
                  High Accuracy
                </h3>
                <p className="text-xs text-gray-600 leading-relaxed">
                  Advanced AI model trained on diverse speech patterns for
                  exceptional accuracy
                </p>
              </div>
            </div>
          </div>

          <div className="group bg-white p-6 rounded-xl shadow-sm border border-gray-200 hover:shadow-lg hover:-translate-y-1 transition-all duration-300">
            <div className="flex items-start gap-4">
              <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-orange-100 to-orange-200 flex items-center justify-center flex-shrink-0 group-hover:scale-110 transition-transform">
                <svg
                  className="w-6 h-6 text-orange-600"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                  strokeWidth="1.5"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"
                  />
                </svg>
              </div>
              <div className="flex-grow">
                <h3 className="text-sm font-bold text-gray-900 mb-1">
                  Fast Processing
                </h3>
                <p className="text-xs text-gray-600 leading-relaxed">
                  Get results in minutes, not hours. Optimized for speed without
                  sacrificing quality
                </p>
              </div>
            </div>
          </div>

          <div className="group bg-white p-6 rounded-xl shadow-sm border border-gray-200 hover:shadow-lg hover:-translate-y-1 transition-all duration-300">
            <div className="flex items-start gap-4">
              <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-rose-100 to-rose-200 flex items-center justify-center flex-shrink-0 group-hover:scale-110 transition-transform">
                <svg
                  className="w-6 h-6 text-rose-600"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                  strokeWidth="1.5"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M3.375 19.5h17.25m-17.25 0a1.125 1.125 0 01-1.125-1.125M3.375 19.5h0a1.125 1.125 0 001.125 1.125m0 0v1.5a.5.5 0 01-.5.5H5a.5.5 0 01-.5-.5v-1.5m0 0h-1.5a.5.5 0 01-.5-.5V15m0 0a1.125 1.125 0 001.125-1.125m0 0h0a1.125 1.125 0 001.125 1.125m0 0v1.5a.5.5 0 01-.5.5H5a.5.5 0 01-.5-.5v-1.5"
                  />
                </svg>
              </div>
              <div className="flex-grow">
                <h3 className="text-sm font-bold text-gray-900 mb-1">
                  30+ Languages
                </h3>
                <p className="text-xs text-gray-600 leading-relaxed">
                  Automatic language detection with support for languages
                  worldwide
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }
);
