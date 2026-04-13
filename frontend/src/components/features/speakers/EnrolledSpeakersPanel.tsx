import { useState, useEffect } from "react";
import axios from "axios";
import toast from "react-hot-toast";
import { API_BASE_URL } from "../../../config";

interface Speaker {
  name: string;
  samples_count: number;
  embedding_shape: number[];
}

interface EnrolledSpeakersPanelProps {
  onSpeakerDeleted?: () => void;
}

export const EnrolledSpeakersPanel: React.FC<EnrolledSpeakersPanelProps> = ({
  onSpeakerDeleted,
}) => {
  const [speakers, setSpeakers] = useState<Speaker[]>([]);
  const [loading, setLoading] = useState(false);
  const [isOpen, setIsOpen] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState<string | null>(null);

  const fetchSpeakers = async () => {
    setLoading(true);
    try {
      const response = await axios.get(`${API_BASE_URL}/api/speaker/list`);
      setSpeakers(response.data.speakers || []);
    } catch (error) {
      console.error("Error fetching speakers:", error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      fetchSpeakers();
    }
  }, [isOpen]);

  const handleDeleteSpeaker = async (speakerName: string) => {
    try {
      await axios.delete(`${API_BASE_URL}/api/speaker/${speakerName}`);
      setConfirmingDelete(null);
      await fetchSpeakers();
      onSpeakerDeleted?.();
    } catch (error) {
      console.error("Error deleting speaker:", error);
      toast.error("Failed to delete speaker");
    }
  };

  return (
    <div className="relative">
      {/* Toggle Button */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="btn-ghost"
        style={{
          padding: '4px 10px',
          fontSize: '12px',
          color: isOpen ? 'var(--accent)' : 'var(--text-secondary)',
          backgroundColor: isOpen ? 'var(--accent-dim)' : 'transparent',
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
        }}
        title="Manage enrolled speaker voice prints"
      >
        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z"
          />
        </svg>
        Enrolled
        {speakers.length > 0 && (
          <span style={{
            fontSize: '10px', fontWeight: 600,
            backgroundColor: 'var(--bg-surface)',
            color: 'var(--text-tertiary)',
            border: '1px solid var(--border-subtle)',
            borderRadius: '9999px',
            padding: '0 5px',
          }}>
            {speakers.length}
          </span>
        )}
      </button>

      {/* Panel */}
      {isOpen && (
        <div
          className="absolute left-0 mt-1 z-20 animate-scaleIn"
          style={{
            width: '280px',
            backgroundColor: 'var(--bg-overlay)',
            border: '1px solid var(--border-subtle)',
            borderRadius: '6px',
            boxShadow: '0 8px 24px oklch(0% 0 0 / 0.5)',
            top: '100%',
          }}
        >
          <div style={{ padding: '10px 14px', borderBottom: '1px solid var(--border-subtle)' }}>
            <p style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)' }}>
              Enrolled speakers
            </p>
            <p style={{ fontSize: '11px', color: 'var(--text-tertiary)', marginTop: '2px' }}>
              Voice prints for automatic identification
            </p>
          </div>

          <div style={{ maxHeight: '320px', overflowY: 'auto', padding: '6px 0' }}>
            {loading ? (
              <div style={{ display: 'flex', justifyContent: 'center', padding: '24px 0' }}>
                <div className="animate-spin" style={{ width: '18px', height: '18px', border: '2px solid var(--border-default)', borderTopColor: 'var(--accent)', borderRadius: '50%' }} />
              </div>
            ) : speakers.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '24px 16px' }}>
                <svg className="w-8 h-8 mx-auto mb-2" style={{ color: 'var(--text-tertiary)' }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                    d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z"
                  />
                </svg>
                <p style={{ fontSize: '12px', color: 'var(--text-secondary)', fontWeight: 500 }}>No speakers enrolled</p>
                <p style={{ fontSize: '11px', color: 'var(--text-tertiary)', marginTop: '4px' }}>
                  Click "Enroll" on a transcript segment
                </p>
              </div>
            ) : (
              speakers.map((speaker) => (
                <div key={speaker.name}>
                  {confirmingDelete === speaker.name ? (
                    <div style={{ padding: '8px 14px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px', backgroundColor: 'oklch(65% 0.20 25 / 0.06)' }}>
                      <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                        Remove <strong style={{ color: 'var(--text-primary)' }}>{speaker.name}</strong>?
                      </span>
                      <div style={{ display: 'flex', gap: '6px', flexShrink: 0 }}>
                        <button
                          onClick={() => handleDeleteSpeaker(speaker.name)}
                          style={{ fontSize: '11px', fontWeight: 600, color: 'var(--c-error)', background: 'none', border: 'none', cursor: 'pointer', padding: '2px 6px' }}
                        >
                          Remove
                        </button>
                        <button
                          onClick={() => setConfirmingDelete(null)}
                          style={{ fontSize: '11px', color: 'var(--text-tertiary)', background: 'none', border: 'none', cursor: 'pointer', padding: '2px 6px' }}
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div
                      style={{ padding: '8px 14px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '10px' }}
                      onMouseEnter={e => (e.currentTarget as HTMLDivElement).style.backgroundColor = 'var(--bg-surface)'}
                      onMouseLeave={e => (e.currentTarget as HTMLDivElement).style.backgroundColor = 'transparent'}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0 }}>
                        <div style={{
                          width: '28px', height: '28px', borderRadius: '50%', flexShrink: 0,
                          backgroundColor: 'var(--bg-surface)',
                          border: '1px solid var(--border-default)',
                          display: 'flex', alignItems: 'center', justifyContent: 'center',
                        }}>
                          <svg className="w-3.5 h-3.5" style={{ color: 'var(--text-secondary)' }} fill="currentColor" viewBox="0 0 20 20">
                            <path fillRule="evenodd" d="M10 9a3 3 0 100-6 3 3 0 000 6zm-7 9a7 7 0 1114 0H3z" clipRule="evenodd" />
                          </svg>
                        </div>
                        <div style={{ minWidth: 0 }}>
                          <p style={{ fontSize: '13px', fontWeight: 500, color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {speaker.name}
                          </p>
                          <p style={{ fontSize: '11px', color: 'var(--text-tertiary)' }}>
                            {speaker.samples_count} sample{speaker.samples_count !== 1 ? 's' : ''}
                          </p>
                        </div>
                      </div>
                      <button
                        onClick={() => setConfirmingDelete(speaker.name)}
                        className="btn-ghost"
                        style={{ padding: '4px', flexShrink: 0 }}
                        title="Remove speaker"
                      >
                        <svg className="w-3.5 h-3.5" style={{ color: 'var(--text-tertiary)' }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                            d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
                          />
                        </svg>
                      </button>
                    </div>
                  )}
                </div>
              ))
            )}
          </div>

          {speakers.length > 0 && (
            <div style={{ padding: '8px 14px', borderTop: '1px solid var(--border-subtle)' }}>
              <p style={{ fontSize: '11px', color: 'var(--text-tertiary)' }}>
                Enroll multiple samples per speaker for better accuracy.
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
