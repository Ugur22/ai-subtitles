import React from "react";
import { match } from "ts-pattern";
import { OutputPreview } from "./OutputPreview";
import { formatFileSize } from "../../../utils/file";

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
  handleStartTranscriptionClick: () => void;
  languageOptions: LanguageOption[];
  children: React.ReactNode;
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
    handleStartTranscriptionClick,
    languageOptions,
    children,
  }) => {
    const [showExample, setShowExample] = React.useState(false);
    const exampleId = React.useId();

    const getFileTypeLabel = (fileType: string) =>
      match(fileType)
        .when((t) => t.startsWith("video/"), () => "Video")
        .otherwise(() => "Audio");

    const handleDropzoneKeyDown = (e: React.KeyboardEvent) => {
      if (isTranscribing) return;
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        handleButtonClick();
      }
    };

    const dropzoneState = dragActive
      ? "border-solid border-accent bg-accent-dim ring-1 ring-accent-border"
      : "border-border-default bg-surface";

    return (
      <section className="upload-workspace relative overflow-hidden">
        <header className="relative mx-auto flex max-w-page items-center justify-between gap-4 border-b border-border-subtle px-5 py-4 sm:px-8">
          <span className="text-sm font-semibold text-text-primary">AI Subs <span className="ml-3 border-l border-border-default pl-3 font-normal text-text-tertiary">Workspace</span></span>
          <span className="mono hidden text-[11px] text-text-tertiary sm:block">VIDEO / AUDIO → TRANSCRIPT</span>
        </header>
        <div className="upload-workspace-grid relative mx-auto grid max-w-page gap-6 px-5 py-6 sm:gap-8 sm:px-8">
          <div className="upload-workspace-form flex min-w-0 flex-col gap-6">
            <div className="flex flex-col gap-3">
              <span className="mono text-xs font-medium uppercase leading-5 tracking-[0.12em] text-accent">Your next transcript starts here</span>
              <h1 className="m-0 text-balance text-[32px] font-medium leading-[1.12] tracking-[-0.035em] text-text-primary sm:text-[38px]">
                Every word. Every speaker.
              </h1>
              <p className="m-0 text-base leading-6 text-text-secondary">
                Turn video or audio into a transcript with named speakers, translations, and subtitles synced to your file.
              </p>
            </div>

            <div className="flex flex-col gap-3">
              <div
                onDragEnter={handleDrag}
                onDragLeave={handleDrag}
                onDragOver={handleDrag}
                onDrop={handleDrop}
                onClick={isTranscribing ? undefined : handleButtonClick}
                onKeyDown={handleDropzoneKeyDown}
                className={`upload-dropzone flex min-h-[128px] items-center gap-4 rounded-lg border border-dashed p-4 sm:p-5 motion-safe:transition-colors motion-safe:duration-150 focus-visible:border-accent focus-visible:bg-accent-dim focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${dropzoneState} ${
                  isTranscribing ? "cursor-not-allowed opacity-50" : "cursor-pointer"
                }`}
                data-drag-active={dragActive}
                role="button"
                tabIndex={isTranscribing ? -1 : 0}
                aria-disabled={isTranscribing}
                aria-label="Drop a file here or click to browse"
              >
                <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-md bg-accent-dim text-accent">
                  <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d="M12 16V4m0 0-4 4m4-4 4 4" />
                    <path d="M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" />
                  </svg>
                </span>
                <span className="flex min-w-0 flex-col gap-1">
                  <span className="text-base font-medium text-text-primary">
                    {dragActive ? "Release to upload" : "Drop a video or audio file"}
                  </span>
                  <span className="text-sm text-text-tertiary">
                    or <span className="text-accent underline underline-offset-[3px]">browse your computer</span>
                  </span>
                  <span className="mono mt-1 text-[11px] text-text-tertiary">
                    MP4 · MP3 · WAV · WebM · MOV · MKV, up to 4 GB
                  </span>
                </span>

                <input
                  ref={fileInputRef}
                  type="file"
                  className="hidden"
                  accept="video/*,audio/*,.mp4,.mpeg,.mpga,.m4a,.wav,.webm,.mp3,.mov,.mkv"
                  onChange={fileUploadHandleChange}
                  disabled={isTranscribing}
                />
              </div>

              {file && (
                <div className="flex items-center gap-3 rounded-md border border-border-subtle bg-surface px-4 py-3">
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-sm bg-accent-dim text-accent">
                    <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                      <path d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                      <path d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                  </span>
                  <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <span className="truncate text-[13px] font-medium text-text-primary">{file.name}</span>
                    <span className="text-xs text-text-tertiary">
                      {getFileTypeLabel(file.type)} · {formatFileSize(file.size)}
                    </span>
                  </span>
                  <span className="text-xs font-medium text-accent">Ready</span>
                </div>
              )}

              <label
                htmlFor="language-select"
                className="upload-language relative flex min-h-11 cursor-pointer items-center gap-2 rounded-md border border-border-subtle bg-surface px-4 focus-within:border-accent focus-within:ring-1 focus-within:ring-accent-border"
              >
                <svg className="h-4 w-4 shrink-0 text-text-tertiary" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <circle cx="12" cy="12" r="9" />
                  <path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" />
                </svg>
                <span className="text-sm text-text-secondary">Spoken language</span>
                <select
                  id="language-select"
                  value={selectedLanguage}
                  onChange={handleLanguageChange}
                  disabled={isTranscribing}
                  className="ml-auto min-w-0 max-w-full cursor-pointer appearance-none border-0 bg-transparent pr-5 text-sm font-medium text-text-primary outline-none"
                >
                  {languageOptions.map((option) => (
                    <option key={option.value} value={option.value} className="bg-overlay text-text-primary">
                      {option.label}
                    </option>
                  ))}
                </select>
                <svg className="pointer-events-none absolute right-4 h-3 w-3 text-text-tertiary" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="m6 9 6 6 6-6" />
                </svg>
              </label>

              {file && !isTranscribing && (
                <button
                  type="button"
                  onClick={handleStartTranscriptionClick}
                  className="btn-primary h-11 w-full gap-2"
                >
                  Start transcribing
                  <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d="M14 5l7 7m0 0l-7 7m7-7H3" />
                  </svg>
                </button>
              )}
              <p className="m-0 text-xs leading-5 text-text-tertiary">Processing time depends on file length. Allow about half an hour for a 50-minute episode.</p>
            </div>
          </div>
          <div className="upload-workspace-jobs min-w-0">{children}</div>
          <div className="upload-workspace-example min-w-0" data-expanded={showExample}>
            <button type="button" aria-expanded={showExample} aria-controls={exampleId} onClick={() => setShowExample(!showExample)} className="min-h-11 cursor-pointer rounded-md py-3 text-left text-sm font-medium text-text-secondary focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">{showExample ? "Hide example" : "See an example"}</button>
            <div id={exampleId} className="upload-workspace-preview pt-3"><OutputPreview /></div>
          </div>
          <details className="upload-workspace-help border-t border-border-subtle">
            <summary className="min-h-11 cursor-pointer rounded-md py-3 text-sm font-medium text-text-secondary focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">How transcription works</summary>
          <ol aria-label="How transcription works" className="m-0 grid list-none gap-6 p-0 pb-3 pt-3 sm:grid-cols-3">
            {[
              { step: '01', title: 'Bring your footage', detail: 'Upload a video, recording, interview, or podcast.' },
              { step: '02', title: 'Let it process', detail: 'We transcribe, separate speakers, and translate. You can come back later.' },
              { step: '03', title: 'Work with every word', detail: 'Follow the transcript alongside your video, with speakers and timestamps.' },
            ].map(({ step, title, detail }) => (
              <li key={step} className="flex gap-3">
                <span className="mono pt-0.5 text-[11px] text-accent">{step}</span>
                <div>
                  <h2 className="m-0 text-[13px] font-medium text-text-primary">{title}</h2>
                  <p className="mb-0 mt-1 max-w-[32ch] text-xs leading-5 text-text-tertiary">{detail}</p>
                </div>
              </li>
            ))}
          </ol>
          </details>
        </div>
      </section>
    );
  }
);
UploadZone.displayName = "UploadZone";
