interface TranscriptionErrorBannerProps {
  error: string;
  setError: (error: string | null) => void;
}

export const TranscriptionErrorBanner: React.FC<TranscriptionErrorBannerProps> = ({ error, setError }) => (
  <div
    className="mt-6 w-full"
    style={{
      padding: '12px 16px',
      borderRadius: '6px',
      backgroundColor: 'oklch(65% 0.20 25 / 0.08)',
      border: '1px solid oklch(65% 0.20 25 / 0.3)',
      display: 'flex',
      alignItems: 'flex-start',
      gap: '12px',
    }}
  >
    <svg style={{ width: '16px', height: '16px', color: 'var(--c-error)', flexShrink: 0, marginTop: '1px' }} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="10"></circle>
      <line x1="12" y1="8" x2="12" y2="12"></line>
      <line x1="12" y1="16" x2="12.01" y2="16"></line>
    </svg>
    <div style={{ flex: 1 }}>
      <p style={{ fontSize: '13px', fontWeight: 500, color: 'var(--c-error)', marginBottom: '2px' }}>Transcription failed</p>
      <p style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>{error}</p>
      <button
        onClick={() => setError(null)}
        style={{ marginTop: '8px', fontSize: '12px', color: 'var(--accent)', background: 'none', border: 'none', cursor: 'pointer', padding: 0, fontWeight: 500 }}
      >
        Try again
      </button>
    </div>
  </div>
);
