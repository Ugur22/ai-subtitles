import { isChatSource } from "./types";
import type { PhaseEntry, PhaseId, Source } from "./types";

export function takeSseDataLines(buffer: string): { payloads: string[]; rest: string } {
  const payloads: string[] = [];
  let rest = buffer;
  let newline: number;
  while ((newline = rest.indexOf("\n")) !== -1) {
    const line = rest.slice(0, newline).replace(/\r$/, "");
    rest = rest.slice(newline + 1);
    if (line.startsWith("data:")) payloads.push(line.slice(5).trim());
  }
  return { payloads, rest };
}

export function parseStreamSources(rawSources: unknown[]): Source[] {
  return rawSources.map((source: unknown) => {
    const normalized: unknown = source && typeof source === "object"
      ? Object.fromEntries(Object.entries(source).filter(([, value]) => value !== null)) : source;
    if (!isChatSource(normalized)) throw new Error("Invalid chat source.");
    return normalized;
  });
}

export function advancePhases(previous: PhaseEntry[], id: PhaseId, label: string, now: number): PhaseEntry[] {
  if (previous.at(-1)?.id === id) return previous;
  return [...previous.map((phase): PhaseEntry => ({ ...phase, status: "done" })),
    { id, label, status: "active", startedAt: now }];
}
