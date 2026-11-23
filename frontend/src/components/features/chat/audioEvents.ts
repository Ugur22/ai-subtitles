import type { IconType } from "react-icons";
import { LuSpeech, LuAudioWaveform } from "react-icons/lu";

export const EVENT_CATEGORY_ICON: Record<string, IconType> = {
  speech: LuSpeech,
  sound: LuAudioWaveform,
  other: LuAudioWaveform,
};

export const getEventDetails = (eventType: string) => {
  const type = eventType.toLowerCase();

  if (type.includes("sigh")) {
    return { label: "Sigh", category: "speech" };
  }
  if (type.includes("gasp")) {
    return { label: "Gasp", category: "speech" };
  }
  if (type.includes("moan")) {
    return { label: "Moan", category: "speech" };
  }
  if (type.includes("groan")) {
    return { label: "Groan", category: "speech" };
  }
  if (type.includes("panting")) {
    return { label: "Panting", category: "speech" };
  }
  if (type.includes("huff") || type.includes("huffing")) {
    return { label: "Huffing", category: "speech" };
  }
  if (type.includes("scream")) {
    return { label: "Scream", category: "speech" };
  }
  if (type.includes("whimper")) {
    return { label: "Whimper", category: "speech" };
  }
  if (type.includes("sniff") || type.includes("sniffle")) {
    return { label: "Sniffling", category: "speech" };
  }
  if (type.includes("yawn")) {
    return { label: "Yawn", category: "speech" };
  }
  if (type.includes("sneeze")) {
    return { label: "Sneeze", category: "speech" };
  }
  if (type.includes("cough")) {
    return { label: "Cough", category: "speech" };
  }
  if (type.includes("hiccup")) {
    return { label: "Hiccup", category: "speech" };
  }

  if (type.includes("breath") || type.includes("breathing")) {
    return { label: "Breathing", category: "speech" };
  }
  if (type.includes("exhale")) {
    return { label: "Exhale", category: "speech" };
  }
  if (type.includes("inhale")) {
    return { label: "Inhale", category: "speech" };
  }

  if (
    type.includes("speech") ||
    type.includes("speaking") ||
    type.includes("narration")
  ) {
    return { label: "Speech", category: "speech" };
  }
  if (type.includes("laugh")) {
    return { label: "Laughter", category: "speech" };
  }
  if (type.includes("giggle") || type.includes("chuckle")) {
    return { label: "Giggling", category: "speech" };
  }
  if (type.includes("cry") || type.includes("sobbing")) {
    return { label: "Crying", category: "speech" };
  }
  if (type.includes("shout") || type.includes("yell")) {
    return { label: "Shouting", category: "speech" };
  }
  if (type.includes("whisper")) {
    return { label: "Whisper", category: "speech" };
  }
  if (type.includes("cheer")) {
    return { label: "Cheering", category: "speech" };
  }
  if (type.includes("hum") || type.includes("humming")) {
    return { label: "Humming", category: "speech" };
  }
  if (type.includes("sing")) {
    return { label: "Singing", category: "speech" };
  }

  if (type.includes("clap") || type.includes("applause")) {
    return { label: "Applause", category: "sound" };
  }
  if (type.includes("snap") || type.includes("finger snap")) {
    return { label: "Snap", category: "sound" };
  }
  if (type.includes("footstep") || type.includes("step")) {
    return { label: "Footsteps", category: "sound" };
  }
  if (type.includes("knock")) {
    return { label: "Knocking", category: "sound" };
  }
  if (type.includes("tap") || type.includes("tapping")) {
    return { label: "Tapping", category: "sound" };
  }
  if (type.includes("stomp")) {
    return { label: "Stomping", category: "sound" };
  }

  if (type.includes("music") || type.includes("melody")) {
    return { label: "Music", category: "sound" };
  }
  if (
    type.includes("silence") ||
    type.includes("ambient") ||
    type.includes("quiet")
  ) {
    return { label: "Silence", category: "sound" };
  }
  if (type.includes("noise")) {
    return { label: "Noise", category: "sound" };
  }

  const label = eventType.charAt(0).toUpperCase() + eventType.slice(1);
  return { label, category: "other" };
};
