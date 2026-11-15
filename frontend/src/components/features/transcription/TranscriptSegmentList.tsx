import React from "react";
import { formatScreenshotUrl } from "../../../utils/url";
import { getSpeakerIndex } from "../../../utils/speaker";

interface Segment {
  id: string;
  start_time: string;
  end_time: string;
  text: string;
  translation?: string | null;
  speaker?: string;
  screenshot_url?: string;
  is_silent?: boolean;
}

interface TranscriptSegmentListProps {
  segments: Segment[];
  activeSegmentId: string | null;
  showTranslation: boolean;
  seekToTimestamp: (timestamp: string) => void;
  openImageModal: (imageUrl: string) => void;
  editingSegmentId: string | null;
  setEditingSegmentId: (segmentId: string | null) => void;
  editSpeakerName: string;
  setEditSpeakerName: (name: string) => void;
  handleSpeakerRename: (speaker: string) => void;
  isRenamingSpeaker: boolean;
  formatSpeakerLabel: (speaker: string) => string;
  onEnrollSpeaker?: (segment: Segment) => void;
}

interface SegmentRowProps {
  segment: Segment;
  isActive: boolean;
  onClick?: () => void;
  children?: React.ReactNode;
}

const SegmentRow = ({
  segment,
  isActive,
  ...props
}: SegmentRowProps) => {
  const isSilent = segment.is_silent;

  return (
    <div
      style={{
        backgroundColor: isActive ? 'var(--accent-dim)' : 'transparent',
        borderRadius: 'var(--radius-sm)',
        padding: '12px',
        cursor: 'pointer',
        position: 'relative',
        border: isSilent ? '1px dashed var(--border-subtle)' : '1px solid transparent',
        transition: 'background-color 150ms var(--ease-out), border-color 150ms var(--ease-out)',
      }}
      id={`transcript-segment-${segment.id}`}
      onClick={props.onClick}
      role="button"
      tabIndex={0}
      onMouseEnter={e => {
        if (!isActive) (e.currentTarget as HTMLDivElement).style.backgroundColor = 'var(--bg-subtle)';
      }}
      onMouseLeave={e => {
        if (!isActive) (e.currentTarget as HTMLDivElement).style.backgroundColor = 'transparent';
      }}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          props.onClick?.();
        }
      }}
      aria-label={`Transcript segment ${segment.id}: ${segment.text || 'Visual moment'}`}
    >
      {isActive && (
        <span
          aria-hidden="true"
          style={{
            position: 'absolute',
            left: 0,
            top: 8,
            bottom: 8,
            width: 3,
            background: 'var(--accent)',
            borderRadius: '0 2px 2px 0',
          }}
        />
      )}
      {props.children}
    </div>
  );
};

