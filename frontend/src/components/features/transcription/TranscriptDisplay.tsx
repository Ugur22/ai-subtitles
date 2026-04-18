import { useState } from "react";

interface Word {
  word: string;
  start: string;
  end: string;
  speaker: string;
}

interface Segment {
  id: number;
  start_time: string;
  end_time: string;
  text: string;
  speaker: string;
  words?: Word[];
}

interface Transcription {
  segments: Segment[];
  language: string;
  duration: string;
}

interface TranscriptDisplayProps {
  transcription: Transcription;
}

export const TranscriptDisplay = ({
  transcription,
}: TranscriptDisplayProps) => {
  const [displayMode, setDisplayMode] = useState<"segments" | "words">(
    "segments"
  );
  const [selectedSegment, setSelectedSegment] = useState<number | null>(null);

  const handleTimeClick = (time: string) => {
    // Could be used to sync with video player in future
    console.log("Clicked time:", time);
  };

  // Speaker palette: 5 distinct hues at consistent L/C, all token-aware
  const speakerStyles = (speaker: string): React.CSSProperties => {
    const palette: Array<{ bg: string; text: string }> = [
      { bg: 'oklch(70% 0.18 145 / 0.15)', text: 'oklch(75% 0.14 145)' }, // emerald (accent)
      { bg: 'oklch(70% 0.10 240 / 0.15)', text: 'oklch(75% 0.10 240)' }, // slate-blue
      { bg: 'oklch(70% 0.12 80 / 0.15)',  text: 'oklch(75% 0.12 80)'  }, // amber
      { bg: 'oklch(70% 0.12 320 / 0.15)', text: 'oklch(75% 0.12 320)' }, // magenta
      { bg: 'oklch(70% 0.12 35 / 0.15)',  text: 'oklch(75% 0.12 35)'  }, // ember
    ];
    const hash = speaker.split('').reduce((acc, ch) => ch.charCodeAt(0) + acc, 0);
    const c = palette[hash % palette.length];
    return { background: c.bg, color: c.text };
  };
  const speakerTextColor = (speaker: string): string => {
    return (speakerStyles(speaker).color as string) ?? 'var(--text-primary)';
  };

  return (
    <div className="p-4">
      {/* Display Mode Controls */}
      <div className="flex gap-2 mb-6">
        <button
          onClick={() => setDisplayMode("segments")}
          className={displayMode === "segments" ? "btn-primary" : "btn-ghost"}
        >
          Segment View
        </button>
        <button
          onClick={() => setDisplayMode("words")}
          className={displayMode === "words" ? "btn-primary" : "btn-ghost"}
        >
          Word View
        </button>
      </div>

      {/* Transcript Content */}
      <div className="space-y-2">
        {transcription.segments.map((segment, index) => {
          const isSelected = selectedSegment === index;
          return (
            <div
              key={segment.id}
              className="p-4 rounded-lg border transition-colors duration-150 cursor-pointer"
              style={{
                background: isSelected ? 'var(--accent-dim)' : 'var(--bg-surface)',
                borderColor: isSelected ? 'var(--accent-border)' : 'var(--border-subtle)',
              }}
              onClick={() => setSelectedSegment(index)}
            >
              {/* Segment Header */}
              <div className="flex items-center justify-between mb-3">
                <button
                  onClick={() => handleTimeClick(segment.start_time)}
                  className="flex items-center gap-2 text-xs font-mono tabular-nums transition-colors"
                  style={{ color: 'var(--accent)' }}
                >
                  <svg className="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor">
                    <path
                      fillRule="evenodd"
                      d="M10 18a8 8 0 100-16 8 8 0 000 16zM9.555 7.168A1 1 0 008 8v4a1 1 0 001.555.832l3-2a1 1 0 000-1.664l-3-2z"
                      clipRule="evenodd"
                    />
                  </svg>
                  <span>{segment.start_time} – {segment.end_time}</span>
                </button>
                <span
                  className="px-2 py-0.5 text-xs font-medium rounded-full"
                  style={speakerStyles(segment.speaker)}
                >
                  {segment.speaker}
                </span>
              </div>

              {/* Content */}
              {displayMode === "segments" ? (
                <p
                  className="text-sm leading-relaxed"
                  style={{ color: 'var(--text-primary)' }}
                >
                  {segment.text}
                </p>
              ) : (
                <div className="flex flex-wrap gap-1">
                  {segment.words?.map((word, wordIndex) => (
                    <div
                      key={wordIndex}
                      className="group relative"
                      title={`${word.start} - ${word.end}`}
                    >
                      <span
                        className="text-sm rounded px-1 py-0.5 cursor-pointer transition-colors hover:[background:var(--bg-subtle)]"
                        style={{ color: speakerTextColor(word.speaker) }}
                      >
                        {word.word}
                      </span>
                      <div
                        className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 px-2 py-1 text-xs rounded opacity-0 group-hover:opacity-100 transition-opacity z-10 border font-mono tabular-nums"
                        style={{
                          background: 'var(--bg-overlay)',
                          color: 'var(--text-primary)',
                          borderColor: 'var(--border-subtle)',
                        }}
                      >
                        {word.start}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Statistics */}
      <div className="mt-8 grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: 'Total Segments', value: transcription.segments.length },
          { label: 'Duration', value: transcription.duration },
          { label: 'Language', value: transcription.language, capitalize: true },
          {
            label: 'Total Words',
            value: transcription.segments.reduce(
              (acc, segment) => acc + (segment.words?.length || 0),
              0
            ),
          },
        ].map((stat) => (
          <div key={stat.label} className="surface-panel p-4">
            <div
              className="text-xs uppercase tracking-wider mb-1"
              style={{ color: 'var(--text-tertiary)' }}
            >
              {stat.label}
            </div>
            <div
              className={`text-xl font-semibold tabular-nums ${stat.capitalize ? 'capitalize' : ''}`}
              style={{ color: 'var(--text-primary)' }}
            >
              {stat.value}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
