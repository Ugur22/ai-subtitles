import { type OrbState } from "thinking-orbs";
import type { PhaseId } from "./types";

export function isPhaseId(value: unknown): value is PhaseId {
  return typeof value === "string" && Object.prototype.hasOwnProperty.call(ORB_STATE, value);
}

// The orb's color prop takes hex/rgb only, so resolve the oklch --accent token to rgb.
export function readAccentRgb(): string | undefined {
  const accent = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim();
  const ctx = document.createElement("canvas").getContext("2d");
  if (!accent || !ctx) return undefined;
  ctx.fillStyle = accent;
  ctx.fillRect(0, 0, 1, 1);
  const [r, g, b] = ctx.getImageData(0, 0, 1, 1).data;
  return `rgb(${r}, ${g}, ${b})`;
}

export const ORB_STATE: Record<PhaseId, OrbState> = {
  searching: "searching",
  analyzing_scenes: "shaping",
  analyzing_visuals: "shaping",
  matching_faces: "connecting",
  comparing: "solving",
  analyzing_audio: "listening",
  generating: "composing",
};

export const PHASE_LABELS: Record<PhaseId, string> = {
  searching: "Searching transcript",
  analyzing_scenes: "Analyzing scenes",
  analyzing_visuals: "Inspecting screenshots",
  matching_faces: "Matching faces",
  comparing: "Comparing person states",
  analyzing_audio: "Scanning audio events",
  generating: "Writing answer",
};
