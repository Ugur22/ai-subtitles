import os
from fastapi import FastAPI, UploadFile, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from openai import OpenAI
from pathlib import Path
import tempfile
from typing import Dict, List
import json
import httpx
from datetime import timedelta
from moviepy.editor import VideoFileClip
import math
import subprocess
import shutil
from tqdm import tqdm
import time
import ffmpeg
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request as StarletteRequest
from starlette.responses import Response as StarletteResponse
from starlette.types import ASGIApp, Receive, Scope, Send
from fastapi.staticfiles import StaticFiles
import sqlite3
import hashlib

# Global variable to store the last transcription
last_transcription_data = None

# Database functions
def init_db():
    """Initialize the SQLite database for storing transcriptions"""
    conn = sqlite3.connect('transcriptions.db')
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS transcriptions (
        video_hash TEXT PRIMARY KEY,
        filename TEXT,
        file_path TEXT,
        transcription_data TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    conn.commit()
    conn.close()
    print("Database initialized successfully")

def generate_file_hash(file_path):
    """Generate a unique hash for a file based on its content"""
    BUF_SIZE = 65536  # 64kb chunks
    sha256 = hashlib.sha256()
    
    with open(file_path, 'rb') as f:
        while True:
            data = f.read(BUF_SIZE)
            if not data:
                break
            sha256.update(data)
    
    return sha256.hexdigest()

def store_transcription(video_hash, filename, transcription_data, file_path=None):
    """Store transcription data in the database"""
    try:
        conn = sqlite3.connect('transcriptions.db')
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO transcriptions (video_hash, filename, file_path, transcription_data) VALUES (?, ?, ?, ?)",
            (video_hash, filename, file_path, json.dumps(transcription_data))
        )
        conn.commit()
        conn.close()
        print(f"Stored transcription for {filename} with hash {video_hash}")
        return True
    except Exception as e:
        print(f"Error storing transcription: {str(e)}")
        return False

def get_transcription(video_hash):
    """Retrieve transcription data from the database by hash"""
    try:
        conn = sqlite3.connect('transcriptions.db')
        cursor = conn.cursor()
        cursor.execute("SELECT transcription_data, file_path FROM transcriptions WHERE video_hash = ?", (video_hash,))
        result = cursor.fetchone()
        conn.close()
        
        if result:
            transcription_data = json.loads(result[0])
            file_path = result[1]
            # Add file_path to the transcription data
            if file_path:
                transcription_data['file_path'] = file_path
            return transcription_data
        return None
    except Exception as e:
        print(f"Error retrieving transcription: {str(e)}")
        return None

# Load environment variables
load_dotenv()

def format_timestamp(seconds: float) -> str:
    """Convert seconds to HH:MM:SS format"""
    td = timedelta(seconds=seconds)
    hours = td.seconds // 3600
    minutes = (td.seconds % 3600) // 60
    seconds = td.seconds % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

def translate_text(client: OpenAI, text: str, source_lang: str) -> str:
    """Translate text to English using OpenAI's API"""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": f"""You are a professional translator from {source_lang} to English. 
