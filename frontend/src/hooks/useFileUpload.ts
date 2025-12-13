/**
 * useFileUpload - Custom hook for managing file upload with drag-and-drop
 * Handles file selection, drag events, and video URL creation
 */

import { useState, useRef } from "react";

interface UseFileUploadOptions {
  onFileSelected?: (file: File, videoUrl: string | null) => void;
}

export const useFileUpload = (options: UseFileUploadOptions = {}) => {
  const { onFileSelected } = options;

  const [file, setFile] = useState<File | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileChange = async (
    event: React.ChangeEvent<HTMLInputElement>
  ) => {
    const selectedFile = event.target.files?.[0];
    if (selectedFile) {
      setFile(selectedFile);

      // Create URL for video preview if it's a video file
      let url: string | null = null;
      if (selectedFile.type.startsWith("video/")) {
        url = URL.createObjectURL(selectedFile);
        setVideoUrl(url);
      } else {
        setVideoUrl(null);
      }

      // Notify parent component
      onFileSelected?.(selectedFile, url);
    }
  };

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  };

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);

    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      const droppedFile = e.dataTransfer.files[0];
      setFile(droppedFile);

      // Create and store video URL for dropped file if it's a video
      let url: string | null = null;
      if (droppedFile.type.startsWith("video/")) {
        url = URL.createObjectURL(droppedFile);
        setVideoUrl(url);
      } else {
        setVideoUrl(null);
      }

      // Notify parent component
      onFileSelected?.(droppedFile, url);
    }
  };

  const handleButtonClick = () => {
    fileInputRef.current?.click();
  };

  const resetFile = () => {
    setFile(null);
    setVideoUrl(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  return {
    file,
    dragActive,
    videoUrl,
    fileInputRef,
    handleFileChange,
    handleDrag,
    handleDrop,
    handleButtonClick,
    resetFile,
    setVideoUrl, // Exposed for cases where URL needs to be set externally
  };
};
