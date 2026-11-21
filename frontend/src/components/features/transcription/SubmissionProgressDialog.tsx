import { Dialog } from "@headlessui/react";
import type { SubmissionProgress } from "../../../services/api";

interface SubmissionProgressDialogProps {
  isOpen: boolean;
  progress: SubmissionProgress | null;
  file: File | null;
}

export const SubmissionProgressDialog: React.FC<SubmissionProgressDialogProps> = ({ isOpen, progress, file }) => {
  const submissionStage = progress?.stage ?? 'hashing';
  const submissionPercent = progress?.progress ?? 0;
  const submissionStep = submissionStage === 'hashing' ? 0 : submissionStage === 'uploading' ? 1 : 2;

  return (
    <Dialog open={isOpen} onClose={() => {}} className="relative z-50">
      <div className="fixed inset-0" style={{ backgroundColor: 'oklch(11% 0.008 250 / 0.55)', backdropFilter: 'blur(4px)' }} aria-hidden="true" />
      <div className="fixed inset-0 flex items-center justify-center overflow-y-auto p-5">
        <Dialog.Panel className="w-full max-w-md overflow-hidden rounded-2xl" style={{ backgroundColor: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', boxShadow: '0 24px 80px oklch(0% 0 0 / 0.22)' }}>
          <div className="p-6 sm:p-8">
            <p className="mb-3 text-xs font-medium uppercase tracking-widest" style={{ color: 'var(--accent)' }}>New transcription</p>
            <Dialog.Title className="text-xl font-semibold tracking-tight" style={{ color: 'var(--text-primary)' }}>
              {submissionStage === 'hashing' ? 'Preparing your file' : submissionStage === 'uploading' ? 'Uploading your file' : submissionStage === 'complete' ? 'Ready to transcribe' : 'Adding to the queue'}
            </Dialog.Title>
            <Dialog.Description className="mt-2 text-sm leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
              Keep this tab open until your file is uploaded and queued.
            </Dialog.Description>
            <div className="mt-6 min-w-0 rounded-lg px-4 py-3" style={{ backgroundColor: 'var(--bg-base)', border: '1px solid var(--border-subtle)' }}>
              <p className="truncate text-sm font-medium" style={{ color: 'var(--text-primary)' }} title={file?.name}>{file?.name || 'Media file'}</p>
              {file && <p className="mt-1 text-xs tabular-nums" style={{ color: 'var(--text-tertiary)' }}>{new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(file.size / (1024 ** 2))} MB</p>}
            </div>
            <div className="mt-6 flex items-baseline justify-between gap-3">
              <span className="text-xs font-medium" style={{ color: 'var(--text-secondary)' }}>Overall progress</span>
              <span className="text-2xl font-medium tabular-nums tracking-tight" style={{ color: 'var(--text-primary)' }}>{submissionPercent}<span className="ml-0.5 text-sm" style={{ color: 'var(--text-tertiary)' }}>%</span></span>
            </div>
            <div className="mt-2 h-1.5 overflow-hidden rounded-full" role="progressbar" aria-label="Transcription submission" aria-valuemin={0} aria-valuemax={100} aria-valuenow={submissionPercent} style={{ backgroundColor: 'var(--bg-subtle)' }}>
              <div className="h-full rounded-full transition-[width] duration-300 motion-reduce:transition-none" style={{ width: `${submissionPercent}%`, backgroundColor: 'var(--accent)' }} />
            </div>
            <ol className="mt-4 flex justify-between gap-2 text-xs" aria-label="Submission steps">
              {['Prepare', 'Upload', 'Queue'].map((label, index) => {
                const complete = submissionStage === 'complete' || index < submissionStep;
                const active = submissionStage !== 'complete' && index === submissionStep;
                return (
                  <li key={label} aria-current={active ? 'step' : undefined} className="flex items-center gap-1.5" style={{ color: complete || active ? 'var(--accent)' : 'var(--text-tertiary)', fontWeight: active ? 600 : 400 }}>
                    <span className="flex h-4 w-4 items-center justify-center rounded-full text-[10px]" style={{ backgroundColor: complete || active ? 'var(--accent-dim)' : 'var(--bg-subtle)' }}>
                      {complete ? <svg className="h-3 w-3" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" aria-label="Complete"><path d="m3 8 3 3 7-7" /></svg> : index + 1}
                    </span>
                    {label}
                  </li>
                );
              })}
            </ol>
            <p role="status" className="mt-5 min-h-4 text-xs leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
              {submissionStage === 'uploading' && submissionPercent >= 80 ? 'All bytes sent. Waiting for storage to confirm…' : submissionStage === 'uploading' ? progress?.message || 'Connecting to storage…' : submissionStage === 'hashing' ? 'Reading your file before upload…' : submissionStage === 'complete' ? 'Your transcription is queued.' : 'Your file is uploaded. Waiting for the queue to confirm…'}
            </p>
          </div>
          <div className="px-6 py-4 text-xs leading-relaxed sm:px-8" style={{ borderTop: '1px solid var(--border-subtle)', backgroundColor: 'var(--bg-base)', color: 'var(--text-tertiary)' }}>
            Once queued, transcription continues even if you close this tab.
          </div>
        </Dialog.Panel>
      </div>
    </Dialog>
  );
};
