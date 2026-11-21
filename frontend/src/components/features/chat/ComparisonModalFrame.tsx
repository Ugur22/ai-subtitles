import type { Source } from "./types";

export const ComparisonModalFrame: React.FC<{
  source: Source;
  image: string;
  onTimestampClick?: (ts: string) => void;
}> = ({ source, image, onTimestampClick }) => (
  <div className="min-w-0">
    <div
      className="relative overflow-hidden rounded-lg border"
      style={{ borderColor: "var(--border-subtle)", background: "var(--bg-overlay)" }}
    >
      <img
        src={image}
        alt={`${source.evidence_label || "Comparison frame"} at ${source.start_time}`}
        className="max-h-[78vh] w-full object-contain"
      />
      {(source.bboxes || []).map(({ person, bbox }, idx) => bbox && (
        <span
          key={`${person || "face"}-${idx}`}
          title={person || "Face"}
          aria-label={person ? `${person} face box` : "Face box"}
          className="absolute rounded"
          style={{
            left: `${bbox.x * 100}%`,
            top: `${bbox.y * 100}%`,
            width: `${bbox.w * 100}%`,
            height: `${bbox.h * 100}%`,
            border: `2px solid ${idx === 0 ? "var(--accent)" : "#f59e0b"}`,
            boxShadow: idx === 0 ? "0 0 0 9999px rgb(0 0 0 / 0.12)" : "none",
          }}
        />
      ))}
      <div className="img-label absolute left-3 top-3">
        {source.evidence_label || "Comparison frame"}
      </div>
    </div>
    <div className="mt-2 flex items-center justify-between gap-3">
      <button
        type="button"
        onClick={() => onTimestampClick?.(source.start_time)}
        className="tc"
        title={`Jump to ${source.start_time}`}
      >
        {source.start_time}
      </button>
      <span className="truncate text-xs" style={{ color: "var(--text-tertiary)" }}>
        {source.speaker}
      </span>
    </div>
  </div>
);
