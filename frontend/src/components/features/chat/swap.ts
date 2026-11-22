import { match } from "ts-pattern";
import type { SwapState } from "./types";

export interface SwapView {
  isSwapping: boolean;
  pendingBSeconds: number | null;
  pendingSwapTarget: "a" | "b" | null;
  swapError: string | undefined;
}

export const swapView = (swap: SwapState = { kind: "idle" }): SwapView =>
  match(swap)
    .with({ kind: "idle" }, () => ({ isSwapping: false, pendingBSeconds: null, pendingSwapTarget: null, swapError: undefined }))
    .with({ kind: "pending" }, ({ bSeconds, target }) => ({ isSwapping: true, pendingBSeconds: bSeconds, pendingSwapTarget: target, swapError: undefined }))
    .with({ kind: "failed" }, ({ error }) => ({ isSwapping: false, pendingBSeconds: null, pendingSwapTarget: null, swapError: error }))
    .exhaustive();
