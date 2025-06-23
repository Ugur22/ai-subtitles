import { useState, useEffect, useRef } from "react";
import {
  getSavedTranscriptions,
  loadSavedTranscription,
  deleteTranscription,
  SavedTranscription,
} from "../../../services/api";
import { useQueryClient } from "@tanstack/react-query";

interface SavedTranscriptionsPanelProps {
  onTranscriptionLoaded?: (videoHash?: string) => void;
  onImageClick?: (imageUrl: string) => void;
}

export const SavedTranscriptionsPanel = ({
  onTranscriptionLoaded,
  onImageClick,
}: SavedTranscriptionsPanelProps) => {
  const [transcriptions, setTranscriptions] = useState<SavedTranscription[]>(
    []
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [loadingTranscription, setLoadingTranscription] = useState(false);
  const [uploadingFile, setUploadingFile] = useState<string | null>(null);
  const [deletingFile, setDeletingFile] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const queryClient = useQueryClient();

  useEffect(() => {
    fetchTranscriptions();
  }, []);

  const fetchTranscriptions = async () => {
    try {
      setLoading(true);
      const response = await getSavedTranscriptions();
      setTranscriptions(response.transcriptions);
      setLoading(false);
    } catch (err) {
      console.error("Failed to load saved transcriptions:", err);
      setError("Failed to load saved transcriptions. Please try again.");
      setLoading(false);
    }
  };

  const handleLoadTranscription = async (hash: string) => {
    try {
      setLoadingTranscription(true);
      const transcriptionData = await loadSavedTranscription(hash);
      setLoadingTranscription(false);

      // Reset any cached data in react-query
      queryClient.invalidateQueries();

      // Callback to notify parent component with the video hash
      if (onTranscriptionLoaded) {
        onTranscriptionLoaded(hash);
      }
    } catch (err) {
      console.error("Failed to load transcription:", err);
      setLoadingTranscription(false);
      setError("Failed to load transcription. Please try again.");
    }
  };

  const handleUploadVideo = async (hash: string, file: File) => {
    try {
      setUploadingFile(hash);

      // Create a form data object
      const formData = new FormData();
      formData.append("file", file);

      // Send the request
      const response = await fetch(
        `http://localhost:8000/update_file_path/${hash}`,
        {
          method: "POST",
          body: formData,
        }
      );

      if (!response.ok) {
        throw new Error(`Failed to upload video: ${response.statusText}`);
      }

      // Get the updated file data
      const data = await response.json();
      console.log("Video uploaded successfully:", data);

      // Refresh the list
      await fetchTranscriptions();

      // Load the transcription if needed
      if (onTranscriptionLoaded) {
        onTranscriptionLoaded(hash);
      }
    } catch (error) {
      console.error("Error uploading video:", error);
      setError("Failed to upload video. Please try again.");
    } finally {
      setUploadingFile(null);
    }
  };

  const handleUploadClick = (hash: string) => {
    if (fileInputRef.current) {
      // Set a data attribute to keep track of which hash we're uploading for
      fileInputRef.current.dataset.hash = hash;
      fileInputRef.current.click();
    }
  };

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const hash = event.target.dataset.hash;
    const file = event.target.files?.[0];

    if (hash && file) {
      handleUploadVideo(hash, file);
    }

    // Reset the input
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  const handleDeleteTranscription = async (hash: string) => {
    try {
      if (
        !confirm(
          "Are you sure you want to delete this transcription? This action cannot be undone."
        )
      ) {
        return;
      }

      setDeletingFile(hash);

      // Send the delete request
      const response = await deleteTranscription(hash);
      console.log("Transcription deleted successfully:", response);

      // Refresh the list
      await fetchTranscriptions();
    } catch (error) {
      console.error("Error deleting transcription:", error);
      setError("Failed to delete transcription. Please try again.");
    } finally {
      setDeletingFile(null);
    }
  };

  const formatDate = (dateString: string) => {
    try {
      const date = new Date(dateString);
      return date.toLocaleDateString() + " " + date.toLocaleTimeString();
    } catch (e) {
      return dateString;
    }
  };

  return (
    <div className="card border rounded-lg overflow-hidden shadow-sm bg-white">
      {/* Hidden file input */}
      <input
        ref={fileInputRef}
        type="file"
        className="hidden"
        accept="video/*,audio/*"
        onChange={handleFileChange}
      />

      <div className="card-header p-4 border-b">
        <h3 className="text-lg font-medium text-gray-900">
          Saved Transcriptions
        </h3>
        <p className="text-sm text-gray-500 mt-1">
          Load a previously transcribed video
        </p>
      </div>

      <div className="card-body p-4">
        {loading ? (
          <div className="flex justify-center py-8">
            <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-gray-900"></div>
          </div>
        ) : error ? (
          <div className="p-4 text-red-800 border border-red-300 rounded-md bg-red-50">
            <p>{error}</p>
            <button
              onClick={() => fetchTranscriptions()}
              className="mt-2 text-sm text-blue-600 hover:text-blue-800"
            >
              Try Again
            </button>
          </div>
        ) : transcriptions.length === 0 ? (
          <div className="text-center py-8">
            <svg
              xmlns="http://www.w3.org/2000/svg"
              className="h-16 w-16 mx-auto text-gray-400"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.5}
                d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"
              />
            </svg>
            <p className="mt-2 text-gray-500">No saved transcriptions found.</p>
            <p className="text-sm text-gray-400">
              Transcriptions will be saved automatically when you process
              videos.
            </p>
          </div>
        ) : (
          <div className="overflow-y-auto max-h-[350px]">
            <ul className="divide-y divide-gray-200">
              {transcriptions.map((t) => (
                <li
                  key={t.video_hash}
                  className="py-3 hover:bg-gray-50 transition-colors"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center">
                      {t.thumbnail_url && (
                        <img
                          src={`http://localhost:8000${t.thumbnail_url}`}
                          alt={`Thumbnail for ${t.filename}`}
                          className="w-32 h-20 object-cover rounded-md mr-4 cursor-pointer transition-all duration-300 hover:scale-110 hover:shadow-xl"
                          onClick={() => {
                            if (onImageClick && t.thumbnail_url) {
                              onImageClick(
                                `http://localhost:8000${t.thumbnail_url}`
                              );
                            }
                          }}
                        />
                      )}
                      <div className="ml-2">
                        <h4 className="font-medium text-gray-900 truncate max-w-[200px]">
                          {t.filename}
                        </h4>
                        <p className="text-xs text-gray-500">
                          {formatDate(t.created_at)}
                        </p>
                        {!t.file_path && (
                          <span className="text-2xs text-amber-600">
                            Missing video file
                          </span>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center space-x-2">
                      {!t.file_path && (
                        <button
                          onClick={() => handleUploadClick(t.video_hash)}
                          disabled={uploadingFile === t.video_hash}
                          className={`px-3 py-1 text-xs font-medium rounded-md border transition-colors ${
                            uploadingFile === t.video_hash
                              ? "bg-gray-200 text-gray-500 border-gray-300 cursor-not-allowed"
                              : "bg-emerald-500 text-white border-emerald-600 hover:bg-emerald-600"
                          }`}
                        >
                          {uploadingFile === t.video_hash
                            ? "Uploading..."
                            : "Upload"}
                        </button>
                      )}
                      <button
                        onClick={() => handleLoadTranscription(t.video_hash)}
                        disabled={
                          loadingTranscription ||
                          deletingFile === t.video_hash ||
                          uploadingFile === t.video_hash
                        }
                        className="px-3 py-1 text-sm font-medium rounded-md border border-gray-300 bg-white text-gray-700 hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        {loadingTranscription ? "Loading..." : "Load"}
                      </button>
                      <button
                        onClick={() => handleDeleteTranscription(t.video_hash)}
                        disabled={
                          deletingFile === t.video_hash ||
                          loadingTranscription ||
                          uploadingFile === t.video_hash
                        }
                        className="px-3 py-1 text-sm font-medium rounded-md border border-red-300 bg-white text-red-600 hover:bg-red-50 disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        {deletingFile === t.video_hash
                          ? "Deleting..."
                          : "Delete"}
                      </button>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Refresh Button */}
        {!loading && transcriptions.length > 0 && (
          <button
            onClick={fetchTranscriptions}
            className="mt-4 w-full py-2 text-sm border border-gray-300 rounded-md bg-gray-50 text-gray-600 hover:bg-gray-100 transition-colors"
          >
            Refresh List
          </button>
        )}
      </div>
    </div>
  );
};
