/**
 * FaceTagOverlay - Renders face bounding boxes on a screenshot image
 * Handles coordinate mapping between original image dims and displayed size.
 * Click a box to assign a speaker name via popover.
 */

import React, { useState, useRef, useEffect, useCallback } from "react";
import {
  DetectedFace,
  tagFace,
} from "../../../services/api";

interface FaceTagOverlayProps {
  faces: DetectedFace[];
  imageRef: React.RefObject<HTMLImageElement | null>;
  videoHash: string;
  screenshotUrl: string;
  speakers: string[];
  onTagSaved: () => void;
}

export const FaceTagOverlay: React.FC<FaceTagOverlayProps> = ({
  faces,
  imageRef,
  videoHash,
  screenshotUrl,
  speakers,
  onTagSaved,
}) => {
  const [selectedFaceIdx, setSelectedFaceIdx] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [imageDims, setImageDims] = useState({ width: 0, height: 0 });
  const overlayRef = useRef<HTMLDivElement>(null);

  // Track displayed image dimensions for coordinate mapping
  const updateDims = useCallback(() => {
    if (imageRef.current) {
      const rect = imageRef.current.getBoundingClientRect();
      setImageDims({ width: rect.width, height: rect.height });
    }
  }, [imageRef]);

  useEffect(() => {
    updateDims();
    window.addEventListener("resize", updateDims);
    return () => window.removeEventListener("resize", updateDims);
  }, [updateDims]);

  // Close popover on outside click
  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (
        overlayRef.current &&
        !overlayRef.current.contains(e.target as Node)
      ) {
        setSelectedFaceIdx(null);
      }
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const handleTagFace = async (faceIdx: number, speakerName: string) => {
    const face = faces[faceIdx];
    if (!face) return;

    setSaving(true);
    try {
      await tagFace(videoHash, screenshotUrl, speakerName, face.bbox);
      setSelectedFaceIdx(null);
      onTagSaved();
    } catch (error) {
      console.error("Failed to tag face:", error);
    } finally {
      setSaving(false);
    }
  };

  if (!imageDims.width || !imageDims.height || faces.length === 0) {
    return null;
  }

  return (
    <div
      ref={overlayRef}
      className="absolute inset-0 pointer-events-none"
      style={{ width: imageDims.width, height: imageDims.height }}
    >
      {faces.map((face, idx) => {
        const { x, y, w, h } = face.bbox;
        const left = x * imageDims.width;
        const top = y * imageDims.height;
        const width = w * imageDims.width;
        const height = h * imageDims.height;
        const isSelected = selectedFaceIdx === idx;

        return (
          <div key={idx}>
            {/* Bounding box */}
            <div
              className="absolute pointer-events-auto cursor-pointer transition-all"
              style={{
                left: `${left}px`,
                top: `${top}px`,
                width: `${width}px`,
                height: `${height}px`,
                borderRadius: "4px",
                border: isSelected
                  ? `3px solid var(--accent)`
                  : `2px solid oklch(70% 0.18 145 / 0.5)`,
                boxShadow: isSelected ? `0 0 0 4px var(--accent-dim)` : 'none',
              }}
              onClick={(e) => {
                e.stopPropagation();
                setSelectedFaceIdx(isSelected ? null : idx);
              }}
            >
              {/* Confidence badge */}
              <div
                className="absolute -top-5 left-0 px-1.5 py-0.5 text-[10px] rounded whitespace-nowrap font-mono tabular-nums"
                style={{
                  background: 'var(--bg-overlay)',
                  color: 'var(--text-primary)',
                  border: '1px solid var(--border-subtle)',
                }}
              >
                {(face.confidence * 100).toFixed(0)}%
              </div>
            </div>

            {/* Speaker assignment popover */}
            {isSelected && (
              <div
                className="absolute pointer-events-auto z-50 rounded-lg p-2 min-w-[160px] border"
                style={{
                  left: `${left + width + 8}px`,
                  top: `${top}px`,
                  maxHeight: "200px",
                  overflowY: "auto",
                  background: 'var(--bg-overlay)',
                  borderColor: 'var(--border-subtle)',
                  boxShadow: 'var(--shadow-overlay)',
                }}
              >
                <div
                  className="text-xs font-medium px-2 py-1 mb-1"
                  style={{ color: 'var(--text-tertiary)' }}
                >
                  Assign speaker
                </div>
                {speakers.length === 0 ? (
                  <div
                    className="text-xs px-2 py-1"
                    style={{ color: 'var(--text-tertiary)' }}
                  >
                    No speakers found
                  </div>
                ) : (
                  speakers.map((name) => (
                    <button
                      key={name}
                      disabled={saving}
                      onClick={(e) => {
                        e.stopPropagation();
                        handleTagFace(idx, name);
                      }}
                      className="w-full text-left px-2 py-1.5 text-sm rounded transition-colors disabled:opacity-50 hover:[background:var(--accent-dim)] hover:[color:var(--accent)]"
                      style={{ color: 'var(--text-primary)' }}
                    >
                      {name}
                    </button>
                  ))
                )}
                {saving && (
                  <div
                    className="text-xs px-2 py-1 mt-1"
                    style={{ color: 'var(--accent)' }}
                  >
                    Saving...
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
};