export const TranscriptSegmentList: React.FC<TranscriptSegmentListProps> =
  React.memo(
    ({
      segments,
      activeSegmentId,
      showTranslation,
      seekToTimestamp,
      openImageModal,
      editingSegmentId,
      setEditingSegmentId,
      editSpeakerName,
      setEditSpeakerName,
      handleSpeakerRename,
      isRenamingSpeaker,
      formatSpeakerLabel,
      onEnrollSpeaker,
    }) => {
      return (
        <div style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
          {segments.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '48px 16px' }}>
              <div style={{
                width: '40px', height: '40px', margin: '0 auto 12px',
                backgroundColor: 'var(--bg-overlay)', borderRadius: '50%',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}>
                <svg style={{ width: '20px', height: '20px', color: 'var(--text-tertiary)' }} fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z" />
                </svg>
              </div>
              <p style={{ fontSize: '14px', fontWeight: 500, color: 'var(--text-secondary)', marginBottom: '4px' }}>
                No segments found
              </p>
              <p style={{ fontSize: '13px', color: 'var(--text-tertiary)' }}>
                No segments match the current speaker filter
              </p>
            </div>
          ) : (
            segments.map((segment, index) => (
              <SegmentRow
                key={segment.id}
                segment={segment}
                isActive={activeSegmentId === segment.id}
                onClick={() => seekToTimestamp(segment.start_time)}
              >
                <div style={{ display: 'flex', alignItems: 'flex-start', gap: '12px', flexDirection: segment.is_silent ? 'column' : 'row' }}>
                  {/* Thumbnail */}
                  {segment.screenshot_url && (
                    <div style={{ flexShrink: 0, ...(segment.is_silent ? { width: '100%' } : {}) }}>
                      <img
                        src={formatScreenshotUrl(segment.screenshot_url)}
                        alt={`Screenshot at ${segment.start_time}`}
                        style={{
                          objectFit: 'cover',
                          borderRadius: '6px',
                          cursor: 'pointer',
                          border: '1px solid var(--border-subtle)',
                          transition: 'opacity 150ms ease',
                          ...(segment.is_silent
                            ? { width: '100%', height: '180px' }
                            : { width: '80px', height: '80px' }),
                        }}
                        onClick={(e) => {
                          e.stopPropagation();
                          openImageModal(formatScreenshotUrl(segment.screenshot_url) || "");
                        }}
                        role="button"
                        tabIndex={0}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault();
                            e.stopPropagation();
                            openImageModal(formatScreenshotUrl(segment.screenshot_url) || "");
                          }
                        }}
                        aria-label={`View full screenshot at ${segment.start_time}`}
                      />
                    </div>
                  )}

                  <div style={{ flex: 1, minWidth: 0 }}>
                    {/* Meta row */}
                    <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: '8px', marginBottom: '8px' }}>
                      {/* Timestamp button */}
                      <button
                        onClick={(e) => { e.stopPropagation(); seekToTimestamp(segment.start_time); }}
                        className="tc"
                        data-active={activeSegmentId === segment.id}
                        title="Jump to timestamp"
                        aria-label={`Jump to timestamp ${segment.start_time}`}
                      >
                        {segment.start_time}
                      </button>

                      <span className="mono" style={{ fontSize: '11px', color: 'var(--text-quaternary)' }}>
                        –
                      </span>
                      <span className="mono" style={{ fontSize: '11px', color: 'var(--text-tertiary)' }}>
                        {segment.end_time}
                      </span>

                      {segment.is_silent ? (
                        <span className="badge badge-default gap-1">
                          <svg style={{ width: '12px', height: '12px' }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
                          </svg>
                          Visual
                        </span>
                      ) : (
                        <>
                          {/* Speaker edit mode */}
                          {segment.speaker && editingSegmentId === segment.id && (
                            <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }} onClick={(e) => e.stopPropagation()}>
                              <input
                                type="text"
                                value={editSpeakerName}
                                onChange={(e) => setEditSpeakerName(e.target.value)}
                                className="input-base"
                                style={{ padding: '2px 8px', fontSize: '12px', width: '120px' }}
                                autoFocus
                                disabled={isRenamingSpeaker}
                                onKeyDown={(e) => {
                                  if (e.key === "Enter") handleSpeakerRename(segment.speaker!);
                                  if (e.key === "Escape") setEditingSegmentId(null);
                                  e.stopPropagation();
                                }}
                                onClick={(e) => e.stopPropagation()}
                                aria-label="Edit speaker name"
                              />
                              <button
                                onClick={(e) => { e.stopPropagation(); handleSpeakerRename(segment.speaker!); }}
                                disabled={isRenamingSpeaker}
                                style={{ padding: '2px 6px', fontSize: '11px', color: 'var(--c-success)', background: 'none', border: '1px solid var(--c-success)', borderRadius: '4px', cursor: isRenamingSpeaker ? 'not-allowed' : 'pointer', opacity: isRenamingSpeaker ? 0.7 : 1 }}
                                title="Save"
                              >
                                {isRenamingSpeaker ? (
                                  <svg style={{ width: '12px', height: '12px', animation: 'spin 0.8s linear infinite' }} fill="none" viewBox="0 0 24 24">
                                    <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" strokeDasharray="31.4" strokeDashoffset="10" strokeLinecap="round" />
                                  </svg>
                                ) : (
                                  <svg style={{ width: '12px', height: '12px' }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M5 13l4 4L19 7" />
                                  </svg>
                                )}
                              </button>
                              <button
                                onClick={(e) => { e.stopPropagation(); setEditingSegmentId(null); }}
                                disabled={isRenamingSpeaker}
                                style={{ padding: '2px 6px', fontSize: '11px', color: 'var(--c-error)', background: 'none', border: '1px solid var(--c-error)', borderRadius: '4px', cursor: isRenamingSpeaker ? 'not-allowed' : 'pointer', opacity: isRenamingSpeaker ? 0.5 : 1 }}
                                title="Cancel"
                              >
                                <svg style={{ width: '12px', height: '12px' }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M6 18L18 6M6 6l12 12" />
                                </svg>
                              </button>
                            </div>
                          )}

                          {/* Speaker badge (click to rename) */}
                          {segment.speaker && editingSegmentId !== segment.id && (
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                e.preventDefault();
                                setEditingSegmentId(segment.id);
                                setEditSpeakerName(formatSpeakerLabel(segment.speaker!));
                              }}
                              className="sp-pill"
                              data-sp={getSpeakerIndex(segment.speaker)}
                              title="Click to rename speaker"
                              aria-label={`Edit speaker: ${formatSpeakerLabel(segment.speaker!)}`}
                            >
                              <span className="sp-dot" />
                              {formatSpeakerLabel(segment.speaker)}
                            </button>
                          )}

                          {/* Enroll button */}
                          {segment.speaker && onEnrollSpeaker && (
                            <button
                              onClick={(e) => { e.stopPropagation(); onEnrollSpeaker(segment); }}
                              className="badge badge-default gap-1 cursor-pointer transition-colors"
                              title="Enroll this speaker for automatic recognition"
                            >
                              <svg style={{ width: '12px', height: '12px' }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 6v6m0 0v6m0-6h6m-6 0H6" />
                              </svg>
                              Enroll
                            </button>
                          )}
                        </>
                      )}

                      {/* Segment number */}
                      <span className="mono" style={{ marginLeft: 'auto', fontSize: '11px', color: 'var(--text-quaternary)' }}>
                        {index + 1}
                      </span>
                    </div>

                    {/* Text content */}
                    {segment.is_silent ? (
                      <p style={{ fontSize: '13px', color: 'var(--text-tertiary)' }}>
                        No speech in this segment
                      </p>
                    ) : (
                      <p style={{
                        fontSize: '14px',
                        lineHeight: '1.6',
                        color: activeSegmentId === segment.id ? 'var(--text-primary)' : 'var(--text-secondary)',
                        transition: 'color 150ms ease',
                      }}>
                        {showTranslation && segment.translation ? (
                          <>
                            {segment.translation}
                            <span style={{ display: 'block', fontSize: '12px', color: 'var(--text-tertiary)', marginTop: '8px' }}>
                              Original: {segment.text}
                            </span>
                          </>
                        ) : (
                          segment.text
                        )}
                      </p>
                    )}
                  </div>
                </div>
              </SegmentRow>
            ))
          )}
        </div>
      );
    }
  );
