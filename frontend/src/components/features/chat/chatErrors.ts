import axios from "axios";

export type FriendlyErrorType = "timeout" | "server" | "network" | "unknown";

export const getFriendlyErrorMessage = (error: unknown): { message: string; errorType: FriendlyErrorType } => {
  const isAxiosError = axios.isAxiosError<{ detail?: unknown }>(error);
  const status = isAxiosError ? error.response?.status : undefined;
  const code = isAxiosError ? error.code : undefined;
  const errorMessage = error instanceof Error ? error.message : "";

  if (status === 502 || status === 503 || status === 504) {
    return {
      message: "The server is temporarily unavailable, likely warming up. Please try again in a few seconds.",
      errorType: "server",
    };
  }
  if (code === "ECONNABORTED" || errorMessage.includes("timeout")) {
    return {
      message: "The request timed out. The server might be starting up — please try again in a moment.",
      errorType: "timeout",
    };
  }
  if (isAxiosError && !error.response && error.request) {
    return {
      message: "Could not reach the server. Please check your connection and try again.",
      errorType: "network",
    };
  }
  const detail = isAxiosError ? error.response?.data?.detail : undefined;
  if (detail && typeof detail === "string" && detail.length < 200) {
    return { message: detail, errorType: "unknown" };
  }
  return { message: "Something went wrong. Please try again.", errorType: "unknown" };
};
