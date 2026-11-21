import { describe, expect, it } from "vitest";
import { parsePersonComparisonSection, splitIntoSections } from "./answerSections";
import { formatSecondsToTimestamp } from "./timestamps";

describe("splitIntoSections", () => {
  it("splits on ## headings and keeps a heading-less preamble", () => {
    expect(splitIntoSections("Intro\n## Direct Answer\nYes.\n## Evidence\n- a")).toEqual([
      { heading: "", body: "Intro" },
      { heading: "Direct Answer", body: "Yes." },
      { heading: "Evidence", body: "- a" },
    ]);
  });

  it("accepts the bold and deeper heading styles the LLM emits", () => {
    expect(splitIntoSections("**Summary:**\nShort.\n### Details\nLong.").map((s) => s.heading)).toEqual([
      "Summary",
      "Details",
    ]);
  });
});

describe("parsePersonComparisonSection", () => {
  it("extracts the fenced JSON metadata and returns the remaining prose", () => {
    const body = 'Before.\n```json\n{"person": "Vila"}\n```\nAfter.';

    expect(parsePersonComparisonSection(body)).toEqual({
      metadata: { person: "Vila" },
      prose: "Before.\n\nAfter.",
    });
  });

  it("falls back to prose when the JSON block is malformed", () => {
    expect(parsePersonComparisonSection("Text ```json {broken``` end")).toEqual({
      metadata: null,
      prose: "Text ```json {broken``` end",
    });
  });
});

describe("formatSecondsToTimestamp", () => {
  it("pads hours, minutes and seconds and clamps negatives", () => {
    expect(formatSecondsToTimestamp(3725.9)).toBe("01:02:05");
    expect(formatSecondsToTimestamp(-4)).toBe("00:00:00");
  });
});
