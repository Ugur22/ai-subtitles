// Timestamp pattern: [HH:MM:SS] or [HH:MM:SS - HH:MM:SS], optionally with
// fractional seconds ([HH:MM:SS.mmm]) since the LLM sometimes echoes the
// millisecond-precision timestamps it sees in its own context verbatim.
export const TIMESTAMP_REGEX =
  /\[(\d{1,2}:\d{2}:\d{2}(?:\.\d{1,3})?)(?:\s*-\s*(\d{1,2}:\d{2}:\d{2}(?:\.\d{1,3})?))?\]/g;

export const displayTimestamp = (ts: string): string => ts.split(".")[0];

export const formatSecondsToTimestamp = (seconds: number): string => {
  const safeSeconds = Math.max(0, Math.floor(seconds || 0));
  const h = Math.floor(safeSeconds / 3600);
  const m = Math.floor((safeSeconds % 3600) / 60);
  const s = safeSeconds % 60;
  return `${h.toString().padStart(2, "0")}:${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
};
