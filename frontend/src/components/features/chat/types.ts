import type { FaceBbox } from "../../../services/api";
import type { FriendlyErrorType } from "./chatErrors";
export type ReasoningEffort = "low" | "medium" | "high" | "xhigh";

export interface ComparisonFrame {
  url?: string;
  timestamp_seconds?: number;
  timestamp?: string;
  bbox?: FaceBbox | null;
  bboxes?: Array<{
    person?: string;
    bbox?: FaceBbox | null;
  }>;
  label?: string;
  people?: string[];
}

export interface TimelineFrame {
  url: string;
  timestamp: string;
  timestamp_seconds: number;
  bbox?: FaceBbox | null;
  similarity?: number;
  low_confidence?: boolean;
}

export interface PersonComparisonData {
  person?: string;
  secondary_person?: string;
  frame_a?: ComparisonFrame;
  frame_b?: ComparisonFrame;
  timeline?: TimelineFrame[];
}

export interface Source {
  start_time: string;
  end_time: string;
  start: number;
  end: number;
  speaker: string;
  text?: string;
  screenshot_url?: string;
  type?: "text" | "visual" | "audio";
  event_type?: string;
  confidence?: number;
  likely_speakers?: string[];
  overlap_score?: number;
  visual_query_variant?: string;
  visual_similarity?: number;
  hybrid_score?: number;
  face_score?: number;
  source_kind?: "clip" | "face_tag" | string;
  evidence_label?: string;
  bboxes?: Array<{
    person?: string;
    bbox?: FaceBbox | null;
  }>;
}

export function isChatSource(value: unknown): value is Source {
  if (!value || typeof value !== "object") return false;
  const required = ["start_time", "end_time", "speaker"];
  const strings = ["text", "screenshot_url", "event_type", "visual_query_variant", "source_kind", "evidence_label"];
  const numbers = ["confidence", "overlap_score", "visual_similarity", "hybrid_score", "face_score"];
  const fields = Object.fromEntries(Object.entries(value));
  return required.every((key) => typeof fields[key] === "string")
    && typeof fields.start === "number" && typeof fields.end === "number"
    && strings.every((key) => fields[key] === undefined || typeof fields[key] === "string")
    && numbers.every((key) => fields[key] === undefined || typeof fields[key] === "number")
    && (fields.type === undefined || fields.type === "text" || fields.type === "visual" || fields.type === "audio")
    && (fields.likely_speakers === undefined || (Array.isArray(fields.likely_speakers) && fields.likely_speakers.every((speaker: unknown) => typeof speaker === "string")))
    && (fields.bboxes === undefined || (Array.isArray(fields.bboxes) && fields.bboxes.every((item: unknown) => {
      if (!item || typeof item !== "object") return false;
      if ("person" in item && item.person !== undefined && typeof item.person !== "string") return false;
      if (!("bbox" in item) || item.bbox == null) return true;
      const box = item.bbox;
      return typeof box === "object" && "x" in box && typeof box.x === "number"
        && "y" in box && typeof box.y === "number" && "w" in box && typeof box.w === "number"
        && "h" in box && typeof box.h === "number";
    })));
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
  visual_query_used?: string;
  visual_query_variants?: string[];
  original_question?: string;
  status: MessageStatus;
  swap?: SwapState;
}

export type MessageStatus =
  | { kind: "streaming"; phases: PhaseEntry[]; screenshotCount: number }
  | { kind: "done" }
  | { kind: "error"; errorType: FriendlyErrorType; retryQuestion?: string };

export type SwapState =
  | { kind: "idle" }
  | { kind: "pending"; bSeconds: number; target: "a" | "b" }
  | { kind: "failed"; error: string };

export type PhaseId =
  | "searching"
  | "analyzing_scenes"
  | "analyzing_visuals"
  | "matching_faces"
  | "comparing"
  | "analyzing_audio"
  | "generating";

export interface PhaseEntry {
  id: PhaseId;
  label: string;
  status: "active" | "done";
  startedAt: number;
}

export interface ChatProviderStatus {
  name: string;
  available: boolean;
  model: string;
}

export interface ScreenshotModalState {
  currentIndex: number;
  sources: Source[];
}
