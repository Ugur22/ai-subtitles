import { describe, expect, it } from "vitest";
import { advancePhases, parseStreamSources, takeSseDataLines } from "./chatStream";
import type { PhaseEntry } from "./types";

describe("takeSseDataLines", () => {
  it("returns data payloads and keeps an incomplete trailing line buffered", () => {
    const { payloads, rest } = takeSseDataLines('data: {"type":"token"}\n\ndata: {"type":"do');

    expect(payloads).toEqual(['{"type":"token"}']);
    expect(rest).toBe('data: {"type":"do');
  });

  it("ignores non-data lines and strips CRLF endings", () => {
    const { payloads, rest } = takeSseDataLines(': keep-alive\r\nevent: x\r\ndata:{"a":1}\r\n');

    expect(payloads).toEqual(['{"a":1}']);
    expect(rest).toBe("");
  });

  it("reassembles a payload split across two reads", () => {
    const first = takeSseDataLines('data: {"type":"to');
    const second = takeSseDataLines(first.rest + 'ken"}\n');

    expect(first.payloads).toEqual([]);
    expect(second.payloads).toEqual(['{"type":"token"}']);
  });
});

describe("parseStreamSources", () => {
  const source = { start_time: "00:00:01", end_time: "00:00:02", start: 1, end: 2, speaker: "A" };

  it("drops null fields the backend sends for absent values", () => {
    const [parsed] = parseStreamSources([{ ...source, screenshot_url: null, confidence: null }]);

    expect(parsed).toEqual(source);
    expect("screenshot_url" in parsed).toBe(false);
  });

  it("rejects a source missing required fields", () => {
    expect(() => parseStreamSources([{ start_time: "00:00:01" }])).toThrow("Invalid chat source.");
  });
});

describe("advancePhases", () => {
  const searching: PhaseEntry = { id: "searching", label: "Searching", status: "active", startedAt: 1 };

  it("marks earlier phases done and appends the new active phase", () => {
    expect(advancePhases([searching], "generating", "Writing", 5)).toEqual([
      { ...searching, status: "done" },
      { id: "generating", label: "Writing", status: "active", startedAt: 5 },
    ]);
  });

  it("ignores a repeated heartbeat for the current phase", () => {
    const phases = [searching];

    expect(advancePhases(phases, "searching", "Searching", 9)).toBe(phases);
  });
});
