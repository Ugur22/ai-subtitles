import React from "react";
import { match } from "ts-pattern";

interface ProcessingStatus {
  stage: "uploading" | "downloading" | "extracting" | "transcribing" | "translating" | "complete";
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
  setTranscriptionMethod: React.Dispatch<React.SetStateAction<"local" | "background">>;
  handleStartTranscriptionClick: () => void;
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
    isNewTranscription: _isNewTranscription,
    processingStatus: _processingStatus,
    elapsedTime: _elapsedTime,
    languageOptions,
  }) => {
    const getFileTypeLabel = (fileType: string) =>
      match(fileType)
        .when((t) => t.startsWith("video/"), () => "Video")
        .otherwise(() => "Audio");

    return (
      <div style={{ maxWidth: '720px', margin: '0 auto', padding: '56px 24px 32px' }}>

        {/* Page heading */}
        <div style={{ marginBottom: '32px', textAlign: 'center' }}>
          <h1 style={{
            fontSize: '24px',
            fontWeight: 600,
            letterSpacing: '-0.02em',
            color: 'var(--text-primary)',
            margin: 0,
            lineHeight: 1.2,
          }}>
            Transcribe your media
          </h1>
        </div>

        {/* Upload drop zone */}
        <div
          onDragEnter={handleDrag}
          onDragLeave={handleDrag}
          onDragOver={handleDrag}
          onDrop={handleDrop}
          onClick={handleButtonClick}
          style={{
            position: 'relative',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            width: '100%',
            height: '220px',
            border: `1px dashed ${dragActive ? 'var(--accent)' : 'var(--border-default)'}`,
            borderRadius: '10px',
            backgroundColor: dragActive ? 'var(--accent-dim)' : 'transparent',
            cursor: isTranscribing ? 'not-allowed' : 'pointer',
            opacity: isTranscribing ? 0.5 : 1,
            transition: 'border-color 150ms ease, background-color 150ms ease',
          }}
          onMouseEnter={e => {
            if (!dragActive && !isTranscribing) {
              (e.currentTarget as HTMLDivElement).style.borderColor = 'var(--accent)';
              (e.currentTarget as HTMLDivElement).style.backgroundColor = 'var(--accent-dim)';
            }
          }}
          onMouseLeave={e => {
            if (!dragActive) {
              (e.currentTarget as HTMLDivElement).style.borderColor = 'var(--border-default)';
              (e.currentTarget as HTMLDivElement).style.backgroundColor = 'transparent';
            }
          }}
        >
          {/* Circular icon pill */}
          <div style={{
            width: '56px',
            height: '56px',
            borderRadius: '50%',
            backgroundColor: 'var(--accent-dim)',
            border: '1px solid var(--accent-border)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}>
            <svg
              style={{ width: '22px', height: '22px', color: 'var(--accent)' }}
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              strokeWidth="1.5"
            >
              <path d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
            </svg>
          </div>

          <p style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text-primary)', marginTop: '16px', marginBottom: '4px' }}>
            {dragActive ? 'Release to upload' : 'Drop your file here'}
          </p>
          <p style={{ fontSize: '13px', color: 'var(--text-tertiary)' }}>
            or <span style={{ color: 'var(--accent)', textDecoration: 'underline', textUnderlineOffset: '2px' }}>browse your computer</span>
          </p>
          <p style={{ fontSize: '11px', color: 'var(--text-tertiary)', marginTop: '12px', letterSpacing: '0.02em' }}>
            MP4 · MP3 · WAV · WebM · AVI · MKV and more
          </p>

          <input
            ref={fileInputRef}
            type="file"
            style={{ display: 'none' }}
            accept="video/*,audio/*,.mp4,.mpeg,.mpga,.m4a,.wav,.webm,.mp3,.mov,.mkv"
            onChange={fileUploadHandleChange}
            disabled={isTranscribing}
          />
        </div>

        {/* Selected file info */}
        {file && (
          <div
            style={{
              marginTop: '16px',
              padding: '12px 16px',
              borderRadius: '8px',
              backgroundColor: 'var(--bg-surface)',
              border: '1px solid var(--border-subtle)',
              display: 'flex',
              alignItems: 'center',
              gap: '12px',
            }}
          >
            <div style={{
              width: '32px', height: '32px', borderRadius: '8px',
              backgroundColor: 'var(--accent-dim)', border: '1px solid var(--accent-border)',
              display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
            }}>
              <svg style={{ width: '16px', height: '16px', color: 'var(--accent)' }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                  d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <p style={{ fontSize: '13px', fontWeight: 500, color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {file.name}
              </p>
              <p style={{ fontSize: '12px', color: 'var(--text-tertiary)', marginTop: '2px' }}>
                {getFileTypeLabel(file.type)} · {(file.size / (1024 * 1024)).toFixed(1)} MB
              </p>
            </div>
            <span style={{ fontSize: '11px', color: 'var(--c-success)', fontWeight: 500, flexShrink: 0 }}>Ready</span>
          </div>
        )}

        {/* Compact settings row */}
        <div style={{
          marginTop: '20px',
          display: 'flex',
          justifyContent: 'center',
          gap: '8px',
          flexWrap: 'wrap',
        }}>
          {/* Language pill */}
          <div style={{ position: 'relative' }}>
            <svg
              style={{
                position: 'absolute',
                left: '10px',
                top: '50%',
                transform: 'translateY(-50%)',
                width: '14px',
                height: '14px',
                color: 'var(--text-tertiary)',
                pointerEvents: 'none',
              }}
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              strokeWidth={1.8}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M3.055 11H5a2 2 0 012 2v1a2 2 0 002 2 2 2 0 012 2v2.945M8 3.935V5.5A2.5 2.5 0 0010.5 8h.5a2 2 0 012 2 2 2 0 104 0 2 2 0 012-2h1.064M15 20.488V18a2 2 0 012-2h3.064M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <select
              id="language-select"
              value={selectedLanguage}
              onChange={handleLanguageChange}
              disabled={isTranscribing}
              aria-label="Source language"
              style={{
                height: '32px',
                padding: '0 28px 0 32px',
                border: '1px solid var(--border-subtle)',
                borderRadius: '8px',
                backgroundColor: 'var(--bg-surface)',
                color: 'var(--text-primary)',
                fontSize: '13px',
                appearance: 'none',
                cursor: 'pointer',
                outline: 'none',
              }}
            >
              {languageOptions.map((option) => (
                <option key={option.value} value={option.value} style={{ backgroundColor: 'var(--bg-overlay)', color: 'var(--text-primary)' }}>
                  {option.label}
                </option>
              ))}
            </select>
            <svg
              style={{
                position: 'absolute',
                right: '10px',
                top: '50%',
                transform: 'translateY(-50%)',
                width: '12px',
                height: '12px',
                color: 'var(--text-tertiary)',
                pointerEvents: 'none',
              }}
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              strokeWidth={2}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
            </svg>
          </div>

          {/* Processing segmented control */}
          <div style={{
            height: '32px',
            display: 'flex',
            padding: '2px',
            gap: '2px',
            backgroundColor: 'var(--bg-surface)',
            border: '1px solid var(--border-subtle)',
            borderRadius: '8px',
          }}>
            {[
              { value: 'local', label: 'Real-time', title: 'Stay on this page' },
              { value: 'background', label: 'Background', title: 'Close tab safely' },
            ].map(({ value, label, title }) => {
              const isActive = transcriptionMethod === value;
              return (
                <button
                  key={value}
                  type="button"
                  onClick={() => setTranscriptionMethod(value as "local" | "background")}
                  disabled={isTranscribing}
                  title={title}
                  style={{
                    padding: '0 12px',
                    borderRadius: '6px',
                    fontSize: '13px',
                    fontWeight: 500,
                    border: 'none',
                    cursor: isTranscribing ? 'not-allowed' : 'pointer',
                    backgroundColor: isActive ? 'var(--bg-overlay)' : 'transparent',
                    color: isActive ? 'var(--text-primary)' : 'var(--text-tertiary)',
                    boxShadow: isActive ? '0 1px 2px oklch(0% 0 0 / 0.06)' : 'none',
                    transition: 'background-color 150ms ease, color 150ms ease, box-shadow 150ms ease',
                    outline: 'none',
                  }}
                >
                  {label}
                </button>
              );
            })}
          </div>
        </div>

        {/* CTA */}
        {file && !isTranscribing && (
          <button
            onClick={handleStartTranscriptionClick}
            className="btn-primary"
            style={{ marginTop: '16px', width: '100%', justifyContent: 'center', height: '40px', padding: '0 24px', fontSize: '15px', fontWeight: 600 }}
          >
            <svg style={{ width: '16px', height: '16px', marginRight: '8px' }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
            Start transcription
          </button>
        )}
      </div>
    );
  }
);