Translate the following text accurately while maintaining the original meaning and tone.
Important guidelines:
- Maintain natural language flow and avoid word-for-word translation
- Consider the context when translating repeated phrases
- Keep the same format with [index] markers
- Only return the translation, nothing else
- Ensure each segment flows naturally with adjacent segments"""},
                    {"role": "user", "content": text}
                ],
                temperature=0.7,  # Increased for more natural variations
                max_tokens=2000,
                timeout=30
            )
            translated = response.choices[0].message.content.strip()
            if not translated:
                raise Exception("Empty translation received")
            return translated
        except Exception as e:
            if attempt == max_retries - 1:  # Last attempt
                raise Exception(f"Translation failed after {max_retries} attempts: {str(e)}")
            print(f"Translation attempt {attempt + 1} failed: {str(e)}. Retrying...")
            time.sleep(1)  # Wait before retrying

def translate_segments(client: OpenAI, segments: List[Dict], source_lang: str) -> List[Dict]:
    """Translate a batch of segments to reduce API calls"""
    # Process segments in smaller batches for better reliability
    BATCH_SIZE = 10  # Reduced batch size for better context handling
    
    # Split into smaller batches with context overlap
    for i in range(0, len(segments), BATCH_SIZE):
        # Get current batch
        batch = segments[i:i + BATCH_SIZE]
        
        # Add context from previous and next segments if available
        context_before = ""
        context_after = ""
        if i > 0:
            context_before = f"Context before: {segments[i-1].text}\n"
        if i + BATCH_SIZE < len(segments):
            context_after = f"\nContext after: {segments[i+BATCH_SIZE].text}"
        
        # Combine text with context
        combined_text = context_before + "\n---\n".join([f"[{j}] {segment.text}" for j, segment in enumerate(batch)]) + context_after
        
        try:
            translated_text = translate_text(client, combined_text, source_lang)
            
            # Split translations and map back to segments
            translations = {}
            current_index = None
            current_text = []
            
            for line in translated_text.split('\n'):
                line = line.strip()
                if not line:
                    continue
                
                # Skip context lines
                if line.startswith("Context "):
                    continue
                    
                if line.startswith('[') and ']' in line:
                    # Save previous segment if exists
                    if current_index is not None:
                        translations[current_index] = ' '.join(current_text).strip()
                    
                    # Start new segment
                    try:
                        current_index = int(line[line.find('[')+1:line.find(']')])
                        current_text = [line[line.find(']')+1:].strip()]
                    except ValueError:
                        # If index parsing fails, append to current segment
                        if current_index is not None:
                            current_text.append(line)
                else:
                    if current_index is not None:
                        current_text.append(line)
            
            # Save the last segment
            if current_index is not None:
                translations[current_index] = ' '.join(current_text).strip()
            
            # Map translations back to segments
            for j, segment in enumerate(batch):
                translation = translations.get(j)
                if not translation:  # If translation is empty or None
                    # Try to translate this segment individually with context
                    try:
                        context = ""
                        if j > 0:
                            context += f"Previous: {batch[j-1].text}\n"
                        if j < len(batch) - 1:
                            context += f"\nNext: {batch[j+1].text}"
                        
                        single_translation = translate_text(
                            client,
                            f"{context}\n---\n{segment.text}",
                            source_lang
                        )
                        # Remove any context markers from the translation
                        single_translation = single_translation.replace("Previous:", "").replace("Next:", "").strip()
                        segment.translation = single_translation
                    except Exception as e:
                        print(f"Individual translation error for segment {j}: {str(e)}")
                        segment.translation = None
                else:
                    segment.translation = translation
                
        except Exception as e:
            print(f"Batch translation error: {str(e)}")
            # Try to translate each segment individually with context
            for j, segment in enumerate(batch):
                try:
                    context = ""
                    if j > 0:
                        context += f"Previous: {batch[j-1].text}\n"
                    if j < len(batch) - 1:
                        context += f"\nNext: {batch[j+1].text}"
                    
                    single_translation = translate_text(
                        client,
                        f"{context}\n---\n{segment.text}",
                        source_lang
                    )
                    # Remove any context markers from the translation
                    single_translation = single_translation.replace("Previous:", "").replace("Next:", "").strip()
                    segment.translation = single_translation
                except Exception as e:
                    print(f"Individual translation error for segment {j}: {str(e)}")
                    segment.translation = None
    
    return segments

def compress_audio(input_path: str, output_path: str) -> str:
    """Compress audio file to reduce size while maintaining quality"""
    try:
        # Check if ffmpeg is available
        if not shutil.which('ffmpeg'):
            raise Exception("ffmpeg is not installed. Please install ffmpeg first.")

        # Convert to mono, reduce quality, and compress
        command = [
            'ffmpeg', '-i', input_path,
            '-ac', '1',  # Convert to mono
            '-ar', '16000',  # Sample rate 16kHz
            '-b:a', '32k',  # Bitrate 32k
            output_path,
            '-y'  # Overwrite output file if it exists
        ]
        
        subprocess.run(command, check=True, capture_output=True)
        return output_path
    except subprocess.CalledProcessError as e:
        raise Exception(f"Error compressing audio: {e.stderr.decode()}")

def extract_audio(video_path: str, chunk_duration: int = 600) -> list:
    """
    Extract audio from video and split into chunks if needed
    Returns list of paths to compressed audio chunks
    """
    audio_chunks = []
    
    with VideoFileClip(video_path) as video:
        # Get total duration in seconds
        duration = video.duration
        
        # If duration is less than chunk_duration, just extract the whole audio
        if duration <= chunk_duration:
            temp_audio_path = video_path + "_temp.wav"
            compressed_audio_path = video_path + ".wav"
            
            # Extract audio
            video.audio.write_audiofile(temp_audio_path, codec='pcm_s16le')
            
            # Compress the audio
            compress_audio(temp_audio_path, compressed_audio_path)
            
            # Clean up temporary file
            os.unlink(temp_audio_path)
            
            audio_chunks.append(compressed_audio_path)
        else:
            # Split into chunks
            num_chunks = math.ceil(duration / chunk_duration)
            for i in range(num_chunks):
                start_time = i * chunk_duration
                end_time = min((i + 1) * chunk_duration, duration)
                
                # Extract chunk
                chunk = video.subclip(start_time, end_time)
                temp_chunk_path = f"{video_path}_chunk_{i}_temp.wav"
                compressed_chunk_path = f"{video_path}_chunk_{i}.wav"
                
                # Extract audio for this chunk
                chunk.audio.write_audiofile(temp_chunk_path, codec='pcm_s16le')
                
                # Compress the audio chunk
                compress_audio(temp_chunk_path, compressed_chunk_path)
                
                # Clean up temporary file
                os.unlink(temp_chunk_path)
                
                audio_chunks.append(compressed_chunk_path)
                
    return audio_chunks

def format_srt_timestamp(seconds: float) -> str:
    """Convert seconds to SRT timestamp format (HH:MM:SS,mmm)"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    seconds = seconds % 60
    milliseconds = int((seconds % 1) * 1000)
    seconds = int(seconds)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"

