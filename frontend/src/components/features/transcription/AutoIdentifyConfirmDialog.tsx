import { Fragment } from "react";
import { Dialog, Transition } from "@headlessui/react";
import type { SpeakerManagementState } from "./hooks/useSpeakerManagement";

export const AutoIdentifyConfirmDialog: React.FC<{ speakers: SpeakerManagementState }> = ({ speakers }) => {
  const {
    autoIdentifyConfirmOpen,
    setAutoIdentifyConfirmOpen,
    autoIdentifyRunning,
    handleAutoIdentifyConfirm,
  } = speakers;

  return (
    <Transition appear show={autoIdentifyConfirmOpen} as={Fragment}>
      <Dialog as="div" className="relative z-50" onClose={() => { if (!autoIdentifyRunning) setAutoIdentifyConfirmOpen(false); }}>
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
            <Dialog.Panel style={{ backgroundColor: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', borderRadius: '8px', padding: '24px', width: '100%', maxWidth: '380px', boxShadow: '0 16px 48px oklch(0% 0 0 / 0.6)' }}>
              <Dialog.Title style={{ fontSize: '14px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '6px' }}>
                Auto-identify speakers
              </Dialog.Title>
              <p style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '16px', lineHeight: '1.5' }}>
                This will compare all transcript segments against your enrolled speaker voice prints and assign names where there's a confident match.
              </p>
              <p style={{ fontSize: '11px', color: 'var(--text-tertiary)', marginBottom: '20px' }}>
                The page will refresh after identification completes.
              </p>
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
                <button
                  onClick={() => setAutoIdentifyConfirmOpen(false)}
                  disabled={autoIdentifyRunning}
                  className="btn-ghost"
                  style={{ padding: '6px 14px', fontSize: '13px', opacity: autoIdentifyRunning ? 0.5 : 1 }}
                >
                  Cancel
                </button>
                <button
                  onClick={handleAutoIdentifyConfirm}
                  disabled={autoIdentifyRunning}
                  className="btn-primary"
                  style={{ padding: '6px 14px', fontSize: '13px', opacity: autoIdentifyRunning ? 0.5 : 1 }}
                >
                  {autoIdentifyRunning ? (
                    <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <svg style={{ width: '12px', height: '12px', animation: 'spin 1s linear infinite' }} fill="none" viewBox="0 0 24 24">
                        <circle style={{ opacity: 0.25 }} cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path style={{ opacity: 0.75 }} fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                      </svg>
                      Identifying…
                    </span>
                  ) : 'Identify'}
                </button>
              </div>
            </Dialog.Panel>
          </Transition.Child>
        </div>
      </Dialog>
    </Transition>
  );
};
