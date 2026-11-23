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

  it.each(["02:03", "", "01:02:03:04", "aa:bb:cc"])("returns 0 for malformed %j", (input) => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    expect(timeToSeconds(input)).toBe(0);
  });
});