def generate_srt(segments: List[Dict], use_translation: bool = False) -> str:
    """Generate SRT format subtitles from segments"""
    srt_content = []
    for i, segment in enumerate(segments, 1):
        # Convert timestamps to SRT format
        start_seconds = sum(float(x) * 60 ** i for i, x in enumerate(reversed(segment['start_time'].split(':'))))
        end_seconds = sum(float(x) * 60 ** i for i, x in enumerate(reversed(segment['end_time'].split(':'))))
        
        # Format subtitle entry
        srt_content.extend([
            str(i),
            f"{format_srt_timestamp(start_seconds)} --> {format_srt_timestamp(end_seconds)}",
            segment['translation'] if use_translation else segment['text'],
            ""  # Empty line between entries
        ])
    
    return "\n".join(srt_content)

def analyze_content(client: OpenAI, text: str, topic: str) -> bool:
    """Analyze if a text segment is related to a specific topic using GPT-4"""
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are an expert at analyzing text content. Respond with 'true' if the text discusses the given topic, even indirectly. Respond with 'false' if it doesn't. Only respond with 'true' or 'false'."},
                {"role": "user", "content": f"Topic to check: {topic}\n\nText: {text}"}
            ],
            temperature=0.1
        )
        result = response.choices[0].message.content.strip().lower()
        return result == "true"
    except Exception as e:
        return False

def analyze_content_batch(client: OpenAI, segments: List[Dict], topic: str, max_segments: int = 50) -> List[bool]:
    """Analyze multiple segments at once for a topic using GPT-4"""
    try:
        # Limit the number of segments to analyze
        segments = segments[:max_segments]
        
        # Combine segments with markers
        combined_text = "\n---\n".join([f"[{i}] {segment['text']}" for i, segment in enumerate(segments)])
        
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are an expert at analyzing text content. For each numbered segment, respond with the segment number and either 'true' or 'false' indicating if it's related to the topic. Format: [number]:true/false"},
                {"role": "user", "content": f"Topic to check: {topic}\n\nText segments:\n{combined_text}"}
            ],
            temperature=0.1,
            timeout=30  # 30 second timeout
        )
        
        # Parse results
        results = {}
        for line in response.choices[0].message.content.strip().split('\n'):
            if ':' in line:
                try:
                    idx, result = line.split(':')
                    idx = int(idx.strip('[]'))
                    results[idx] = result.strip().lower() == 'true'
                except:
                    continue
        
        return [results.get(i, False) for i in range(len(segments))]
    except Exception as e:
        print(f"Batch analysis error: {str(e)}")
        return [False] * len(segments)

def format_eta(seconds: int) -> str:
    """Format estimated time remaining"""
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    elif minutes > 0:
        return f"{minutes}m {secs}s"
    return f"{secs}s"

