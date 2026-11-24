// @vitest-environment jsdom
import { act, renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { getJob, getJobVideoUrl, type TranscriptionResponse } from "../../../../services/api";
import type { Job } from "../../../../types/job";
import { useOpenJob } from "./useOpenJob";

vi.mock("../../../../services/api", () => ({
  getJob: vi.fn(),
  getJobVideoUrl: vi.fn(),
}));
vi.mock("react-hot-toast", () => ({ default: { error: vi.fn() } }));

const result = { video_hash: "hash-1" } as unknown as TranscriptionResponse;
const job = {
  job_id: "job-1",
  access_token: "token-1",
  result_json: result,
  video_url: "https://storage.example/video.mp4",
} as unknown as Job;

function renderOpenJob(initialEntry: string, jobs: Job[]) {
  const options = {
    jobs,
    isFresh: false,
    transcription: null,
    setTranscription: vi.fn(),
    setShowTranslation: vi.fn(),
    setVideoUrl: vi.fn(),
    setShowJobPanel: vi.fn(),
    closeTranscription: vi.fn(),
  };
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(MemoryRouter, { initialEntries: [initialEntry] }, children);
  const hook = renderHook((props: typeof options) => useOpenJob(props), {
    initialProps: options,
    wrapper,
  });
  return { ...hook, options };
}

afterEach(() => {
  vi.clearAllMocks();
});

describe("useOpenJob", () => {
  it("opens a deep-linked job once, even when the job list refreshes", async () => {
    const { options, rerender, result: hook } = renderOpenJob("/?job=job-1", [job]);

    await waitFor(() => expect(options.setTranscription).toHaveBeenCalledWith(result));
    expect(options.setVideoUrl).toHaveBeenCalledWith(job.video_url);
    expect(hook.current.currentJobId).toBe("job-1");
    expect(hook.current.currentAccessToken).toBe("token-1");

    // A job-list refetch hands over a new array while transcription is still null.
    rerender({ ...options, jobs: [{ ...job }] });
    rerender({ ...options, jobs: [{ ...job }], isFresh: true });

    expect(options.setTranscription).toHaveBeenCalledTimes(1);
    expect(options.closeTranscription).not.toHaveBeenCalled();
  });

  it("refreshes an expired video URL only once per opened video", async () => {
    vi.mocked(getJobVideoUrl).mockResolvedValue({ download_url: "https://storage.example/fresh.mp4" } as Awaited<
      ReturnType<typeof getJobVideoUrl>
    >);
    const { options, result: hook } = renderOpenJob("/", []);

    await act(() => hook.current.handleViewTranscript(job));
    expect(getJobVideoUrl).not.toHaveBeenCalled();

    await act(() => hook.current.handleVideoError());
    await act(() => hook.current.handleVideoError());

    expect(getJobVideoUrl).toHaveBeenCalledTimes(1);
    expect(getJobVideoUrl).toHaveBeenCalledWith("job-1", "token-1");
    expect(options.setVideoUrl).toHaveBeenLastCalledWith("https://storage.example/fresh.mp4");
    expect(getJob).not.toHaveBeenCalled();
  });

  it("does nothing on a video error before any job is opened", async () => {
    const { result: hook } = renderOpenJob("/", []);
    await act(() => hook.current.handleVideoError());
    expect(getJobVideoUrl).not.toHaveBeenCalled();
  });

  it("closes the transcription when the job param is removed", async () => {
    const { options, result: hook } = renderOpenJob("/?job=job-1", [job]);
    await waitFor(() => expect(options.setTranscription).toHaveBeenCalled());

    act(() => hook.current.closeJob());

    await waitFor(() => expect(options.closeTranscription).toHaveBeenCalledTimes(1));
  });
});
