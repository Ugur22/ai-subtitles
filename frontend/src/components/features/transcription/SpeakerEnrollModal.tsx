import { Fragment } from "react";
import { Dialog, Transition } from "@headlessui/react";
import type { SpeakerManagementState } from "./hooks/useSpeakerManagement";

export const SpeakerEnrollModal: React.FC<{ speakers: SpeakerManagementState }> = ({ speakers }) => {
  const {
    enrollModalSegment,
    setEnrollModalSegment,
    enrollSpeakerName,
    setEnrollSpeakerName,
    enrollSubmitting,
    handleEnrollConfirm,
  } = speakers;

  return (
    <Transition appear show={enrollModalSegment !== null} as={Fragment}>
      <Dialog as="div" className="relative z-50" onClose={() => { setEnrollModalSegment(null); setEnrollSpeakerName(''); }}>
        <Transition.Child
          as={Fragment}
          enter="ease-out duration-200" enterFrom="opacity-0" enterTo="opacity-100"
          leave="ease-in duration-150" leaveFrom="opacity-100" leaveTo="opacity-0"
        >
          <div className="fixed inset-0" style={{ backgroundColor: 'oklch(11% 0.008 250 / 0.75)' }} />
        </Transition.Child>
        <div className="fixed inset-0 flex items-center justify-center p-4">
          <Transition.Child
            as={Fragment}
            enter="ease-out duration-200" enterFrom="opacity-0 scale-95" enterTo="opacity-100 scale-100"
            leave="ease-in duration-150" leaveFrom="opacity-100 scale-100" leaveTo="opacity-0 scale-95"
          >
            <Dialog.Panel style={{ backgroundColor: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', borderRadius: '8px', padding: '24px', width: '100%', maxWidth: '360px', boxShadow: '0 16px 48px oklch(0% 0 0 / 0.6)' }}>
              <Dialog.Title style={{ fontSize: '14px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '6px' }}>
                Enroll speaker
              </Dialog.Title>
              <p style={{ fontSize: '12px', color: 'var(--text-tertiary)', marginBottom: '16px' }}>
                Save this voice segment as a named speaker for future identification.
              </p>
              <input
                type="text"
                value={enrollSpeakerName}
                onChange={e => setEnrollSpeakerName(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') handleEnrollConfirm(); if (e.key === 'Escape') { setEnrollModalSegment(null); setEnrollSpeakerName(''); } }}
                placeholder="Speaker name"
                autoFocus
                style={{
                  width: '100%', padding: '8px 10px', fontSize: '13px',
                  backgroundColor: 'var(--bg-overlay)', border: '1px solid var(--border-default)',
                  borderRadius: '5px', color: 'var(--text-primary)', outline: 'none',
                  marginBottom: '16px',
                }}
                onFocus={e => (e.currentTarget.style.borderColor = 'var(--accent)')}
                onBlur={e => (e.currentTarget.style.borderColor = 'var(--border-default)')}
              />
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
                <button
                  onClick={() => { setEnrollModalSegment(null); setEnrollSpeakerName(''); }}
                  className="btn-ghost"
                  style={{ padding: '6px 14px', fontSize: '13px' }}
                >
                  Cancel
                </button>
                <button
                  onClick={handleEnrollConfirm}
                  disabled={enrollSubmitting || !enrollSpeakerName.trim()}
                  className="btn-primary"
                  style={{ padding: '6px 14px', fontSize: '13px', opacity: enrollSubmitting || !enrollSpeakerName.trim() ? 0.5 : 1 }}
                >
                  {enrollSubmitting ? 'Enrolling…' : 'Enroll'}
                </button>
              </div>
            </Dialog.Panel>
          </Transition.Child>
        </div>
      </Dialog>
    </Transition>
  );
};
