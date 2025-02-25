# Video Transcription API

This is a FastAPI-based backend service that transcribes video files into text with timestamps using OpenAI's Whisper model.

## Features

- Upload video/audio files for transcription
- Get transcribed text with timestamps
- Supports multiple file formats (mp4, mpeg, mpga, m4a, wav, webm, mp3)
- File size limit of 25MB (OpenAI's limit)

## Setup

1. Install the required dependencies:

```bash
pip install -r requirements.txt
```

2. Create a `.env` file in the root directory with your OpenAI API key:

```
OPENAI_API_KEY=your_api_key_here
```

3. Run the server:

```bash
python main.py
```

The server will start at `http://localhost:8000`

## API Endpoints

### POST /transcribe/

Upload a video/audio file for transcription.

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
                "text": "Segment text..."
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
- Files exceeding size limit
- Transcription failures

## Notes

- The API uses OpenAI's Whisper model for transcription
- CORS is enabled for all origins
- Maximum file size is 25MB
