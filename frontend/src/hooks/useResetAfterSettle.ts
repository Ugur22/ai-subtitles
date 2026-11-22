import { useEffect } from "react";

interface SettlingMutation {
  status: "idle" | "pending" | "success" | "error";
  submittedAt: number;
  reset: () => void;
}

export function useResetAfterSettle(
  { status, submittedAt, reset }: SettlingMutation,
  delayMs: { success: number; error: number },
) {
  const delay = status === "success" ? delayMs.success : status === "error" ? delayMs.error : undefined;

  useEffect(() => {
    if (delay === undefined) return;
    const timer = setTimeout(reset, delay);
    return () => clearTimeout(timer);
  }, [delay, submittedAt, reset]);
}
