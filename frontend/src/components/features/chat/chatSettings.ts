import type { ReasoningEffort } from "./types";

export const EFFORT_LABELS: Record<ReasoningEffort, string> = {
  low: "Low · faster",
  medium: "Medium",
  high: "High · more thinking",
  xhigh: "Extra high · most thinking",
};

export const FIELD_LABEL_CLASS = "text-xs font-medium w-[4.5rem] shrink-0";

export const FIELD_WIDTH_CLASS = "w-56";

export const PROVIDER_LABELS: Record<string, string> = {
  grok: "Grok (xAI)",
  openai: "OpenAI",
  anthropic: "Claude (Anthropic)",
  groq: "Groq",
  deepseek: "DeepSeek",
  ollama: "Ollama (local)",
};

export const VISION_SUPPORTED_PROVIDERS = ["grok", "openai", "anthropic", "deepseek"];
