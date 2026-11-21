import { useCallback, useLayoutEffect, useRef } from "react";

/** A callback whose identity never changes but always runs the latest render's `fn`, so memoized children don't re-render. */
export function useStableCallback<A extends unknown[], R>(fn: (...args: A) => R): (...args: A) => R {
  const latest = useRef(fn);
  useLayoutEffect(() => {
    latest.current = fn;
  });
  return useCallback((...args: A) => latest.current(...args), []);
}
