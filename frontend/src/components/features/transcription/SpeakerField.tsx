import React from "react";

interface Bar {
  height: number;
  tone: string;
}

const SPEAKER_TONES = ["bg-sp-1", "bg-sp-2", "bg-sp-3", "bg-sp-4", "bg-sp-5"];
const ODD_ROW_SPEAKER_COUNT = 3;
const SILENCE_TONE = "bg-border-default";
const ROWS = 8;
const BARS_PER_TILE = 72;
const FIXED_SEED = 7;

const seededRandom = (seed: number) => () => {
  seed = (seed * 16807) % 2147483647;
  return (seed - 1) / 2147483646;
};

const repeatForSpeakerDriftLoop = <T,>(tile: T[]): T[] => tile.concat(tile);

const buildRows = (): Bar[][] => {
  const rand = seededRandom(FIXED_SEED);

  return Array.from({ length: ROWS }, (_, row) => {
    const tile: Bar[] = [];
    const speakerCount = row % 2 ? ODD_ROW_SPEAKER_COUNT : SPEAKER_TONES.length;
    while (tile.length < BARS_PER_TILE) {
      const isSilence = rand() < 0.22;
      const run = isSilence ? 3 + Math.floor(rand() * 4) : 8 + Math.floor(rand() * 14);
      const tone = isSilence ? SILENCE_TONE : SPEAKER_TONES[Math.floor(rand() * speakerCount)];
      const phase = rand() * 6;
      for (let k = 0; k < run && tile.length < BARS_PER_TILE; k++) {
        const envelope = Math.sin((k / Math.max(run - 1, 1)) * Math.PI);
        const wobble = 0.55 + 0.45 * Math.abs(Math.sin(k * 0.9 + phase) * Math.cos(k * 0.37 + phase));
        const height = isSilence ? 4 : Math.max(4, Math.round((8 + 44 * envelope * wobble) / 2) * 2);
        tile.push({ height, tone });
      }
    }
    return repeatForSpeakerDriftLoop(tile);
  });
};

const ROW_DATA = buildRows();

export const SpeakerField: React.FC = React.memo(() => (
  <div
    aria-hidden="true"
    className="speaker-field-mask pointer-events-none absolute inset-0 flex flex-col justify-center gap-4 opacity-[0.18] lg:opacity-70"
  >
    {ROW_DATA.map((bars, row) => (
      <div key={row} className="h-14 overflow-hidden">
        <div className={`speaker-field-track flex h-14 w-max items-center gap-1 ${row % 2 ? "is-rev" : ""}`}>
          {bars.map((bar, i) => (
            <i
              key={i}
              className={`block w-1 shrink-0 rounded-[2px] ${bar.tone}`}
              style={{ height: bar.height }}
            />
          ))}
        </div>
      </div>
    ))}
  </div>
));
SpeakerField.displayName = "SpeakerField";