def process_video_with_ffmpeg(input_path: str, output_path: str) -> None:
    """Process video and extract compressed audio using ffmpeg"""
    try:
        # Check if ffmpeg is available
        if not shutil.which('ffmpeg'):
            raise Exception("ffmpeg is not installed")

        # Extract audio with compression settings
        command = [
            'ffmpeg',
            '-i', input_path,
            '-vn',  # Skip video
            '-ac', '1',  # Convert to mono
            '-ar', '16000',  # Sample rate 16kHz
            '-b:a', '32k',  # Bitrate 32k
            output_path,
            '-y'  # Overwrite output file if it exists
        ]
        
        subprocess.run(command, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        raise Exception(f"Error processing video: {e.stderr.decode()}")

def extract_screenshot(input_path: str, timestamp: float, output_path: str) -> None:
    """Extract a screenshot from a video at a specific timestamp."""
    try:
        print(f"\nExtracting screenshot at timestamp {timestamp}...")
        print(f"Input path: {input_path}")
        print(f"Output path: {output_path}")
        
        # Use FFmpeg to extract the frame
        cmd = [
            'ffmpeg', '-ss', str(timestamp),
            '-i', input_path,
            '-vframes', '1',
            '-q:v', '2',  # High quality
            '-vf', 'scale=320:-1',  # Resize to 320px width, maintain aspect ratio
            output_path,
            '-y'  # Overwrite if exists
        ]
        print(f"Running FFmpeg command: {' '.join(cmd)}")
        result = subprocess.run(cmd, check=True, capture_output=True)
        print(f"Screenshot extraction completed successfully")
        return True
    except Exception as e:
        print(f"Failed to extract screenshot at {timestamp}")
        print(f"Error details: {str(e)}")
        if isinstance(e, subprocess.CalledProcessError):
            print(f"FFmpeg stderr: {e.stderr.decode()}")
        return None

# Initialize FastAPI app with custom request size limit
app = FastAPI(
    title="Video Transcription API"
)

# Add startup event to initialize database
@app.on_event("startup")
async def startup_event():
    init_db()

# Mount static files directory
app.mount("/static", StaticFiles(directory="static"), name="static")

# Configure CORS with more specific settings
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Allow frontend origin
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
    expose_headers=["Content-Disposition"],  # Important for file downloads
    max_age=600,  # Cache preflight requests for 10 minutes
)

# Add middleware for handling large file uploads
class LargeUploadMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method == 'POST' and request.url.path == '/transcribe/':
            # Set a 5GB limit for /transcribe/ endpoint
            request._body_size_limit = 5 * 1024 * 1024 * 1024  # 5GB
            request.scope["max_content_size"] = 5 * 1024 * 1024 * 1024  # 5GB
        return await call_next(request)

app.add_middleware(LargeUploadMiddleware)

# Configure OpenAI with a custom httpx client
http_client = httpx.Client()
client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    http_client=http_client
)

@app.post("/cleanup_screenshots/")
async def cleanup_screenshots() -> Dict:
    """Delete all screenshots from the static/screenshots directory"""
    try:
        screenshots_dir = os.path.join("static", "screenshots")
        
        # Check if directory exists
        if not os.path.exists(screenshots_dir):
            os.makedirs(screenshots_dir, exist_ok=True)
            return {"success": True, "message": "Screenshots directory was empty"}
        
        # Count files before deletion
        files = os.listdir(screenshots_dir)
        file_count = len(files)
        
        # Delete all files in the directory
        for filename in files:
            file_path = os.path.join(screenshots_dir, filename)
            if os.path.isfile(file_path):
                os.remove(file_path)
                print(f"Deleted: {file_path}")
        
        return {
            "success": True, 
            "message": f"Successfully deleted {file_count} screenshot files"
        }
    except Exception as e:
        print(f"Error cleaning up screenshots: {str(e)}")
        return {
            "success": False,
            "message": f"Error cleaning up screenshots: {str(e)}"
        }

@app.get("/current_transcription/")
async def get_current_transcription(request: Request) -> Dict:
    """Return the current transcription data"""
    global last_transcription_data
    
    if not last_transcription_data:
        raise HTTPException(status_code=404, detail="No transcription available. Please transcribe a video first.")
    
    # Count segments with screenshots
    segment_count = len(last_transcription_data['transcription']['segments'])
    screenshots_count = sum(1 for segment in last_transcription_data['transcription']['segments'] 
                          if 'screenshot_url' in segment and segment['screenshot_url'])
    
    print(f"Sending transcription data: {segment_count} segments total, {screenshots_count} with screenshots")
    return last_transcription_data

