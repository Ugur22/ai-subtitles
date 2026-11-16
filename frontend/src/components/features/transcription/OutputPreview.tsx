import React, { useEffect, useRef, useState } from "react";
import { secondsToTimeString } from "../../../utils/time";

const SAMPLE = [
  { start: 718, time: "00:11:58", speaker: "Lucía", dot: "bg-sp-3", name: "text-sp-3", original: "Ya están todos dentro.", translation: "Everyone is inside now." },
  { start: 724, time: "00:12:04", speaker: "Marta", dot: "bg-sp-1", name: "text-sp-1", original: "¿Dónde estabas anoche?", translation: "Where were you last night?" },
  { start: 727, time: "00:12:07", speaker: "Daniel", dot: "bg-sp-2", name: "text-sp-2", original: "En la estación. Esperándote.", translation: "At the station. Waiting for you." },
];
const SAMPLE_START = 718;
const SAMPLE_END = 734;

export const OutputPreview: React.FC = React.memo(() => {
  const [currentTime, setCurrentTime] = useState(724);
  const [isPlaying, setIsPlaying] = useState(false);
  const figureRef = useRef<HTMLElement>(null);
  const activeLine = SAMPLE.find((line, index) =>
    currentTime >= line.start && currentTime < (SAMPLE[index + 1]?.start ?? SAMPLE_END + 1)
  );

  useEffect(() => {
    if (!isPlaying) return;
    if (currentTime >= SAMPLE_END) {
      setIsPlaying(false);
      return;
    }
    const timeout = window.setTimeout(() => setCurrentTime(currentTime + 1), 1000);
    return () => window.clearTimeout(timeout);
  }, [isPlaying, currentTime]);

  useEffect(() => {
    const pauseWhenHidden = () => { if (document.hidden) setIsPlaying(false); };
    const observer = new IntersectionObserver(([entry]) => {
      if (!entry.isIntersecting) setIsPlaying(false);
    });
    if (figureRef.current) observer.observe(figureRef.current);
    document.addEventListener("visibilitychange", pauseWhenHidden);
    return () => {
      observer.disconnect();
      document.removeEventListener("visibilitychange", pauseWhenHidden);
    };
  }, []);

  return (
    <figure ref={figureRef} className="transcript-sample m-0 flex min-w-0 flex-col gap-3">
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
            <button type="button" className="sample-play flex h-11 w-11 shrink-0 items-center justify-center rounded-sm text-player-icon focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-player-icon" aria-label={isPlaying ? "Pause sample" : "Play sample"} onClick={() => {
              if (currentTime >= SAMPLE_END) setCurrentTime(SAMPLE_START);
              setIsPlaying(!isPlaying);
            }}>
              <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                <path d={isPlaying ? "M6 4h4v16H6zm8 0h4v16h-4z" : "M7 4.5v15l12-7.5z"} />
              </svg>
            </button>
            <input type="range" className="sample-seek min-w-0 flex-1" min={SAMPLE_START} max={SAMPLE_END} step={1} value={currentTime} onChange={event => setCurrentTime(Number(event.target.value))} aria-label="Sample playback position" aria-valuetext={`00:${secondsToTimeString(currentTime)}`} />
            <span className="sample-timestamp mono whitespace-nowrap text-xs tabular-nums text-player-icon">{`00:${secondsToTimeString(currentTime)}`} / 00:12:14</span>
          </div>
        </div>
        <ol className="m-0 flex list-none flex-col p-0">
          {SAMPLE.map(line => {
            const active = line === activeLine;
            return <li key={line.time}>
              <button type="button" onClick={() => setCurrentTime(line.start)} aria-label={`Seek sample to ${line.time}, ${line.speaker}`} aria-current={active ? "true" : undefined} className={`sample-transcript-row grid min-h-11 w-full items-baseline gap-2 rounded-sm px-3 py-2 text-left motion-safe:transition-colors motion-safe:duration-100 focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent ${active ? "bg-accent-dim ring-1 ring-inset ring-accent-border" : "hover:bg-subtle"}`}>
                <span className={`mono text-xs ${active ? "font-medium text-accent" : "text-text-tertiary"}`}>{line.time}</span>
                <span className="flex items-center gap-2 text-[13px] font-medium text-text-primary"><span className={`h-2 w-2 shrink-0 rounded-full ${line.dot}`} aria-hidden="true" />{line.speaker}</span>
                <span className="sample-transcript-text flex min-w-0 flex-col gap-0.5"><span className="text-sm text-text-primary">{line.original}</span><span className="text-[13px] text-text-tertiary">{line.translation}</span></span>
              </button>
            </li>;
          })}
        </ol>
      </div>
      <figcaption className="pl-2 text-xs leading-5 text-text-tertiary">Interactive sample · No audio. Play or select a row to follow the transcript.</figcaption>
    </figure>
  );
});
OutputPreview.displayName = "OutputPreview";
