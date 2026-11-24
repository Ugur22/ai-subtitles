import React from "react";

import { timeToSeconds } from "../../../utils/time";

const SAMPLE_DURATION = "00:45:00";
const SAMPLE = [
  { time: "00:11:58", speaker: "Lucía", dot: "bg-sp-3", name: "text-sp-3", original: "Ya están todos dentro.", translation: "Everyone is inside now." },
  { time: "00:12:04", speaker: "Marta", dot: "bg-sp-1", name: "text-sp-1", original: "¿Dónde estabas anoche?", translation: "Where were you last night?" },
  { time: "00:12:07", speaker: "Daniel", dot: "bg-sp-2", name: "text-sp-2", original: "En la estación. Esperándote.", translation: "At the station. Waiting for you." },
];
export const OutputPreview: React.FC = React.memo(() => {
  const activeLine = SAMPLE[1];
  const progress = timeToSeconds(activeLine.time) / timeToSeconds(SAMPLE_DURATION);

  return (
    <figure className="transcript-sample m-0 flex min-w-0 flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2 px-2 text-[11px] text-text-tertiary">
        <span className="font-medium uppercase tracking-[0.12em]">Inside the transcript</span>
        <span className="mono">ES → EN · 3 speakers · Sample</span>
      </div>
      <div className="flex flex-col gap-2 rounded-xl border border-border-subtle bg-surface p-2">
        <div className="sample-player dark relative aspect-video max-h-[220px] min-h-[168px] overflow-hidden rounded-md bg-[linear-gradient(180deg,oklch(26%_0.014_250),oklch(17%_0.010_250))]">
          <div className="sample-caption absolute inset-x-0 bottom-16 px-4 text-center text-sm font-medium sm:text-base">
            {activeLine && <p className="m-0 text-on-scrim"><span className={activeLine.name}>{activeLine.speaker}</span>&ensp;{activeLine.translation}</p>}
          </div>
          <div className="sample-controls absolute inset-x-3 bottom-2">
            <span className="sample-play flex h-11 w-11 shrink-0 items-center justify-center text-player-icon" aria-hidden="true">
              <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="currentColor"><path d="M7 4.5v15l12-7.5z" /></svg>
            </span>
            <div className="h-1 rounded-full bg-[var(--player-track)] [grid-area:seek]" aria-hidden="true">
              <div className="h-full rounded-full bg-player-icon" style={{ width: `${progress * 100}%` }} />
            </div>
            <span className="sample-timestamp mono whitespace-nowrap text-xs tabular-nums text-player-icon">{activeLine.time} / {SAMPLE_DURATION}</span>
          </div>
        </div>
        <ol className="m-0 flex list-none flex-col p-0">
          {SAMPLE.map(line => {
            const active = line === activeLine;
            return <li key={line.time}>
              <div className={`sample-transcript-row grid min-h-11 w-full items-baseline gap-2 rounded-sm px-3 py-2 text-left ${active ? "bg-accent-dim ring-1 ring-inset ring-accent-border" : ""}`}>
                <span className={`mono text-xs ${active ? "font-medium text-accent" : "text-text-tertiary"}`}>{line.time}</span>
                <span className="flex items-center gap-2 text-[13px] font-medium text-text-primary"><span className={`h-2 w-2 shrink-0 rounded-full ${line.dot}`} aria-hidden="true" />{line.speaker}</span>
                <span className="sample-transcript-text flex min-w-0 flex-col gap-0.5"><span className="text-sm text-text-primary">{line.original}</span><span className="text-[13px] text-text-tertiary">{line.translation}</span></span>
              </div>
            </li>;
          })}
        </ol>
      </div>
      <figcaption className="pl-2 text-xs leading-5 text-text-tertiary">Example transcript · Speaker labels, translation, and synced subtitles.</figcaption>
    </figure>
  );
});
OutputPreview.displayName = "OutputPreview";
