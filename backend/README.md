# Video Transcription API

This is a FastAPI-based backend service that transcribes video files into text with timestamps using the local **Faster Whisper** model (no OpenAI API key required).

## Features

- Upload video/audio files for transcription
- Local transcription using `faster-whisper` (runs on your machine)
- High-performance batched inference
- Speaker diarization support
- Get transcribed text with timestamps
- Supports multiple file formats (mp4, mpeg, mpga, m4a, wav, webm, mp3)
- No strict file size limit (dependent on server resources, not API limits)

## Setup

1. Install the required dependencies:

```bash
pip install -r requirements.txt
```

Note: For GPU acceleration, ensure you have the correct CUDA/cuDNN libraries installed for `faster-whisper`.

2. Run the server:

```bash
source venv/bin/activate && uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

The server will start at `http://localhost:8000`

## API Endpoints

### POST /transcribe_local/

Upload a video/audio file for local transcription.

**Request:**

- Method: POST
- Content-Type: multipart/form-data
- Body: file (video/audio file)

**Response:**

```json
{
    "filename": "example.mp4",
    "transcription": {
        "text": "Transcribed text...",
        "segments": [
            {
                "id": 0,
                "start": 0.0,
                "end": 2.5,
                "text": "Segment text...",
                "speaker": "SPEAKER_00"
            },
            ...
        ]
    }
}
```

## Error Handling

The API will return appropriate error messages for:

- Missing files
- Unsupported file formats
- Transcription failures

## Notes

- The API uses `faster-whisper` for high-performance local transcription.
- CORS is enabled for all origins.
- Large files may take longer to process depending on hardware capabilities.
