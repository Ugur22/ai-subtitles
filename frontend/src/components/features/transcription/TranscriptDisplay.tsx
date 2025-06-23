import { useState } from "react";

interface Word {
  word: string;
  start: string;
  end: string;
  speaker: string;
}

interface Segment {
  id: number;
  start_time: string;
  end_time: string;
  text: string;
  speaker: string;
  words?: Word[];
}

interface Transcription {
  segments: Segment[];
  language: string;
  duration: string;
}

interface TranscriptDisplayProps {
  transcription: Transcription;
}

export const TranscriptDisplay = ({
  transcription,
}: TranscriptDisplayProps) => {
  const [displayMode, setDisplayMode] = useState<"segments" | "words">(
    "segments"
  );
  const [selectedSegment, setSelectedSegment] = useState<number | null>(null);

  const handleTimeClick = (time: string) => {
    // Could be used to sync with video player in future
    console.log("Clicked time:", time);
  };

  const getSpeakerColor = (speaker: string) => {
    // Generate consistent colors for speakers
    const colors = [
      "text-violet-600 bg-violet-50 border-violet-200",
      "text-rose-600 bg-rose-50 border-rose-200",
      "text-orange-600 bg-orange-50 border-orange-200",
      "text-pink-600 bg-pink-50 border-pink-200",
      "text-purple-600 bg-purple-50 border-purple-200",
    ];
    const hash = speaker
      .split("")
      .reduce((acc, char) => char.charCodeAt(0) + acc, 0);
    return colors[hash % colors.length];
  };

  return (
    <div className="p-4">
      {/* Display Mode Controls */}
      <div className="flex space-x-2 mb-6">
        <button
          onClick={() => setDisplayMode("segments")}
          className={`px-4 py-2 text-sm rounded-md transition ${
            displayMode === "segments"
              ? "bg-violet-600 text-gray-900 shadow-sm"
              : "bg-white text-gray-600 hover:bg-gray-100 border border-gray-200"
          }`}
        >
          Segment View
        </button>
        <button
          onClick={() => setDisplayMode("words")}
          className={`px-4 py-2 text-sm rounded-md transition ${
            displayMode === "words"
              ? "bg-violet-600 text-gray-900 shadow-sm"
              : "bg-white text-gray-600 hover:bg-gray-100 border border-gray-200"
          }`}
        >
          Word View
        </button>
      </div>

      {/* Transcript Content */}
      <div className="space-y-4">
        {transcription.segments.map((segment, index) => {
          const speakerColorClasses = getSpeakerColor(segment.speaker);

          return (
            <div
              key={segment.id}
              className={`p-4 rounded-lg border transition duration-200 ${
                selectedSegment === index
                  ? "bg-rose-50 border-rose-300 shadow-sm"
                  : "bg-white border-gray-200 hover:border-gray-300"
              }`}
              onClick={() => setSelectedSegment(index)}
            >
              {/* Segment Header */}
              <div className="flex items-center justify-between mb-3">
                <button
                  onClick={() => handleTimeClick(segment.start_time)}
                  className="flex items-center space-x-2 text-sm text-violet-600 hover:text-violet-800"
                >
                  <svg
                    className="w-4 h-4"
                    viewBox="0 0 20 20"
                    fill="currentColor"
                  >
                    <path
                      fillRule="evenodd"
                      d="M10 18a8 8 0 100-16 8 8 0 000 16zM9.555 7.168A1 1 0 008 8v4a1 1 0 001.555.832l3-2a1 1 0 000-1.664l-3-2z"
                      clipRule="evenodd"
                    />
                  </svg>
                  <span>
                    {segment.start_time} - {segment.end_time}
                  </span>
                </button>
                <span
                  className={`px-2 py-1 text-xs font-medium rounded-full border ${speakerColorClasses}`}
                >
                  {segment.speaker}
                </span>
              </div>

              {/* Content */}
              {displayMode === "segments" ? (
                // Segment View
                <p className="text-base text-gray-800 leading-relaxed">
                  {segment.text}
                </p>
              ) : (
                // Word View
                <div className="flex flex-wrap gap-1">
                  {segment.words?.map((word, wordIndex) => (
                    <div
                      key={wordIndex}
                      className="group relative"
                      title={`${word.start} - ${word.end}`}
                    >
                      <span
                        className={`text-base hover:bg-gray-100 rounded px-1 py-0.5 cursor-pointer ${
                          getSpeakerColor(word.speaker).split(" ")[0]
                        }`}
                      >
                        {word.word}
                      </span>

                      {/* Timestamp tooltip */}
                      <div className="absolute bottom-full left-1/2 transform -translate-x-1/2 mb-1 px-2 py-1 text-xs text-white bg-gray-800 rounded opacity-0 group-hover:opacity-100 transition-opacity z-10">
                        {word.start}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Statistics */}
      <div className="mt-8 grid grid-cols-2 sm:grid-cols-4 gap-4">
        <div className="bg-white p-4 rounded-lg shadow-sm border border-gray-200">
          <div className="text-sm text-gray-500 mb-1">Total Segments</div>
          <div className="text-xl font-medium">
            {transcription.segments.length}
          </div>
        </div>
        <div className="bg-white p-4 rounded-lg shadow-sm border border-gray-200">
          <div className="text-sm text-gray-500 mb-1">Duration</div>
          <div className="text-xl font-medium">{transcription.duration}</div>
        </div>
        <div className="bg-white p-4 rounded-lg shadow-sm border border-gray-200">
          <div className="text-sm text-gray-500 mb-1">Language</div>
          <div className="text-xl font-medium capitalize">
            {transcription.language}
          </div>
        </div>
        <div className="bg-white p-4 rounded-lg shadow-sm border border-gray-200">
          <div className="text-sm text-gray-500 mb-1">Total Words</div>
          <div className="text-xl font-medium">
            {transcription.segments.reduce(
              (acc, segment) => acc + (segment.words?.length || 0),
              0
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