@app.post("/transcribe/")
async def transcribe_video(file: UploadFile, request: Request, file_path: str = None) -> Dict:
    """Handle video upload, extract audio, and transcribe"""
    global last_transcription_data
    
    try:
        if not file:
            raise HTTPException(status_code=400, detail="No file provided")
            
        # Validate file type
        allowed_extensions = {'.mp4', '.mpeg', '.mpga', '.m4a', '.wav', '.webm', '.mp3'}
        file_extension = Path(file.filename).suffix.lower()
        if file_extension not in allowed_extensions:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file format. Supported formats: {', '.join(allowed_extensions)}"
            )
            
        print(f"\nProcessing video: {file.filename}")
        start_time = time.time()
        
        # Create a temporary directory for processing
        with tempfile.TemporaryDirectory() as temp_dir:
            # Save uploaded file in chunks to avoid memory issues
            temp_input_path = os.path.join(temp_dir, file.filename)
            temp_output_path = os.path.join(temp_dir, "audio.mp3")
            screenshots_dir = os.path.join("static", "screenshots")
            os.makedirs(screenshots_dir, exist_ok=True)
            
            print(f"Created temp directory: {temp_dir}")
            print(f"Input path: {temp_input_path}")
            print(f"Output path: {temp_output_path}")
            print(f"Screenshots directory: {screenshots_dir}")
            
            # Save file in chunks with a larger chunk size for better performance
            CHUNK_SIZE = 1024 * 1024 * 8  # 8MB chunks
            total_size = 0
            
            print("\nUploading video...")
            try:
                with open(temp_input_path, "wb") as buffer:
                    while chunk := await file.read(CHUNK_SIZE):
                        total_size += len(chunk)
                        if total_size > 5 * 1024 * 1024 * 1024:  # 5GB limit
                            raise HTTPException(
                                status_code=413,
                                detail="File too large. Maximum size is 5GB."
                            )
                        buffer.write(chunk)
                        print(f"Uploaded: {total_size / (1024*1024):.1f} MB", end="\r")
                print(f"\nUpload completed. Total size: {total_size / (1024*1024):.1f} MB")
            except Exception as e:
                print(f"Upload error: {str(e)}")
                raise HTTPException(
                    status_code=400,
                    detail=f"Error uploading file: {str(e)}"
                )
            
            # Generate hash for the file
            video_hash = generate_file_hash(temp_input_path)
            print(f"Generated hash for video: {video_hash}")
            
            # Check if we already have a transcription for this file
            existing_transcription = get_transcription(video_hash)
            if existing_transcription:
                print(f"Found existing transcription for {file.filename} with hash {video_hash}")
                # Update the last_transcription_data with the existing data
                last_transcription_data = existing_transcription
                return existing_transcription
            
            print("No existing transcription found. Processing video...")
            
            print("\nExtracting and compressing audio...")
            try:
                process_video_with_ffmpeg(temp_input_path, temp_output_path)
                print("Audio extraction completed successfully")
            except Exception as e:
                print(f"Audio extraction error: {str(e)}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Error processing video: {str(e)}"
                )
            
            print("\nTranscribing audio...")
            try:
                with open(temp_output_path, "rb") as audio_file:
                    # Transcribe with Whisper API
                    print("Calling Whisper API...")
                    response = client.audio.transcriptions.create(
                        model="whisper-1",
                        file=audio_file,
                        response_format="verbose_json"
                    )
                    print("Transcription completed successfully")
                    
                    # Translate if not in English
                    if response.language.lower() not in ['en', 'english']:
                        print("\nTranslating segments to English...")
                        response.segments = translate_segments(client, response.segments, response.language)
                        print("Translation completed successfully")
                    
                    # Extract screenshots for each segment if it's a video file
                    if file_extension in {'.mp4', '.mpeg', '.webm'}:
                        print("\nExtracting screenshots for video segments...")
                        for i, segment in enumerate(response.segments):
                            print(f"\nProcessing segment {i+1}/{len(response.segments)}")
                            screenshot_filename = f"{Path(file.filename).stem}_{segment.start:.2f}.jpg"
                            screenshot_path = os.path.join(screenshots_dir, screenshot_filename)
                            success = extract_screenshot(temp_input_path, segment.start, screenshot_path)
                            if success:
                                # Add screenshot URL to segment
                                screenshot_url = f"/static/screenshots/{screenshot_filename}"
                                segment.screenshot_url = screenshot_url
                                print(f"Added screenshot URL: {screenshot_url}")
                            else:
                                segment.screenshot_url = None
                                print("Failed to add screenshot")
                    
                    # Process transcription result
                    print("\nProcessing transcription result...")
                    result = {
                        "filename": file.filename,
                        "transcription": {
                            "text": response.text,
                            "language": response.language,
                            "duration": str(timedelta(seconds=int(float(response.duration)))),
                            "segments": [
                                {
                                    "id": i,
                                    "start_time": str(timedelta(seconds=int(float(s.start)))),
                                    "end_time": str(timedelta(seconds=int(float(s.end)))),
                                    "text": s.text,
                                    "translation": s.translation if hasattr(s, 'translation') else None,
                                    "screenshot_url": getattr(s, 'screenshot_url', None)
                                }
                                for i, s in enumerate(response.segments)
                            ],
                            "processing_time": f"{time.time() - start_time:.1f} seconds"
                        }
                    }
                    
                    # Store the transcription in the database
                    store_transcription(video_hash, file.filename, result, file_path)
                    
                    # Add file path to the result
                    if file_path:
                        result['file_path'] = file_path
                    
                    # Store in both request state and global variable
                    request.app.state.last_transcription = result
                    last_transcription_data = result
                    
                    print("\nTranscription processing completed successfully")
                    return result
            except Exception as e:
                print(f"Transcription error: {str(e)}")
                if hasattr(e, '__dict__'):
                    print(f"Error details: {e.__dict__}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Error transcribing audio: {str(e)}"
                )
            
    except HTTPException as e:
        print(f"HTTP Exception: {e.detail}")
        raise e
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        if hasattr(e, '__dict__'):
            print(f"Error details: {e.__dict__}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/subtitles/{language}")
