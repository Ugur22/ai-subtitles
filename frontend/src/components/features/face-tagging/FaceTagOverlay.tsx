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
              className={`absolute pointer-events-auto cursor-pointer transition-all ${
                isSelected
                  ? "border-3 border-indigo-400 shadow-lg shadow-indigo-400/30"
                  : "border-2 border-green-400 hover:border-indigo-400"
              }`}
              style={{
                left: `${left}px`,
                top: `${top}px`,
                width: `${width}px`,
                height: `${height}px`,
                borderRadius: "4px",
              }}
              onClick={(e) => {
                e.stopPropagation();
                setSelectedFaceIdx(isSelected ? null : idx);
              }}
            >
              {/* Confidence badge */}
              <div className="absolute -top-5 left-0 px-1.5 py-0.5 bg-black/70 text-white text-[10px] rounded whitespace-nowrap">
                {(face.confidence * 100).toFixed(0)}%
              </div>
            </div>

            {/* Speaker assignment popover */}
            {isSelected && (
              <div
                className="absolute pointer-events-auto z-50 bg-white rounded-lg shadow-xl border border-gray-200 p-2 min-w-[160px]"
                style={{
                  left: `${left + width + 8}px`,
                  top: `${top}px`,
                  maxHeight: "200px",
                  overflowY: "auto",
                }}
              >
                <div className="text-xs font-medium text-gray-500 px-2 py-1 mb-1">
                  Assign speaker
                </div>
                {speakers.length === 0 ? (
                  <div className="text-xs text-gray-400 px-2 py-1">
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
                      className="w-full text-left px-2 py-1.5 text-sm rounded hover:bg-indigo-50 hover:text-indigo-700 transition-colors disabled:opacity-50"
                    >
                      {name}
                    </button>
                  ))
                )}
                {saving && (
                  <div className="text-xs text-indigo-500 px-2 py-1 mt-1">
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
