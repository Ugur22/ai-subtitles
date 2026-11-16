import React from "react";
import { SpeakerField } from "./SpeakerField";

interface SampleLine {
  time: string;
  speaker: string;
  dot: string;
  name: string;
  original: string;
  translation: string;
  active?: boolean;
  onScreen?: boolean;
}

const SAMPLE: SampleLine[] = [
  { time: "00:11:58", speaker: "Lucía", dot: "bg-sp-3", name: "text-sp-3", original: "Ya están todos dentro.", translation: "Everyone is inside now." },
  { time: "00:12:04", speaker: "Marta", dot: "bg-sp-1", name: "text-sp-1", original: "¿Dónde estabas anoche?", translation: "Where were you last night?", active: true, onScreen: true },
  { time: "00:12:07", speaker: "Daniel", dot: "bg-sp-2", name: "text-sp-2", original: "En la estación. Esperándote.", translation: "At the station. Waiting for you.", onScreen: true },
];

const ON_SCREEN = SAMPLE.filter((line) => line.onScreen);

export const OutputPreview: React.FC = React.memo(() => (
  <figure className="m-0 flex min-w-0 flex-[1_1_520px] flex-col gap-3">
    <div className="flex flex-wrap items-center justify-between gap-2 px-2 text-[11px] text-text-tertiary">
      <span className="font-medium uppercase tracking-[0.12em]">Inside the transcript</span>
      <span className="mono">ES → EN · 3 speakers · Sample</span>
    </div>
    <div className="relative">
      <SpeakerField />
      <div className="relative flex flex-col gap-2 rounded-[18px] border border-border-subtle bg-surface p-2 shadow-lg">
        <div className="dark relative aspect-video overflow-hidden rounded-md bg-[linear-gradient(180deg,oklch(26%_0.014_250),oklch(17%_0.010_250))]">
          <div className="absolute inset-x-0 bottom-12 flex flex-col items-center gap-1 px-8 text-center text-lg font-medium text-on-scrim [text-shadow:0_1px_2px_oklch(0%_0_0/0.6)]">
            {ON_SCREEN.map((line) => (
              <p key={line.time} className="m-0">
                <span className={line.name}>{line.speaker}</span>&ensp;{line.translation}
              </p>
            ))}
          </div>
          <div className="absolute inset-x-4 bottom-4 flex items-center gap-3">
            <svg className="h-3.5 w-3.5 text-player-icon" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
              <path d="M7 4.5v15l12-7.5z" />
            </svg>
            <span className="relative h-[3px] flex-1 rounded-full bg-player-track">
              <span className="absolute inset-y-0 left-0 w-[24%] rounded-full bg-player-icon" />
            </span>
            <span className="mono text-[11px] text-player-icon">00:12:04 / 00:50:12</span>
          </div>
        </div>

        <ol className="m-0 flex list-none flex-col p-0">
          {SAMPLE.map((line) => (
            <li
              key={line.time}
              className={`grid grid-cols-[56px_minmax(0,1fr)] sm:grid-cols-[72px_88px_minmax(0,1fr)] items-baseline gap-3 rounded-sm px-4 py-3 ${
                line.active ? "bg-accent-dim ring-1 ring-inset ring-accent-border" : ""
              }`}
            >
              <span className={`mono text-xs ${line.active ? "font-medium text-accent" : "text-text-tertiary"}`}>
                {line.time}
              </span>
              <span className="flex items-center gap-2 text-[13px] font-medium text-text-primary">
                <span className={`h-2 w-2 shrink-0 rounded-full ${line.dot}`} aria-hidden="true" />
                {line.speaker}
              </span>
              <span className="col-start-2 flex min-w-0 flex-col gap-0.5 sm:col-start-auto">
                <span className="text-sm text-text-primary">{line.original}</span>
                <span className="text-[13px] text-text-tertiary">{line.translation}</span>
              </span>
            </li>
          ))}
        </ol>
      </div>
    </div>
    <figcaption className="pl-2 text-xs text-text-tertiary">
      What you get back: a transcript with speakers named, translated, synced to the video
    </figcaption>
  </figure>
));
OutputPreview.displayName = "OutputPreview";
