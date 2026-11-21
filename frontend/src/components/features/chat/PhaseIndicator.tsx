import { useState, useEffect, useMemo } from "react";
import { ThinkingOrb } from "thinking-orbs";
import { useTheme } from "../../../hooks/useTheme";
import { ORB_STATE, readAccentRgb } from "./phases";
import type { PhaseEntry } from "./types";

export const PhaseIndicator: React.FC<{
  phases: PhaseEntry[];
  screenshotCount?: number;
}> = ({ phases, screenshotCount }) => {
  const { theme } = useTheme();
  const orbInk = useMemo(readAccentRgb, [theme]);
  const hasActive = phases.some((p) => p.status === "active");
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!hasActive) return;
    const id = window.setInterval(() => setTick((t) => t + 1), 1000);
    return () => window.clearInterval(id);
  }, [hasActive]);

  if (phases.length === 0) return null;
  return (
    <div className="flex flex-col gap-1.5 mb-3">
      {phases.map((phase) => {
        const isActive = phase.status === "active";
        const elapsedSec = isActive
          ? Math.max(0, Math.floor((Date.now() - phase.startedAt) / 1000))
          : 0;
        const displayLabel =
          isActive && phase.id === "generating" && screenshotCount && screenshotCount > 0
            ? `Analyzing ${screenshotCount} screenshot${screenshotCount === 1 ? "" : "s"}`
            : phase.label;
        return (
          <div
            key={phase.id}
            className={`flex items-center gap-2 whitespace-nowrap ${isActive ? "text-sm" : "text-xs"}`}
            style={{
              color: isActive ? "var(--text-primary)" : "var(--text-tertiary)",
            }}
          >
            <span className="phase-icon">
            {phase.status === "done" ? (
              <svg
                className="w-3.5 h-3.5"
                style={{ color: "var(--text-tertiary)" }}
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={1.5}
                  d="M5 13l4 4L19 7"
                />
              </svg>
            ) : (
              <ThinkingOrb
                size={32}
                state={ORB_STATE[phase.id]}
                color={orbInk}
                aria-hidden="true"
              />
            )}
            </span>
            <span
              style={{
                color: isActive ? "var(--text-primary)" : undefined,
              }}
            >
              {displayLabel}
            </span>
            {isActive && elapsedSec >= 2 && (
              <span className="mono" style={{ color: "var(--text-tertiary)" }}>
                {elapsedSec}s
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
};
