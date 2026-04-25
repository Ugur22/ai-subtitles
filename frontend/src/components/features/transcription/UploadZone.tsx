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
      <div className="upload-hero">
        {/* Eyebrow + headline */}
        <div style={{ textAlign: 'center', marginBottom: '28px' }}>
          <span className="upload-eyebrow">
            <span className="dot" />
            Beta · Speaker diarization
          </span>
          <h1 className="upload-headline">
            Turn any video into <em>clean subtitles</em> in about a minute.
          </h1>
          <p className="upload-lede">
            Drop a file, walk away if you want — we'll transcribe, separate speakers, and find scenes for you.
          </p>
        </div>

        {/* Dropzone */}
        <div
          onDragEnter={handleDrag}
          onDragLeave={handleDrag}
          onDragOver={handleDrag}
          onDrop={handleDrop}
          onClick={isTranscribing ? undefined : handleButtonClick}
          className={`dropzone ${dragActive ? 'is-drag' : ''} ${isTranscribing ? 'is-disabled' : ''}`}
          role="button"
          tabIndex={0}
          aria-label="Drop a file here or click to browse"
        >
          <div className="wave" aria-hidden="true">
            <i /><i /><i /><i /><i /><i /><i /><i /><i />
          </div>
          <h3>{dragActive ? 'Release to upload' : 'Drop a video or audio file here'}</h3>
          <p className="dz-sub">
            or <span className="link">browse your computer</span>
          </p>
          <p className="dz-formats">
            MP4 · MP3 · WAV · WebM · MOV · MKV — up to 4 GB
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
              borderRadius: 'var(--radius-md)',
              backgroundColor: 'var(--bg-surface)',
              border: '1px solid var(--border-subtle)',
              display: 'flex',
              alignItems: 'center',
              gap: '12px',
            }}
          >
            <div style={{
              width: '32px', height: '32px', borderRadius: 'var(--radius-sm)',
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
              <p style={{ fontSize: '13px', fontWeight: 500, color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', margin: 0 }}>
                {file.name}
              </p>
              <p style={{ fontSize: '12px', color: 'var(--text-tertiary)', marginTop: '2px', margin: 0 }}>
                {getFileTypeLabel(file.type)} · {(file.size / (1024 * 1024)).toFixed(1)} MB
              </p>
            </div>
            <span className="chip" style={{ background: 'var(--accent-dim)', color: 'var(--accent)', borderColor: 'var(--accent-border)', fontWeight: 500 }}>Ready</span>
          </div>
        )}

        {/* Options row */}
        <div style={{
          marginTop: '16px',
          display: 'grid',
          gridTemplateColumns: 'repeat(2, 1fr)',
          gap: '10px',
        }}>
          {/* Language card */}
          <label style={{
            display: 'flex',
            alignItems: 'center',
            gap: '10px',
            padding: '10px 14px',
            borderRadius: 'var(--radius-md)',
            background: 'var(--bg-surface)',
            border: '1px solid var(--border-subtle)',
            cursor: 'pointer',
            position: 'relative',
          }}>
            <svg style={{ width: '16px', height: '16px', color: 'var(--text-tertiary)', flexShrink: 0 }} fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.8}>
              <path strokeLinecap="round" strokeLinejoin="round"
                d="M3.055 11H5a2 2 0 012 2v1a2 2 0 002 2 2 2 0 012 2v2.945M8 3.935V5.5A2.5 2.5 0 0010.5 8h.5a2 2 0 012 2 2 2 0 104 0 2 2 0 012-2h1.064M15 20.488V18a2 2 0 012-2h3.064M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <span style={{ fontSize: '11.5px', fontWeight: 500, color: 'var(--text-quaternary)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
              Language
            </span>
            <select
              id="language-select"
              value={selectedLanguage}
              onChange={handleLanguageChange}
              disabled={isTranscribing}
              aria-label="Source language"
              style={{
                marginLeft: 'auto',
                appearance: 'none',
                background: 'transparent',
                border: 0,
                outline: 'none',
                fontFamily: 'inherit',
                fontSize: '13px',
                fontWeight: 500,
                color: 'var(--text-primary)',
                cursor: 'pointer',
                paddingRight: '18px',
              }}
            >
              {languageOptions.map((option) => (
                <option key={option.value} value={option.value} style={{ backgroundColor: 'var(--bg-overlay)', color: 'var(--text-primary)' }}>
                  {option.label}
                </option>
              ))}
            </select>
            <svg style={{ position: 'absolute', right: '14px', width: '12px', height: '12px', color: 'var(--text-quaternary)', pointerEvents: 'none' }} fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
            </svg>
          </label>

          {/* Processing segmented */}
          <div style={{
            display: 'flex',
            padding: '3px',
            gap: '2px',
            background: 'var(--bg-surface)',
            border: '1px solid var(--border-subtle)',
            borderRadius: 'var(--radius-md)',
          }}>
            {[
              { value: 'local', label: 'Stay here', title: 'Watch progress live' },
              { value: 'background', label: 'In background', title: 'Close tab safely' },
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
                    flex: 1,
                    padding: '6px 10px',
                    borderRadius: 'var(--radius-sm)',
                    fontSize: '12.5px',
                    fontWeight: 500,
                    border: 0,
                    cursor: isTranscribing ? 'not-allowed' : 'pointer',
                    backgroundColor: isActive ? 'var(--bg-overlay)' : 'transparent',
                    color: isActive ? 'var(--text-primary)' : 'var(--text-tertiary)',
                    boxShadow: isActive ? 'var(--shadow-xs)' : 'none',
                    transition: 'background-color 150ms ease, color 150ms ease, box-shadow 150ms ease',
                    fontFamily: 'inherit',
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
            style={{
              marginTop: '16px',
              width: '100%',
              justifyContent: 'center',
              height: '44px',
              padding: '0 22px',
              fontSize: '14.5px',
              fontWeight: 600,
              borderRadius: 'var(--radius-md)',
              boxShadow: 'var(--shadow-accent)',
            }}
          >
            Start transcribing
            <svg style={{ width: '16px', height: '16px', marginLeft: '8px' }} fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M14 5l7 7m0 0l-7 7m7-7H3" />
            </svg>
          </button>
        )}

        {/* Tips */}
        <div className="tips">
          <div className="tip">
            <div className="tip-icon">
              <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.8}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
              </svg>
            </div>
            <h4>Paste a URL</h4>
            <p>Press <span className="kbd">⌘V</span> on the dropzone to ingest from YouTube or a direct link.</p>
          </div>
          <div className="tip">
            <div className="tip-icon">
              <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.8}>
                <path strokeLinecap="round" strokeLinejoin="round"
                  d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
              </svg>
            </div>
            <h4>Multiple speakers</h4>
            <p>Auto-detected and color-coded. Click any pill to rename.</p>
          </div>
          <div className="tip">
            <div className="tip-icon">
              <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.8}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
            </div>
            <h4>Search inside the video</h4>
            <p>Ask the chat panel anything — every answer cites the moment.</p>
          </div>
        </div>
      </div>
    );
  }
);
