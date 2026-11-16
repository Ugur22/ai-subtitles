import React, { useId } from "react";

interface Bar {
  height: number;
  tone: string;
}

const SPEAKER_TONES = ["fill-sp-1", "fill-sp-2", "fill-sp-3", "fill-sp-4", "fill-sp-5"];
const ODD_ROW_SPEAKER_COUNT = 3;
const SILENCE_TONE = "fill-border-default";
const ROWS = 8;
const ROW_HEIGHT = 56;
const BARS_PER_TILE = 72;
const BAR_WIDTH = 4;
const BAR_STEP = 8;
const TILE_WIDTH = BARS_PER_TILE * BAR_STEP;
const FIXED_SEED = 7;

const seededRandom = (seed: number) => () => {
  seed = (seed * 16807) % 2147483647;
  return (seed - 1) / 2147483646;
};

const buildTiles = (): Bar[][] => {
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
    return tile;
  });
};

const TILES = buildTiles();

export const SpeakerField: React.FC = React.memo(() => {
  const idPrefix = useId().replace(/:/g, "");

  return (
    <div
      aria-hidden="true"
      className="speaker-field-mask pointer-events-none absolute inset-0 hidden flex-col justify-center gap-4 opacity-70 lg:flex"
      style={{ "--speaker-tile": `${TILE_WIDTH}px` } as React.CSSProperties}
    >
      {TILES.map((tile, row) => {
        const patternId = `${idPrefix}-row-${row}`;
        return (
          <div key={row} className="overflow-hidden" style={{ height: ROW_HEIGHT }}>
            <svg className={`speaker-field-track block ${row % 2 ? "is-rev" : ""}`} height={ROW_HEIGHT}>
              <defs>
                <pattern id={patternId} width={TILE_WIDTH} height={ROW_HEIGHT} patternUnits="userSpaceOnUse">
                  {tile.map((bar, i) => (
                    <rect
                      key={i}
                      className={bar.tone}
                      x={i * BAR_STEP}
                      y={(ROW_HEIGHT - bar.height) / 2}
                      width={BAR_WIDTH}
                      height={bar.height}
                      rx={2}
                    />
                  ))}
                </pattern>
              </defs>
              <rect width="100%" height={ROW_HEIGHT} fill={`url(#${patternId})`} />
            </svg>
          </div>
        );
      })}
    </div>
  );
});
SpeakerField.displayName = "SpeakerField";
