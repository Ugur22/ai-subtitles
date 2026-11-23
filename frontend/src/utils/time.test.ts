import { afterEach, describe, expect, it, vi } from "vitest";
import { timeToSeconds } from "./time";

describe("timeToSeconds", () => {
  afterEach(() => vi.restoreAllMocks());

  it("parses HH:MM:SS", () => {
    expect(timeToSeconds("01:02:03")).toBe(3723);
  });

  it("keeps fractional seconds", () => {
    expect(timeToSeconds("00:00:05.250")).toBeCloseTo(5.25);
  });

  it("returns 0 for the wrong number of parts", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    expect(timeToSeconds("02:03")).toBe(0);
    expect(timeToSeconds("")).toBe(0);
  });

  it("returns 0 instead of NaN for non-numeric parts", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    expect(timeToSeconds("aa:bb:cc")).toBe(0);
  });
});
