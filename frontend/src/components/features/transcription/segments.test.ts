import { describe, expect, it } from "vitest";
import { filterDisplayedSegments, listUniqueSpeakers, type TranscriptSegment } from "./segments";

function segment(id: string, speaker: string, isSilent = false): TranscriptSegment {
  return { id, speaker, is_silent: isSilent, start_time: "00:00:00", end_time: "00:00:01", text: id } as TranscriptSegment;
}

const segments = [segment("a1", "A"), segment("b1", "B"), segment("scene", "", true), segment("a2", "A")];
const ids = (list: TranscriptSegment[]) => list.map((s) => s.id);

describe("filterDisplayedSegments", () => {
  it("shows everything without a speaker filter, hiding silent scenes when toggled off", () => {
    expect(ids(filterDisplayedSegments(segments, null, true))).toEqual(["a1", "b1", "scene", "a2"]);
    expect(ids(filterDisplayedSegments(segments, null, false))).toEqual(["a1", "b1", "a2"]);
  });

  it("keeps the filtered speaker plus silent scenes only when scenes are on", () => {
    expect(ids(filterDisplayedSegments(segments, "A", true))).toEqual(["a1", "scene", "a2"]);
    expect(ids(filterDisplayedSegments(segments, "A", false))).toEqual(["a1", "a2"]);
  });
});

describe("listUniqueSpeakers", () => {
  it("returns sorted distinct speakers and skips empty labels", () => {
    expect(listUniqueSpeakers([segment("1", "B"), segment("2", "A"), segment("3", "B"), segment("4", "")])).toEqual(["A", "B"]);
  });
});