async def get_subtitles(language: str, request: Request) -> Response:
    """
    Get subtitles in SRT format. Language can be 'original' or 'english'.
    """
    if not hasattr(request.app.state, 'last_transcription'):
        raise HTTPException(status_code=404, detail="No transcription available. Please transcribe a video first.")
    
    transcription = request.app.state.last_transcription
    
    if language not in ['original', 'english']:
        raise HTTPException(status_code=400, detail="Language must be 'original' or 'english'")
    
    # Verify we have segments
    if not transcription['transcription']['segments']:
        raise HTTPException(status_code=500, detail="No segments found in transcription")
    
    # For English subtitles, verify we have translations when needed
    if language == 'english' and transcription['transcription']['language'] != 'english':
        if not all('translation' in segment and segment['translation'] for segment in transcription['transcription']['segments']):
            raise HTTPException(status_code=500, detail="English translation is not available. Please try transcribing the video again.")
    
    use_translation = (language == 'english' and transcription['transcription']['language'] != 'english')
    srt_content = generate_srt(transcription['transcription']['segments'], use_translation)
    
    # Create filename based on original video and language
    original_filename = transcription['filename']
    base_name = os.path.splitext(original_filename)[0]
    srt_filename = f"{base_name}_{language}.srt"
    
    # Return SRT file with correct content type and headers
    return Response(
        content=srt_content,
        media_type="application/x-subrip",
        headers={
            "Content-Disposition": f'attachment; filename="{srt_filename}"',
            "Content-Type": "application/x-subrip"
        }
    )

@app.post("/search/")
async def search_content(
    request: Request, 
    topic: str, 
    semantic_search: bool = True,
    context_window: int = 2  # Number of segments before/after for context
) -> Dict:
    """
    Search through the last transcription for specific topics or keywords.
    Use semantic_search=true for topic analysis, false for direct keyword matching.
    """
    if not hasattr(request.app.state, 'last_transcription'):
        raise HTTPException(status_code=404, detail="No transcription available. Please transcribe a video first.")
    
    transcription = request.app.state.last_transcription
    segments = transcription['transcription']['segments']
    full_text = transcription['transcription']['text']
    
    matches = []
    
    if semantic_search:
        try:
            # Analyze the complete text at once
            response = client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": """You are an expert at analyzing text content and finding semantic matches. 
