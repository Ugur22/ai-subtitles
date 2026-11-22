import type { Dispatch, SetStateAction } from "react";
import type { TranscriptionResponse } from "../../../services/api";
import { formatSpeakerLabel } from "../../../utils/speaker";
import type { SpeakerManagementState } from "./hooks/useSpeakerManagement";
import type { TranscriptSegment } from "./segments";

interface TranscriptToolbarProps {
  transcription: TranscriptionResponse;
  displayedSegments: TranscriptSegment[];
  uniqueSpeakers: string[];
  showTranslation: boolean;
  setShowTranslation: (show: boolean) => void;
  filteredSpeaker: string | null;
  setFilteredSpeaker: Dispatch<SetStateAction<string | null>>;
  showVisualMoments: boolean;
  setShowVisualMoments: (show: boolean) => void;
  speakers: SpeakerManagementState;
}

export const TranscriptToolbar: React.FC<TranscriptToolbarProps> = ({
  transcription,
  displayedSegments,
  uniqueSpeakers,
  showTranslation,
  setShowTranslation,
  filteredSpeaker,
  setFilteredSpeaker,
  showVisualMoments,
  setShowVisualMoments,
  speakers,
}) => {
  const {
    speakerDropdownOpen,
    setSpeakerDropdownOpen,
    handleAutoIdentifySpeakers,
    showEnrolledInDropdown,
    setShowEnrolledInDropdown,
    enrolledSpeakers,
    enrolledLoading,
    confirmingDeleteEnrolled,
    handleDeleteEnrolledSpeaker,
    setConfirmingDeleteEnrolled,
  } = speakers;

  return (
    <div
      className="sticky top-0 z-10 flex-wrap gap-2"
      style={{
        display: 'flex',
        alignItems: 'center',
        padding: '8px 10px',
        borderBottom: '1px solid var(--border-subtle)',
        backgroundColor: 'var(--bg-subtle)',
      }}
    >
      <div className="flex items-center gap-2 flex-wrap">
        <button
          onClick={() => setShowTranslation(!showTranslation)}
          className="btn-ghost"
          style={{
            padding: '4px 10px',
            fontSize: '12px',
            color: showTranslation ? 'var(--accent)' : 'var(--text-secondary)',
            backgroundColor: showTranslation ? 'var(--accent-dim)' : 'transparent',
          }}
          title="Show translated text for each segment"
        >
          {showTranslation ? "Original" : "Translate"}
        </button>

        <div className="relative">
          <button
            onClick={() => setSpeakerDropdownOpen(!speakerDropdownOpen)}
            className="btn-ghost"
            style={{
              padding: '4px 10px',
              fontSize: '12px',
              color: filteredSpeaker ? 'var(--accent)' : 'var(--text-secondary)',
              backgroundColor: filteredSpeaker ? 'var(--accent-dim)' : 'transparent',
              display: 'flex', alignItems: 'center', gap: '6px',
            }}
          >
            <span>{filteredSpeaker ? formatSpeakerLabel(filteredSpeaker) : 'Speakers'}</span>
            <span style={{ opacity: 0.6 }}>({displayedSegments.length})</span>
            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" style={{ transform: speakerDropdownOpen ? 'rotate(180deg)' : 'rotate(0)', transition: 'transform 150ms ease' }}>
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </button>

          {speakerDropdownOpen && (
            <div
              className="absolute left-0 mt-1 z-20 rounded-md"
              style={{
                width: '240px',
                backgroundColor: 'var(--bg-overlay)',
                border: '1px solid var(--border-subtle)',
                boxShadow: '0 8px 24px oklch(0% 0 0 / 0.5)',
              }}
            >
              <div style={{ maxHeight: '220px', overflowY: 'auto' }}>
                <button
                  onClick={() => { setFilteredSpeaker(null); setSpeakerDropdownOpen(false); }}
                  style={{
                    display: 'flex', width: '100%', textAlign: 'left',
                    padding: '8px 12px', fontSize: '13px',
                    color: !filteredSpeaker ? 'var(--accent)' : 'var(--text-secondary)',
                    backgroundColor: !filteredSpeaker ? 'var(--accent-dim)' : 'transparent',
                    alignItems: 'center', justifyContent: 'space-between',
                  }}
                >
                  <span style={{ fontWeight: 500 }}>All speakers</span>
                  <span style={{ fontSize: '11px', color: 'var(--text-tertiary)' }}>
                    {transcription?.transcription.segments.length}
                  </span>
                </button>

                {uniqueSpeakers.map((speaker) => {
                  const segmentCount =
                    transcription?.transcription.segments.filter(
                      (seg) => seg.speaker === speaker
                    ).length || 0;

                  return (
                    <button
                      key={speaker}
                      onClick={() => {
                        setFilteredSpeaker(speaker);
                        setSpeakerDropdownOpen(false);
                      }}
                      style={{
                        width: '100%',
                        textAlign: 'left',
                        padding: '8px 14px',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        borderTop: '1px solid var(--border-subtle)',
                        backgroundColor: filteredSpeaker === speaker ? 'var(--accent-dim)' : 'transparent',
                        cursor: 'pointer',
                        transition: 'background-color 100ms ease',
                      }}
                      onMouseEnter={e => { if (filteredSpeaker !== speaker) (e.currentTarget as HTMLButtonElement).style.backgroundColor = 'var(--bg-surface)'; }}
                      onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.backgroundColor = filteredSpeaker === speaker ? 'var(--accent-dim)' : 'transparent'; }}
                    >
                      <div className="flex items-center gap-2">
                        <span style={{
                          display: 'inline-flex', alignItems: 'center', gap: '6px',
                          padding: '2px 8px', borderRadius: '9999px',
                          fontSize: '11px', fontWeight: 600,
                          backgroundColor: filteredSpeaker === speaker ? 'var(--accent)' : 'var(--bg-overlay)',
                          color: filteredSpeaker === speaker ? 'var(--accent-text)' : 'var(--text-secondary)',
                          border: '1px solid var(--border-default)',
                        }}>
                          <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
                            <path fillRule="evenodd" d="M10 9a3 3 0 100-6 3 3 0 000 6zm-7 9a7 7 0 1114 0H3z" clipRule="evenodd" />
                          </svg>
                          {formatSpeakerLabel(speaker)}
                        </span>
                      </div>
                      <span style={{ fontSize: '11px', color: 'var(--text-tertiary)' }}>
                        {segmentCount}
                      </span>
                    </button>
                  );
                })}
              </div>

              <div style={{ borderTop: '1px solid var(--border-subtle)' }}>
                <p style={{ padding: '8px 12px 4px', fontSize: '11px', fontWeight: 500, color: 'var(--text-tertiary)' }}>
                  Speaker tools
                </p>

                <button
                  onClick={handleAutoIdentifySpeakers}
                  style={{
                    width: '100%', textAlign: 'left',
                    padding: '7px 12px', fontSize: '12px',
                    color: 'var(--text-secondary)',
                    display: 'flex', alignItems: 'center', gap: '8px',
                    transition: 'background-color 100ms ease',
                  }}
                  onMouseEnter={e => (e.currentTarget as HTMLButtonElement).style.backgroundColor = 'var(--bg-surface)'}
                  onMouseLeave={e => (e.currentTarget as HTMLButtonElement).style.backgroundColor = 'transparent'}
                  title="Automatically identify speakers using enrolled voice prints"
                >
                  <svg className="w-3.5 h-3.5" style={{ color: 'var(--text-tertiary)', flexShrink: 0 }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
                  </svg>
                  Auto-identify speakers
                </button>

                <button
                  onClick={() => {
                    setShowEnrolledInDropdown(!showEnrolledInDropdown);
                  }}
                  style={{
                    width: '100%', textAlign: 'left',
                    padding: '7px 12px', fontSize: '12px',
                    color: showEnrolledInDropdown ? 'var(--accent)' : 'var(--text-secondary)',
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    transition: 'background-color 100ms ease',
                  }}
                  onMouseEnter={e => (e.currentTarget as HTMLButtonElement).style.backgroundColor = 'var(--bg-surface)'}
                  onMouseLeave={e => (e.currentTarget as HTMLButtonElement).style.backgroundColor = 'transparent'}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <svg className="w-3.5 h-3.5" style={{ color: 'var(--text-tertiary)', flexShrink: 0 }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
                    </svg>
                    Enrolled speakers
                    {enrolledSpeakers.length > 0 && (
                      <span style={{ fontSize: '10px', color: 'var(--text-tertiary)', background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', borderRadius: '9999px', padding: '0 5px' }}>
                        {enrolledSpeakers.length}
                      </span>
                    )}
                  </div>
                  <svg
                    className="w-3 h-3"
                    style={{ color: 'var(--text-tertiary)', transform: showEnrolledInDropdown ? 'rotate(180deg)' : 'rotate(0)', transition: 'transform 150ms ease' }}
                    fill="none" stroke="currentColor" viewBox="0 0 24 24"
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                  </svg>
                </button>

                {showEnrolledInDropdown && (
                  <div style={{ borderTop: '1px solid var(--border-subtle)', maxHeight: '200px', overflowY: 'auto' }}>
                    {enrolledLoading ? (
                      <div style={{ display: 'flex', justifyContent: 'center', padding: '16px 0' }}>
                        <div className="animate-spin" style={{ width: '16px', height: '16px', border: '2px solid var(--border-default)', borderTopColor: 'var(--accent)', borderRadius: '50%' }} />
                      </div>
                    ) : enrolledSpeakers.length === 0 ? (
                      <p style={{ padding: '12px', fontSize: '11px', color: 'var(--text-tertiary)', textAlign: 'center' }}>
                        No enrolled speakers. Click "Enroll" on a segment.
                      </p>
                    ) : (
                      enrolledSpeakers.map(sp => (
                        <div key={sp.name}>
                          {confirmingDeleteEnrolled === sp.name ? (
                            <div style={{ padding: '7px 12px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', backgroundColor: 'oklch(65% 0.20 25 / 0.06)' }}>
                              <span style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>Remove <strong style={{ color: 'var(--text-primary)' }}>{sp.name}</strong>?</span>
                              <div style={{ display: 'flex', gap: '6px' }}>
                                <button onClick={() => handleDeleteEnrolledSpeaker(sp.name)} style={{ fontSize: '11px', fontWeight: 600, color: 'var(--c-error)', background: 'none', border: 'none', cursor: 'pointer' }}>Yes</button>
                                <button onClick={() => setConfirmingDeleteEnrolled(null)} style={{ fontSize: '11px', color: 'var(--text-tertiary)', background: 'none', border: 'none', cursor: 'pointer' }}>No</button>
                              </div>
                            </div>
                          ) : (
                            <div
                              style={{ padding: '7px 12px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px' }}
                              onMouseEnter={e => (e.currentTarget as HTMLDivElement).style.backgroundColor = 'var(--bg-surface)'}
                              onMouseLeave={e => (e.currentTarget as HTMLDivElement).style.backgroundColor = 'transparent'}
                            >
                              <div>
                                <span style={{ fontSize: '12px', fontWeight: 500, color: 'var(--text-primary)' }}>{sp.name}</span>
                                <span style={{ fontSize: '10px', color: 'var(--text-tertiary)', marginLeft: '6px' }}>{sp.samples_count} sample{sp.samples_count !== 1 ? 's' : ''}</span>
                              </div>
                              <button
                                onClick={() => setConfirmingDeleteEnrolled(sp.name)}
                                style={{ background: 'none', border: 'none', cursor: 'pointer', padding: '2px', flexShrink: 0 }}
                                title="Remove enrolled speaker"
                              >
                                <svg className="w-3.5 h-3.5" style={{ color: 'var(--text-tertiary)' }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                                </svg>
                              </button>
                            </div>
                          )}
                        </div>
                      ))
                    )}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        <button
          onClick={() => setShowVisualMoments(!showVisualMoments)}
          className="btn-ghost"
          style={{
            padding: '4px 10px',
            fontSize: '12px',
            color: showVisualMoments ? 'var(--accent)' : 'var(--text-secondary)',
            backgroundColor: showVisualMoments ? 'var(--accent-dim)' : 'transparent',
          }}
          title="Show visual-only segments (silent frames captured from the video)"
        >
          <span>Scenes</span>
        </button>
      </div>
    </div>
  );
};
