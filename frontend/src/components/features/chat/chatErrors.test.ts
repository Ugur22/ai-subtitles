import { AxiosError, AxiosHeaders } from "axios";
import { describe, expect, it } from "vitest";
import { getFriendlyErrorMessage } from "./chatErrors";

function httpError(status: number, detail?: unknown) {
  const config = { headers: new AxiosHeaders() };
  return new AxiosError("Request failed", undefined, config, {}, {
    status,
    statusText: "",
    headers: {},
    config,
    data: { detail },
  });
}

describe("getFriendlyErrorMessage", () => {
  it("treats gateway errors as a warming-up server", () => {
    expect(getFriendlyErrorMessage(httpError(503)).errorType).toBe("server");
  });

  it("shows a short backend detail verbatim", () => {
    expect(getFriendlyErrorMessage(httpError(400, "No valid API key saved"))).toEqual({
      message: "No valid API key saved",
      errorType: "unknown",
    });
  });

  it("classifies timeouts and requests that never got a response", () => {
    expect(getFriendlyErrorMessage(new AxiosError("timeout", "ECONNABORTED")).errorType).toBe("timeout");
    const unreachable = new AxiosError("Network Error");
    unreachable.request = {};
    expect(getFriendlyErrorMessage(unreachable).errorType).toBe("network");
  });
});
