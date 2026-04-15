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
      <div style={{ maxWidth: '760px', margin: '0 auto', padding: '40px 24px 32px' }}>

        {/* Page heading */}
        <div style={{ marginBottom: '28px', textAlign: 'center' }}>
          <h1 style={{
            fontSize: '22px',
            fontWeight: 600,
            letterSpacing: '-0.02em',
            color: 'var(--text-primary)',
            margin: 0,
            lineHeight: 1.3,
          }}>
            Transcribe your media
          </h1>
          <p style={{
            marginTop: '6px',
            fontSize: '14px',
            color: 'var(--text-tertiary)',
            lineHeight: 1.5,
          }}>
            Upload a video or audio file to generate a searchable transcript
          </p>
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
            height: '280px',
            border: `1.5px dashed ${dragActive ? 'var(--accent)' : 'var(--border-default)'}`,
            borderRadius: '8px',
            backgroundColor: dragActive ? 'var(--accent-dim)' : 'var(--bg-subtle)',
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
              (e.currentTarget as HTMLDivElement).style.backgroundColor = 'var(--bg-subtle)';
            }
          }}
        >
          <svg
            style={{ width: '36px', height: '36px', color: dragActive ? 'var(--accent)' : 'var(--text-tertiary)', marginBottom: '14px', transition: 'color 150ms ease' }}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
            strokeWidth="1.5"
          >
            <path d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
          </svg>

          <p style={{ fontSize: '14px', fontWeight: 500, color: 'var(--text-primary)', marginBottom: '4px' }}>
            {dragActive ? 'Release to upload' : 'Drop your file here'}
          </p>
          <p style={{ fontSize: '13px', color: 'var(--text-tertiary)' }}>
            or <span style={{ color: 'var(--accent)' }}>browse</span> your computer
          </p>
          <p style={{ fontSize: '11px', color: 'var(--text-tertiary)', marginTop: '8px' }}>
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
              marginTop: '12px',
              padding: '12px 16px',
              borderRadius: '6px',
              backgroundColor: 'var(--bg-surface)',
              border: '1px solid var(--border-subtle)',
              display: 'flex',
              alignItems: 'center',
              gap: '12px',
            }}
          >
            <div style={{
              width: '32px', height: '32px', borderRadius: '6px',
              backgroundColor: 'var(--accent-dim)', border: '1px solid var(--accent)',
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

        {/* Options */}
        <div style={{ marginTop: '28px', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' }}>

          {/* Language */}
          <div>
            <label
              htmlFor="language-select"
              style={{ display: 'block', fontSize: '12px', fontWeight: 500, color: 'var(--text-secondary)', marginBottom: '8px' }}
            >
              Source language
            </label>
            <select
              id="language-select"
              value={selectedLanguage}
              onChange={handleLanguageChange}
              disabled={isTranscribing}
              className="input-base w-full"
              style={{ appearance: 'none', cursor: 'pointer' }}
            >
              {languageOptions.map((option) => (
                <option key={option.value} value={option.value} style={{ backgroundColor: 'var(--bg-overlay)', color: 'var(--text-primary)' }}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>

          {/* Processing method */}
          <div>
            <p style={{ fontSize: '12px', fontWeight: 500, color: 'var(--text-secondary)', marginBottom: '8px' }}>
              Processing method
            </p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              {[
                { value: 'local', label: 'Real-time', sublabel: 'Stay on page' },
                { value: 'background', label: 'Background', sublabel: 'Close tab safely' },
              ].map(({ value, label, sublabel }) => (
                <label
                  key={value}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '10px',
                    padding: '8px 12px',
                    borderRadius: '6px',
                    border: `1px solid ${transcriptionMethod === value ? 'var(--accent)' : 'var(--border-subtle)'}`,
                    backgroundColor: transcriptionMethod === value ? 'var(--accent-dim)' : 'var(--bg-surface)',
                    cursor: 'pointer',
                    transition: 'border-color 150ms ease, background-color 150ms ease',
                  }}
                >
                  <input
                    type="radio"
                    name="transcriptionMethod"
                    value={value}
                    checked={transcriptionMethod === value}
                    onChange={(e) => setTranscriptionMethod(e.target.value as "local" | "background")}
                    style={{ accentColor: 'var(--accent)', width: '14px', height: '14px', flexShrink: 0 }}
                  />
                  <span>
                    <span style={{ fontSize: '13px', fontWeight: 500, color: 'var(--text-primary)', display: 'block' }}>{label}</span>
                    <span style={{ fontSize: '11px', color: 'var(--text-tertiary)' }}>{sublabel}</span>
                  </span>
                </label>
              ))}
            </div>
          </div>
        </div>

        {/* Feature chips */}
        <div style={{
          marginTop: '24px',
          display: 'flex',
          flexWrap: 'wrap',
          gap: '8px',
          justifyContent: 'center',
        }}>
          {[
            { icon: 'M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z', label: 'Speaker detection' },
            { icon: 'M4 6h16M4 12h16M4 18h7', label: 'Auto chapters' },
            { icon: 'M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z', label: 'AI chat' },
            { icon: 'M3 5h12M9 3v2m1.048 9.5A18.022 18.022 0 016.412 9m6.088 9h7M11 21l5-10 5 10M12.751 5C11.783 10.77 8.07 15.61 3 18.129', label: 'Translations' },
          ].map(({ icon, label }) => (
            <div
              key={label}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '6px',
                padding: '5px 10px',
                borderRadius: '20px',
                border: '1px solid var(--border-subtle)',
                backgroundColor: 'var(--bg-surface)',
                fontSize: '12px',
                color: 'var(--text-tertiary)',
                fontWeight: 400,
                userSelect: 'none' as const,
              }}
            >
              <svg style={{ width: '12px', height: '12px', flexShrink: 0 }} fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d={icon} />
              </svg>
              {label}
            </div>
          ))}
        </div>

        {/* CTA */}
        {file && !isTranscribing && (
          <button
            onClick={handleStartTranscriptionClick}
            className="btn-primary"
            style={{ marginTop: '24px', width: '100%', justifyContent: 'center', padding: '10px 24px', fontSize: '14px', fontWeight: 600 }}
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