Your task is to identify parts of the text that are semantically related to the given topic, including:
- Exact matches of the word
- Different forms of the word (e.g., 'work', 'worked', 'working')
- Synonyms and related concepts
- Contextual references to the topic
- Implicit mentions or discussions of the topic

Return the exact quotes from the text that are relevant, one per line. If no relevant parts are found, return 'NO_MATCHES'.
Be thorough in your analysis and err on the side of including relevant content rather than excluding it.
Important: Return the complete sentences containing the matches, not just the matching words."""},
                    {"role": "user", "content": f"Topic to find: {topic}\n\nText to analyze:\n{full_text}"}
                ],
                temperature=0.3,
                max_tokens=1000
            )
            
            relevant_quotes = response.choices[0].message.content.strip().split('\n')
            
            if relevant_quotes[0] != 'NO_MATCHES':
                # Find matching segments for each quote
                for quote in relevant_quotes:
                    quote = quote.strip('" ')
                    if not quote:
                        continue
                        
                    # Find segments containing this quote using fuzzy matching
                    for i, segment in enumerate(segments):
                        # More lenient matching - check if the core topic or its variations appear
                        segment_text = segment['text'].lower()
                        quote_lower = quote.lower()
                        
                        # Check for direct matches or word variations
                        if (topic.lower() in segment_text or  # Direct match
                            any(variation in segment_text     # Check variations
                                for variation in [f"{topic}s", f"{topic}ed", f"{topic}ing", 
                                               f"{topic}es", f"{topic}'s"]) or
                            quote_lower in segment_text):     # Full quote match
                            
                            # Add the match with context
                            context_start = max(0, i - context_window)
                            context_end = min(len(segments), i + context_window + 1)
                            
                            match_entry = {
                                "timestamp": {
                                    "start": segment['start_time'],
                                    "end": segment['end_time']
                                },
                                "original_text": segment['text'],
                                "translated_text": segment['translation'],
                                "context": {
                                    "before": [s['text'] for s in segments[context_start:i]],
                                    "after": [s['text'] for s in segments[i+1:context_end]]
                                }
                            }
                            
                            # Only add if not already in matches
                            if not any(m['original_text'] == segment['text'] for m in matches):
                                matches.append(match_entry)
                            break  # Found the segment for this quote
                            
        except Exception as e:
            print(f"Semantic search error: {str(e)}")
            # Fall back to keyword search if semantic search fails
            semantic_search = False
    
    if not semantic_search:
        # Simple keyword search in complete text
        topic_lower = topic.lower()
        
        for i, segment in enumerate(segments):
            # Check if segment text contains the topic
            text_match = topic_lower in segment['text'].lower()
            
            # Check for translation match only if translation exists
            translation_match = False
            if segment['translation'] is not None:
                translation_match = topic_lower in segment['translation'].lower()
                
            if text_match or translation_match:
                # Add the match with context
                context_start = max(0, i - context_window)
                context_end = min(len(segments), i + context_window + 1)
                
                matches.append({
                    "timestamp": {
                        "start": segment['start_time'],
                        "end": segment['end_time']
                    },
                    "original_text": segment['text'],
                    "translated_text": segment['translation'],
                    "context": {
                        "before": [s['text'] for s in segments[context_start:i]],
                        "after": [s['text'] for s in segments[i+1:context_end]]
                    }
                })
    
    return {
        "topic": topic,
        "total_matches": len(matches),
        "semantic_search_used": semantic_search,
        "matches": matches
    }

def _time_to_seconds(time_str: str) -> float:
    """Convert HH:MM:SS format to seconds"""
    h, m, s = map(int, time_str.split(':'))
    return h * 3600 + m * 60 + s

def _time_diff_minutes(time1: str, time2: str) -> float:
    """Calculate difference between two timestamps in minutes"""
    return (_time_to_seconds(time2) - _time_to_seconds(time1)) / 60

@app.post("/generate_summary/")
async def generate_summary(request: Request) -> Dict:
    """Generate section summaries from transcription"""
    if not hasattr(request.app.state, 'last_transcription'):
        raise HTTPException(status_code=404, detail="No transcription available. Please transcribe a video first.")
    
    transcription = request.app.state.last_transcription
    segments = transcription['transcription']['segments']
    
    # Group segments into logical sections (roughly 1-3 minutes each)
    sections = []
    current_section = []
    section_start = "00:00:00"
    min_section_duration = 1  # Minimum section duration in minutes
    max_section_duration = 3  # Maximum section duration in minutes
    
    for segment in segments:
        # Create new section when we reach desired duration or significant pause
        start_time = segment['start_time']
        if current_section:
            # Check if we've reached minimum duration and have a natural break
            section_duration = _time_diff_minutes(section_start, start_time)
            if section_duration >= min_section_duration:
                # Check for natural break (>2 second pause)
                last_segment_end = _time_to_seconds(current_section[-1]['end_time'])
                current_segment_start = _time_to_seconds(start_time)
                pause_duration = current_segment_start - last_segment_end
                
                # Create new section if we have a significant pause or reached max duration
                if pause_duration > 2 or section_duration >= max_section_duration:
                    sections.append({
                        "start": section_start,
                        "end": current_section[-1]['end_time'],
                        "segments": current_section.copy()
                    })
                    section_start = start_time
                    current_section = [segment]
                    continue
        
        current_section.append(segment)
    
    # Add the last section
    if current_section:
        sections.append({
            "start": section_start,
            "end": current_section[-1]['end_time'],
            "segments": current_section
        })
    
    # Generate summary for each section
    summaries = []
    for section in sections:
        # Combine text from all segments - safely handling None values
        section_text = " ".join(seg["text"] or "" for seg in section["segments"] if seg.get("text"))
        
        # Fix: Safely handle translation which might be None or missing
        translated_texts = []
        for seg in section["segments"]:
            if seg.get("translation"):
                translated_texts.append(seg["translation"])
            elif seg.get("text"):
                translated_texts.append(seg["text"])
            else:
                # Skip this segment if both text and translation are missing/None
                continue
                
        translated_text = " ".join(translated_texts)
        
        # Only use translation if it's different from the original
        text_to_summarize = translated_text if (
            translated_text != section_text and 
            transcription['transcription']['language'].lower() not in ["en", "english"]
        ) else section_text
        
        # Skip empty sections
        if not text_to_summarize:
            continue
        
        try:
            # Generate concise summary
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are an expert at summarizing content. Create a concise summary (2-3 sentences) that captures the key points from this transcript section."},
                    {"role": "user", "content": f"Section from {section['start']} to {section['end']}:\n\n{text_to_summarize}"}
                ],
                temperature=0.3
            )
            
            # Generate descriptive title
            title_response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "Create a short, descriptive title (3-5 words) for this transcript section."},
                    {"role": "user", "content": text_to_summarize}
                ],
                temperature=0.3
            )
            
            summaries.append({
                "title": title_response.choices[0].message.content.strip(),
                "start": section["start"],
                "end": section["end"],
                "summary": response.choices[0].message.content.strip()
            })
        except Exception as e:
            print(f"Error generating summary for section {section['start']}-{section['end']}: {e}")
            # Add a placeholder for failed summaries
            summaries.append({
                "title": f"Section {section['start']}-{section['end']}",
                "start": section["start"],
                "end": section["end"],
                "summary": "Summary generation failed. Please try again."
            })
    
    return {"summaries": summaries}

@app.get("/transcriptions/")
async def list_transcriptions():
    """List all saved transcriptions"""
    try:
        conn = sqlite3.connect('transcriptions.db')
        cursor = conn.cursor()
        cursor.execute("SELECT video_hash, filename, created_at, file_path FROM transcriptions ORDER BY created_at DESC")
        rows = cursor.fetchall()
        conn.close()
        
        return {
            "transcriptions": [
                {
                    "video_hash": row[0],
                    "filename": row[1],
                    "created_at": row[2],
                    "file_path": row[3]
                }
                for row in rows
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving transcriptions: {str(e)}")

@app.get("/transcription/{video_hash}")
async def get_saved_transcription(video_hash: str, request: Request):
    """Get a specific transcription by hash"""
    transcription = get_transcription(video_hash)
    if not transcription:
        raise HTTPException(status_code=404, detail="Transcription not found")
    
    # Update the last_transcription_data and request state
    global last_transcription_data
    last_transcription_data = transcription
    request.app.state.last_transcription = transcription
    
    return transcription

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 