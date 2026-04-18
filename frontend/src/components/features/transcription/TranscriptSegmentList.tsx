import React from "react";
import { useSpring, animated } from "react-spring";
import { formatScreenshotUrl } from "../../../utils/url";

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
  getSpeakerColor: (speaker: string) => { bg: string; text: string; border: string };
  formatSpeakerLabel: (speaker: string) => string;
  onEnrollSpeaker?: (segment: Segment) => void;
}

const AnimatedSegment = ({
  segment,
  isActive,
  ...props
}: {
  segment: Segment;
  isActive: boolean;
  [key: string]: any;
}) => {
  const isSilent = segment.is_silent;

  // Only animate transform — colors handled via CSS vars
  const style = useSpring({
    transform: isActive ? "scale(1.01)" : "scale(1)",
    config: { tension: 300, friction: 20 },
  });

  return (
    <animated.div
      style={{
        ...style,
        backgroundColor: isActive
          ? 'var(--bg-surface)'
          : 'var(--bg-subtle)',
        borderColor: isActive
          ? 'var(--accent)'
          : isSilent
          ? 'var(--border-subtle)'
          : 'var(--border-subtle)',
        borderWidth: '1px',
        borderStyle: isSilent ? 'dashed' : 'solid',
        borderRadius: '8px',
        padding: '14px 16px',
        cursor: 'pointer',
        transition: 'border-color 150ms ease, background-color 150ms ease',
      }}
      id={`transcript-segment-${segment.id}`}
      onClick={props.onClick}
      role="button"
      tabIndex={0}
      onMouseEnter={e => {
        if (!isActive) (e.currentTarget as HTMLDivElement).style.borderColor = 'var(--border-default)';
      }}
      onMouseLeave={e => {
        if (!isActive) (e.currentTarget as HTMLDivElement).style.borderColor = 'var(--border-subtle)';
      }}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          props.onClick?.();
        }
      }}
      aria-label={`Transcript segment ${segment.id}: ${segment.text || 'Visual moment'}`}
    >
      {props.children}
    </animated.div>
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
      getSpeakerColor,
      formatSpeakerLabel,
      onEnrollSpeaker,
    }) => {
      return (
        <div style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
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
                No segments match the current speaker filter.
              </p>
            </div>
          ) : (
            segments.map((segment, index) => (
              <AnimatedSegment
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
                    <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: '6px', marginBottom: '8px' }}>
                      {/* Timestamp button */}
                      <button
                        onClick={(e) => { e.stopPropagation(); seekToTimestamp(segment.start_time); }}
                        style={{
                          display: 'inline-flex', alignItems: 'center', gap: '4px',
                          padding: '3px 8px', borderRadius: '4px', fontSize: '11px', fontWeight: 600,
                          fontVariantNumeric: 'tabular-nums', cursor: 'pointer',
                          backgroundColor: 'var(--accent-dim)', color: 'var(--accent)',
                          border: '1px solid var(--accent-border)',
                          transition: 'opacity 100ms ease',
                        }}
                        title="Jump to timestamp"
                        aria-label={`Jump to timestamp ${segment.start_time}`}
                      >
                        <svg style={{ width: '11px', height: '11px' }} fill="currentColor" viewBox="0 0 20 20">
                          <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM9.555 7.168A1 1 0 008 8v4a1 1 0 001.555.832l3-2a1 1 0 000-1.664l-3-2z" clipRule="evenodd" />
                        </svg>
                        {segment.start_time}
                      </button>

                      <span style={{ fontSize: '11px', color: 'var(--text-tertiary)' }}>→</span>
                      <span style={{ fontSize: '11px', color: 'var(--text-tertiary)', fontVariantNumeric: 'tabular-nums' }}>
                        {segment.end_time}
                      </span>

                      {segment.is_silent ? (
                        <span style={{
                          display: 'inline-flex', alignItems: 'center', gap: '4px',
                          padding: '2px 8px', borderRadius: '9999px', fontSize: '11px', fontWeight: 500,
                          backgroundColor: 'var(--bg-overlay)', color: 'var(--text-tertiary)',
                          border: '1px solid var(--border-subtle)',
                        }}>
                          <svg style={{ width: '11px', height: '11px' }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
                          </svg>
                          Visual
                        </span>
                      ) : (
                        <>
                          {/* Speaker edit mode */}
                          {segment.speaker && editingSegmentId === segment.id && (
                            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }} onClick={(e) => e.stopPropagation()}>
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
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
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
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M6 18L18 6M6 6l12 12" />
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
                              className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium border ${getSpeakerColor(segment.speaker).bg} ${getSpeakerColor(segment.speaker).text} ${getSpeakerColor(segment.speaker).border}`}
                              title="Click to rename speaker"
                              aria-label={`Edit speaker: ${formatSpeakerLabel(segment.speaker!)}`}
                            >
                              <svg style={{ width: '11px', height: '11px' }} fill="currentColor" viewBox="0 0 20 20">
                                <path fillRule="evenodd" d="M10 9a3 3 0 100-6 3 3 0 000 6zm-7 9a7 7 0 1114 0H3z" clipRule="evenodd" />
                              </svg>
                              {formatSpeakerLabel(segment.speaker)}
                            </button>
                          )}

                          {/* Enroll button */}
                          {segment.speaker && onEnrollSpeaker && (
                            <button
                              onClick={(e) => { e.stopPropagation(); onEnrollSpeaker(segment); }}
                              style={{
                                display: 'inline-flex', alignItems: 'center', gap: '3px',
                                padding: '2px 7px', borderRadius: '4px', fontSize: '11px', fontWeight: 500,
                                backgroundColor: 'var(--bg-overlay)', color: 'var(--text-secondary)',
                                border: '1px solid var(--border-default)', cursor: 'pointer',
                                transition: 'border-color 100ms ease, color 100ms ease',
                              }}
                              onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.color = 'var(--text-primary)'; }}
                              onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.color = 'var(--text-secondary)'; }}
                              title="Enroll this speaker for automatic recognition"
                            >
                              <svg style={{ width: '11px', height: '11px' }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6v6m0 0v6m0-6h6m-6 0H6" />
                              </svg>
                              Enroll
                            </button>
                          )}
                        </>
                      )}

                      {/* Segment number */}
                      <span style={{
                        marginLeft: 'auto', fontSize: '10px', fontWeight: 500, fontVariantNumeric: 'tabular-nums',
                        color: 'var(--text-tertiary)', backgroundColor: 'var(--bg-overlay)',
                        border: '1px solid var(--border-subtle)', padding: '1px 6px', borderRadius: '9999px',
                      }}>
                        {index + 1}
                      </span>
                    </div>

                    {/* Text content */}
                    {segment.is_silent ? (
                      <p style={{ fontSize: '13px', color: 'var(--text-tertiary)', fontStyle: 'italic' }}>
                        No speech during this segment
                      </p>
                    ) : (
                      <p style={{
                        fontSize: '14px',
                        lineHeight: '1.6',
                        color: activeSegmentId === segment.id ? 'var(--text-primary)' : 'var(--text-secondary)',
                        fontWeight: activeSegmentId === segment.id ? 500 : 400,
                        transition: 'color 150ms ease',
                      }}>
                        {showTranslation && segment.translation ? (
                          <>
                            {segment.translation}
                            <span style={{ display: 'block', fontSize: '12px', color: 'var(--text-tertiary)', fontStyle: 'italic', marginTop: '6px' }}>
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
              </AnimatedSegment>
            ))
          )}
        </div>
      );
    }
  );
