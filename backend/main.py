import os
from fastapi import FastAPI, UploadFile, HTTPException, Request, Response, Form
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
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
from fastapi.responses import FileResponse
import uuid
from faster_whisper import WhisperModel
# MarianMT for local translation
from transformers import MarianMTModel, MarianTokenizer
# Import the necessary libraries for local summarization
from transformers import pipeline, AutoTokenizer, AutoModelForSeq2SeqLM
import torch

# Global variable to store the last transcription
last_transcription_data = None

# Initialize the summarization model
def get_summarization_model():
    """Get or initialize the summarization model"""
    model_name = "facebook/bart-large-cnn"  # Good for general summarization
    try:
        # Try to load the model from cache first
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        model = AutoModelForSeq2SeqLM.from_pretrained(model_name)
        return tokenizer, model
    except Exception as e:
        print(f"Error loading summarization model: {str(e)}")
        return None, None

# Global variable to store the model
summarization_tokenizer = None
summarization_model = None

def generate_local_summary(text, max_length=150, min_length=50):
    """Generate a summary using the local model"""
    global summarization_tokenizer, summarization_model
    
    # Initialize the model if not already done
    if summarization_tokenizer is None or summarization_model is None:
        summarization_tokenizer, summarization_model = get_summarization_model()
        if summarization_tokenizer is None or summarization_model is None:
            return "Summary generation failed: Model could not be loaded."
    
    try:
        # Tokenize the input text
        inputs = summarization_tokenizer(text, return_tensors="pt", max_length=1024, truncation=True)
        
        # Generate summary
        summary_ids = summarization_model.generate(
            inputs["input_ids"],
            max_length=max_length,
            min_length=min_length,
            length_penalty=2.0,
            num_beams=4,
            early_stopping=True
        )
        
        # Decode the summary
        summary = summarization_tokenizer.decode(summary_ids[0], skip_special_tokens=True)
        return summary
    except Exception as e:
        print(f"Error generating summary: {str(e)}")
        return f"Summary generation failed: {str(e)}"

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

def translate_segments(segments: List[Dict], source_lang: str) -> List[Dict]:
    """Translate a batch of segments using local MarianMT model"""
    BATCH_SIZE = 10
    for i in range(0, len(segments), BATCH_SIZE):
        batch = segments[i:i + BATCH_SIZE]
        # Only translate segments with non-empty text
        batch_to_translate = [s for s in batch if s.get('text') and not s.get('text').isspace()]
        if not batch_to_translate:
            for segment in batch:
                segment['translation'] = '[No speech detected]'
            continue
        context_before = ""
        context_after = ""
        if i > 0:
            context_before = f"Context before: {segments[i-1].get('text', '')}\n"
        if i + BATCH_SIZE < len(segments):
            context_after = f"\nContext after: {segments[i+BATCH_SIZE].get('text', '')}"
        combined_text = context_before + "\n---\n".join([f"[{j}] {segment.get('text', '')}" for j, segment in enumerate(batch_to_translate)]) + context_after
        try:
            # Use local translation model instead of OpenAI
            tokenizer, model = get_marian_model(source_lang)
            
            # Split texts by [SEP] and translate each segment
            texts = combined_text.split("[SEP]")
            translations = []
            
            for text in texts:
                text = text.strip()
                if not text:
                    continue
                    
                # Translate using MarianMT
                inputs = tokenizer(text, return_tensors="pt", padding=True)
                translated = model.generate(**inputs)
                translation = tokenizer.decode(translated[0], skip_special_tokens=True)
                translations.append(translation)
            
            # Join translations with [SEP]
            translated_text = "\n[SEP]\n".join(translations)
            
            # Split translations and update segments
            translations = translated_text.split('[SEP]')
            for segment, translation in zip(batch_to_translate, translations):
                segment['translation'] = translation.strip()
            
            print("Successfully translated segments using local model")
        except Exception as e:
            print(f"Error in translation process: {str(e)}")
            # If translation fails, set placeholder translations
            for segment in batch_to_translate:
                segment['translation'] = f"[Translation pending for: {segment['text']}]"
    for segment in segments:
        if not segment.get('translation'):
            segment['translation'] = '[No speech detected]'
    return segments

def compress_audio(input_path: str, output_path: str, file_size_check: bool = True) -> str:
    """Compress audio file to reduce size while maintaining quality"""
    try:
        # Check if ffmpeg is available
        if not shutil.which('ffmpeg'):
            raise Exception("ffmpeg is not installed. Please install ffmpeg first.")

        # Default compression settings - good quality
        bitrate = '32k'  # Default bitrate
        sample_rate = '16000'  # Default sample rate
        
        # For larger files, check if we need stronger compression
        if file_size_check:
            file_size = os.path.getsize(input_path)
            # If file is close to or above 25MB (OpenAI's limit)
            if file_size > 20 * 1024 * 1024:  # 20MB threshold
                bitrate = '24k'  # Lower bitrate
                
            # If file is still very large
            if file_size > 30 * 1024 * 1024:  # 30MB threshold
                bitrate = '16k'  # Even lower bitrate
        
        # Convert to mono, reduce quality, and compress
        command = [
            'ffmpeg', '-i', input_path,
            '-ac', '1',  # Convert to mono
            '-ar', sample_rate,  # Sample rate 16kHz
            '-b:a', bitrate,  # Bitrate (adaptive based on size)
            output_path,
            '-y'  # Overwrite output file if it exists
        ]
        
        subprocess.run(command, check=True, capture_output=True)
        
        # If file is still too large for OpenAI (25MB limit), compress more aggressively
        if file_size_check and os.path.getsize(output_path) > 25 * 1024 * 1024:
            print(f"Audio still too large ({os.path.getsize(output_path) / (1024 * 1024):.1f} MB). Applying stronger compression...")
            # Try again with more aggressive settings
            command = [
                'ffmpeg', '-i', input_path,
                '-ac', '1',  # Convert to mono
                '-ar', '12000',  # Lower sample rate
                '-b:a', '10k',  # Much lower bitrate
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
        try:
            # Convert timestamps to SRT format
            start_seconds = float(segment.get('start', 0.0))
            end_seconds = float(segment.get('end', 0.0))
            
            # Get text content, handling missing translation more gracefully
            text_content = None
            if use_translation:
                # Use translation if available and not empty
                text_content = segment.get('translation')
                if not text_content or text_content.isspace():
                    print(f"Warning: Missing or empty translation for segment {i}, text: {segment.get('text', '[No Text]')}")
                    # Don't fall back to original text for missing translations
                    text_content = '[Translation Missing]'
            else:
                # Use original text
                text_content = segment.get('text')
                if not text_content or text_content.isspace():
                    print(f"Warning: Missing or empty text for segment {i}")
                    text_content = '[No Text Available]'
            
            # Ensure text is properly encoded if it happens to be bytes
            if isinstance(text_content, bytes):
                try:
                    text_content = text_content.decode('utf-8')
                except UnicodeDecodeError:
                    print(f"Warning: Could not decode segment {i} text. Using placeholder.")
                    text_content = '[Encoding Error]'
            
            # Ensure text_content is a string before proceeding
            if not isinstance(text_content, str):
                print(f"Warning: Segment {i} content is not a string ({type(text_content)}). Converting.")
                text_content = str(text_content)
            
            # Format subtitle entry
            srt_content.extend([
                str(i),
                f"{format_srt_timestamp(start_seconds)} --> {format_srt_timestamp(end_seconds)}",
                text_content.strip(),  # Ensure no leading/trailing whitespace
                ""  # Empty line between entries
            ])
        except Exception as e:
            print(f"Error processing segment {i}: {str(e)}")
            # Add an error placeholder for this segment
            srt_content.extend([
                str(i),
                "00:00:00,000 --> 00:00:00,001",
                f"[Error: Failed to process segment {i}]",
                ""
            ])
    
    return "\n".join(srt_content)

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

        initial_bitrate = '32k'
        initial_sample_rate = '16000'
        print(f"Attempting initial audio extraction with bitrate={initial_bitrate}, sample_rate={initial_sample_rate}")

        # First extract audio with standard compression settings
        command = [
            'ffmpeg',
            '-i', input_path,
            '-vn',  # Skip video
            '-ac', '1',  # Convert to mono
            '-ar', initial_sample_rate,
            '-b:a', initial_bitrate,
            output_path,
            '-y'  # Overwrite output file if it exists
        ]
        
        subprocess.run(command, check=True, capture_output=True)
        
        # Check if the resulting file is too large for OpenAI's Whisper API (25MB limit)
        if os.path.exists(output_path):
            output_size_mb = os.path.getsize(output_path) / (1024 * 1024)
            print(f"Audio extracted. Size: {output_size_mb:.1f} MB")
            
            if output_size_mb > 25:
                print(f"Audio file too large ({output_size_mb:.1f} MB). Applying stronger compression...")
                stronger_bitrate = '16k'
                stronger_sample_rate = '12000'
                print(f"Applying stronger compression: bitrate={stronger_bitrate}, sample_rate={stronger_sample_rate}")
                # Try again with more aggressive settings
                command = [
                    'ffmpeg',
                    '-i', input_path,
                    '-vn',  # Skip video
                    '-ac', '1',  # Convert to mono
                    '-ar', stronger_sample_rate,
                    '-b:a', stronger_bitrate,
                    output_path,
                    '-y'  # Overwrite output file if it exists
                ]
                subprocess.run(command, check=True, capture_output=True)
                output_size_mb = os.path.getsize(output_path) / (1024 * 1024)
                print(f"Audio size after stronger compression: {output_size_mb:.1f} MB")
            
                # If still too large, compress even more aggressively
                if output_size_mb > 25:
                    print(f"Audio still too large ({output_size_mb:.1f} MB). Applying maximum compression...")
                    max_bitrate = '10k'
                    max_sample_rate = '8000'
                    print(f"Applying maximum compression: bitrate={max_bitrate}, sample_rate={max_sample_rate}")
                    command = [
                        'ffmpeg',
                        '-i', input_path,
                        '-vn',  # Skip video
                        '-ac', '1',  # Convert to mono
                        '-ar', max_sample_rate,
                        '-b:a', max_bitrate,
                        output_path,
                        '-y'  # Overwrite output file if it exists
                    ]
                    subprocess.run(command, check=True, capture_output=True)
                    
                    # Log final size
                    final_size_mb = os.path.getsize(output_path) / (1024 * 1024)
                    print(f"Final audio size after maximum compression: {final_size_mb:.1f} MB")
                    
                    if final_size_mb > 25:
                        print("WARNING: Audio still exceeds OpenAI's 25MB limit after maximum compression. Transcription might fail or be inaccurate.")
        else:
             print("WARNING: Output audio file does not exist after initial extraction attempt.")
             
    except subprocess.CalledProcessError as e:
        raise Exception(f"Error processing video with ffmpeg: {e.stderr.decode()}")

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
            '-vf', 'scale=1280:-1',  # Scale to a larger width (e.g., 1280px) instead of 320px
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
    
    # Ensure static directories exist
    os.makedirs(os.path.join("static", "videos"), exist_ok=True)
    os.makedirs(os.path.join("static", "screenshots"), exist_ok=True)
    print("Static directories initialized")

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
            # Set a 10GB limit for /transcribe/ endpoint
            request._body_size_limit = 10 * 1024 * 1024 * 1024  # 10GB
            request.scope["max_content_size"] = 10 * 1024 * 1024 * 1024  # 10GB
        return await call_next(request)

app.add_middleware(LargeUploadMiddleware)

# Configure OpenAI with a custom httpx client
http_client = httpx.Client()
client = None  # Initialize as None since we're not using OpenAI anymore

# Initialize faster-whisper model for local transcription
whisper_model_size = os.getenv("FASTWHISPER_MODEL", "small")  # Default to 'small' for speed
whisper_model_device = os.getenv("FASTWHISPER_DEVICE", "cpu") # Default to 'cpu' for compatibility
whisper_compute_type = os.getenv("FASTWHISPER_COMPUTE_TYPE", "int8")  # Use 'int8' for CPU compatibility
local_whisper_model = WhisperModel(
    whisper_model_size,
    device=whisper_model_device,
    compute_type=whisper_compute_type
)

# Cache for loaded MarianMT models
marian_models = {}
def get_marian_model(source_lang):
    model_name = f"Helsinki-NLP/opus-mt-{source_lang}-en"
    if model_name not in marian_models:
        tokenizer = MarianTokenizer.from_pretrained(model_name)
        model = MarianMTModel.from_pretrained(model_name)
        marian_models[model_name] = (tokenizer, model)
    return marian_models[model_name]

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
async def transcribe_video(
    file: UploadFile, 
    request: Request, 
    file_path: str = None,
    language: str = Form(None)  # Added language parameter
) -> Dict:
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
        # Print language if provided
        if language:
            print(f"Language specified: {language}")
        else:
            print("Language: Auto-detect")
            
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
                        if total_size > 10 * 1024 * 1024 * 1024:  # 10GB limit
                            raise HTTPException(
                                status_code=413,
                                detail="File too large. Maximum size is 10GB."
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
            
            # Save a permanent copy of the video file
            permanent_storage_dir = os.path.join("static", "videos")
            os.makedirs(permanent_storage_dir, exist_ok=True)
            permanent_file_path = os.path.join(permanent_storage_dir, f"{video_hash}{file_extension}")
            # Check if file already exists to avoid unnecessary copy
            if not os.path.exists(permanent_file_path):
                 shutil.copy2(temp_input_path, permanent_file_path)
                 print(f"Saved permanent copy of video to: {permanent_file_path}")
            else:
                 print(f"Permanent copy already exists at: {permanent_file_path}")
            
            print("\nExtracting and compressing audio...")
            audio_processed = False
            try:
                # --- Force Chunking --- 
                # We will now always chunk the audio using extract_audio, regardless of initial size,
                # as this seems to help Whisper with long files.
                # The old single-file processing path will be removed.
                
                print("Forcing audio splitting into chunks using moviepy...")
                chunk_duration_seconds = 300 # 5-minute chunks
                print(f"Using moviepy to extract audio chunks ({chunk_duration_seconds}s duration)...")
                
                # Ensure extract_audio handles compression for each chunk
                # Assuming extract_audio compresses each chunk and returns paths
                audio_chunks = extract_audio(temp_input_path, chunk_duration=chunk_duration_seconds)  
                
                if not audio_chunks:
                    raise Exception("Failed to split audio into chunks using moviepy")
                
                print(f"Split audio into {len(audio_chunks)} chunks.")
                
                # Transcribe each chunk and combine results
                all_segments = []
                audio_language = language # Use provided language initially
                full_text = []
                
                total_chunks = len(audio_chunks)
                for i, chunk_path in enumerate(audio_chunks):
                    print(f"\nProcessing chunk {i+1}/{total_chunks}: {os.path.basename(chunk_path)}")
                    
                    chunk_size_mb = 0
                    if os.path.exists(chunk_path):
                        chunk_size_mb = os.path.getsize(chunk_path) / (1024 * 1024)
                        print(f"Chunk size: {chunk_size_mb:.2f} MB")
                    else:
                         print(f"WARNING: Chunk file not found: {chunk_path}. Skipping.")
                         continue

                    # If chunk is still too large (shouldn't happen often with 5min chunks, but check anyway)
                    if chunk_size_mb > 25:
                        print(f"WARNING: Chunk {i+1} ({chunk_size_mb:.2f} MB) exceeds 25MB limit. Skipping this chunk.")
                        continue
                    
                    with open(chunk_path, "rb") as chunk_file:
                        # Transcribe with Whisper API, passing language if provided
                        print(f"Calling Whisper API for chunk {i+1}...")
                        # Use local whisper model instead of OpenAI
                        segments, info = local_whisper_model.transcribe(
                            chunk_path,
                            task="translate" if language and language.lower() != "en" else "transcribe",
                            language=language if language else None,
                            beam_size=1  # Faster processing
                        )
                        
                        # Create a synthetic response object to match OpenAI's format
                        chunk_response = type('obj', (object,), {
                            'text': " ".join([seg.text for seg in segments]),
                            'language': info.language,
                            'segments': [{
                                'start': seg.start,
                                'end': seg.end,
                                'text': seg.text
                            } for seg in segments]
                        })
                        
                        print(f"Transcription received for chunk {i+1}.")

                        # Store language (use detected language if none provided)
                        detected_language = chunk_response.language
                        print(f"Detected language for chunk {i+1}: {detected_language}")
                        if audio_language is None: # Set language on first chunk if not provided
                            audio_language = detected_language
                            print(f"Overall audio language set to: {audio_language}")
                        
                        # Collect text and segments
                        full_text.append(chunk_response.text)
                        
                        # Adjust segment timings based on chunk position
                        chunk_start_offset_seconds = i * chunk_duration_seconds 
                        print(f"Adjusting segment times for chunk {i+1} with offset: {chunk_start_offset_seconds}s")
                        if hasattr(chunk_response, 'segments') and chunk_response.segments:
                            print(f"Raw Whisper API response for chunk {i+1}: {chunk_response}")
                            non_empty_count = 0
                            for segment in chunk_response.segments:
                                segment_start = segment.get('start', 0.0)
                                segment_end = segment.get('end', 0.0)
                                segment_text = segment.get('text', '')
                                print(f"  Segment: start={segment_start}, end={segment_end}, text={repr(segment_text)}")
                                if segment_text and not segment_text.isspace():
                                    segment['start'] = segment_start + chunk_start_offset_seconds
                                    segment['end'] = segment_end + chunk_start_offset_seconds
                                    all_segments.append(segment)
                                    non_empty_count += 1
                                else:
                                    print(f"  -> Marked as [No speech detected]")
                                    all_segments.append({
                                        'start': segment_start + chunk_start_offset_seconds,
                                        'end': segment_end + chunk_start_offset_seconds,
                                        'text': '[No speech detected]',
                                        'translation': '[No speech detected]'
                                    })
                            print(f"Chunk {i+1}: Detected language: {chunk_response.language}, Non-empty segments: {non_empty_count}, Total segments: {len(chunk_response.segments)}")
                        else:
                             print(f"Warning: No segments found in response for chunk {i+1}")
                
                # Create a synthetic response object to hold the combined results
                class SyntheticResponse:
                    def __init__(self):
                        self.text = ""
                        self.segments = []
                        self.language = "en" # Default language

                response = SyntheticResponse()
                response.text = " ".join(full_text)
                response.segments = all_segments
                # Use the determined language (provided or detected from first chunk)
                response.language = audio_language or "en" 
                print(f"\nCombined transcription from chunks. Total segments: {len(all_segments)}, Language: {response.language}")
                audio_processed = True # Mark as processed via chunks

                # --- Removed the old single-file transcription block --- 
                # elif audio_processed: 
                #     # ... (code that transcribed temp_output_path directly) ...
                
                if not audio_processed: 
                    # This case should not be reached anymore with forced chunking
                    raise Exception("Audio processing failed. Chunk processing did not succeed.")

            except Exception as e:
                print(f"Audio processing or transcription error: {str(e)}")
                # Log traceback for detailed debugging
                import traceback
                traceback.print_exc() 
                if hasattr(e, '__dict__'):
                    print(f"Error details: {e.__dict__}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Error during audio processing or transcription: {str(e)}"
                )

            # Translate if not in English
            try:
                # Use the determined language for translation check
                source_language_for_translation = response.language
                print(f"\nChecking language for translation: {source_language_for_translation}")
                if source_language_for_translation and source_language_for_translation.lower() not in ['en', 'english']:
                    print(f"Language is not English. Translating segments from '{source_language_for_translation}'...")
                    # Ensure segments exist before attempting translation
                    if hasattr(response, 'segments') and response.segments:
                        response.segments = translate_segments(response.segments, source_language_for_translation)
                        print("Translation completed successfully")
                    else:
                         print("No segments found to translate.")
                else:
                    print("Language is English or undetermined. No translation needed.")
            except Exception as e:
                print(f"Translation error: {str(e)}")
                import traceback
                traceback.print_exc()
                # Continue even if translation fails, but log it

            # Continue with the rest of the function
            # Extract screenshots for each segment if it's a video file
            screenshot_count = 0
            if file_extension in {'.mp4', '.mpeg', '.webm', '.mov'}: # Added .mov
                 print("\nExtracting screenshots for video segments...")
                 # Ensure response.segments exists and is iterable
                 if hasattr(response, 'segments') and response.segments:
                    total_segments_for_screenshots = len(response.segments)
                    print(f"Attempting to extract screenshots for {total_segments_for_screenshots} segments.")
                    for i, segment in enumerate(response.segments):
                        #print(f"Processing segment {i+1}/{total_segments_for_screenshots} for screenshot (Start: {segment.start:.2f})")
                        screenshot_filename = f"{video_hash}_{segment['start']:.2f}.jpg" # Use hash to ensure uniqueness
                        screenshot_path = os.path.join(screenshots_dir, screenshot_filename)
                        
                        # Ensure segment.start is a valid number
                        segment_start_time = segment.get('start', None)
                        if segment_start_time is None or not isinstance(segment_start_time, (int, float)):
                             print(f"Warning: Invalid start time for segment {i+1}. Skipping screenshot.")
                             segment['screenshot_url'] = None
                             continue

                        success = extract_screenshot(temp_input_path, segment_start_time, screenshot_path)
                        if success and os.path.exists(screenshot_path):
                            # Add screenshot URL to segment
                            screenshot_url = f"/static/screenshots/{screenshot_filename}"
                            segment['screenshot_url'] = screenshot_url
                            screenshot_count += 1
                            #print(f"Segment {i+1}: Screenshot added - {screenshot_url}")
                        else:
                            segment['screenshot_url'] = None
                            #print(f"Segment {i+1}: Failed to add screenshot.")
                    print(f"\nFinished screenshot extraction. Successfully added {screenshot_count} screenshots.")
                 else:
                      print("No segments available to extract screenshots from.")
            else:
                 print("\nFile is not a video format. Skipping screenshot extraction.")

            # Process transcription result
            print("\nProcessing final transcription result...")
            result = {
                "filename": file.filename,
                "video_hash": video_hash, # Include hash in response
                "transcription": {
                    "text": getattr(response, 'text', ''), # Safely get text
                    # Store the determined language (provided or detected)
                    "language": getattr(response, 'language', 'unknown'), # Safely get language
                    "segments": []
                }
            }

            # Convert segments to dictionary format
            if hasattr(response, 'segments') and response.segments:
                for segment in response.segments:
                    # Use dict access for all fields
                    segment_id = segment.get('id', None)
                    segment_start = segment.get('start', 0.0)
                    segment_end = segment.get('end', 0.0)
                    segment_text = segment.get('text', '')
                    segment_translation = segment.get('translation', None)
                    segment_screenshot_url = segment.get('screenshot_url', None)
                    segment_dict = {
                        "id": segment_id,
                        "start": segment_start,
                        "end": segment_end,
                        "start_time": format_timestamp(segment_start),
                        "end_time": format_timestamp(segment_end),
                        "text": segment_text
                    }
                    if segment_translation:
                        segment_dict["translation"] = segment_translation
                    if segment_screenshot_url:
                        segment_dict["screenshot_url"] = segment_screenshot_url
                    result["transcription"]["segments"].append(segment_dict)
            else:
                print("Warning: No segments found in the final response object.")

            # --- Ensure unique IDs for all segments --- 
            print("\nEnsuring unique IDs for all segments before storing...")
            assigned_ids = set()
            final_segments = []
            for segment_dict in result["transcription"]["segments"]:
                # Always generate a new UUID to guarantee uniqueness across chunks
                new_id = str(uuid.uuid4())
                # Ensure the generated UUID is truly unique (highly unlikely collision, but safe)
                while new_id in assigned_ids:
                    new_id = str(uuid.uuid4())
                
                segment_dict["id"] = new_id # Assign the guaranteed unique ID
                assigned_ids.add(new_id)
                final_segments.append(segment_dict) # Add to the final list
            
            # Replace the segments list with the one containing guaranteed unique IDs
            result["transcription"]["segments"] = final_segments
            print(f"Assigned unique UUIDs to {len(result['transcription']['segments'])} segments.")
            # --- End of unique ID assignment --- 

            # Store the transcription data, including the permanent file path
            print(f"\nStoring transcription in database with hash: {video_hash}")
            store_transcription(video_hash, file.filename, result, permanent_file_path)
            
            # Store as last transcription
            last_transcription_data = result
            request.app.state.last_transcription = result
            
            total_duration = time.time() - start_time
            result["processing_time"] = format_eta(int(total_duration))
            
            # Add video URL to the result using the hash
            result["video_url"] = f"/video/{video_hash}"
            
            print(f"\nTranscription processing completed successfully in {result['processing_time']}.")
            print(f"Returning result for {result['filename']} (Hash: {result['video_hash']})")
            return result
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
    
    # Get source language and normalize it
    source_lang = transcription['transcription']['language'].lower()
    
    # For English subtitles, check if we need translations
    use_translation = False
    if language == 'english' and source_lang not in ['en', 'english']:
        # First, try to translate any missing translations
        segments_to_translate = []
        for segment in transcription['transcription']['segments']:
            if 'translation' not in segment or not segment['translation']:
                segments_to_translate.append(segment)
        
        if segments_to_translate:
            print(f"Found {len(segments_to_translate)} segments without translation. Attempting to translate...")
            try:
                # Use local translation model
                tokenizer, model = get_marian_model(source_lang)
                
                # Translate each segment individually
                for segment in segments_to_translate:
                    text = segment['text'].strip()
                    if not text:
                        continue
                    
                    # Translate using MarianMT
                    inputs = tokenizer(text, return_tensors="pt", padding=True)
                    translated = model.generate(**inputs)
                    translation = tokenizer.decode(translated[0], skip_special_tokens=True)
                    segment['translation'] = translation.strip()
                
                print("Successfully translated missing segments using local model")
                use_translation = True
            except Exception as e:
                print(f"Error in translation process: {str(e)}")
                # If translation fails, set placeholder translations
                for segment in segments_to_translate:
                    segment['translation'] = f"[Translation pending for: {segment['text']}]"
                use_translation = False
    
    try:
        srt_content = generate_srt(transcription['transcription']['segments'], use_translation)
        
        # Create filename based on original video and language
        original_filename = transcription['filename']
        base_name = os.path.splitext(original_filename)[0]
        srt_filename = f"{base_name}_{language}.srt"
        
        # Return SRT file with correct content type and headers
        return Response(
            content=srt_content.encode('utf-8'),
            media_type="application/x-subrip",
            headers={
                "Content-Disposition": f'attachment; filename="{srt_filename}"',
                "Content-Type": "application/x-subrip; charset=utf-8"
            }
        )
    except Exception as e:
        print(f"Error generating subtitles: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate subtitles: {str(e)}"
        )

def _time_to_seconds(time_str: str) -> float:
    """Convert HH:MM:SS time string to seconds"""
    try:
        h, m, s = time_str.split(':')
        return int(h) * 3600 + int(m) * 60 + int(s)
    except Exception as e:
        print(f"Error converting time to seconds: {str(e)}")
        return 0.0

def _time_diff_minutes(start_time: str, end_time: str) -> float:
    """Calculate the difference between two timestamps in minutes"""
    try:
        start_seconds = _time_to_seconds(start_time)
        end_seconds = _time_to_seconds(end_time)
        return (end_seconds - start_seconds) / 60
    except Exception as e:
        print(f"Error calculating time difference: {str(e)}")
        return 0.0

@app.post("/generate_summary/")
async def generate_summary(request: Request) -> Dict:
    """Generate section summaries from transcription using local model"""
    if not hasattr(request.app.state, 'last_transcription'):
        raise HTTPException(status_code=404, detail="No transcription available. Please transcribe a video first.")
    
    # Get the latest transcription data to ensure we're using the correct movie
    transcription = request.app.state.last_transcription
    
    # Include the filename in the response for verification
    filename = transcription.get('filename', 'unknown_filename')
    print(f"Generating summary for: {filename}")
    
    segments = transcription['transcription']['segments']
    print(f"Found {len(segments)} segments for summarization")
    
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
    
    print(f"Created {len(sections)} logical sections for summarization")
    
    # Generate summary for each section
    summaries = []
    for section_index, section in enumerate(sections):
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
            # Generate concise summary using local model
            summary = generate_local_summary(text_to_summarize)
            
            # Generate descriptive title
            # For now, just use a simple approach
            title = f"Section {section['start']}-{section['end']}"
            
            summaries.append({
                "title": title,
                "start": section["start"],
                "end": section["end"],
                "summary": summary
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
    
    # Log summary generation results
    print(f"Generated {len(summaries)} section summaries")
    
    return {
        "summaries": summaries,
        "filename": filename,  # Include filename for verification
        "sections_count": len(sections)
    }

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

    # Ensure all translations are present if language is not English
    try:
        lang = transcription.get('transcription', {}).get('language', '').lower()
        segments = transcription.get('transcription', {}).get('segments', [])
        if lang and lang not in ['en', 'english']:
            missing = [s for s in segments if not s.get('translation')]
            if missing:
                print(f"Translating {len(missing)} missing segments for video_hash={video_hash}...")
                translated_segments = translate_segments(segments, lang)
                for i, seg in enumerate(segments):
                    seg['translation'] = translated_segments[i].get('translation', seg.get('text', '[Translation missing]'))
                store_transcription(video_hash, transcription.get('filename', ''), transcription, transcription.get('file_path'))
                print(f"Translation complete and saved for video_hash={video_hash}.")
    except Exception as e:
        print(f"Error ensuring translations in /transcription/{{video_hash}}: {e}")

    # Log all segment details for debugging
    try:
        segments = transcription.get('transcription', {}).get('segments', [])
        print(f"\n--- SEGMENTS for video_hash={video_hash} ---")
        for idx, seg in enumerate(segments):
            print(f"Segment {idx}: id={seg.get('id')}, start={seg.get('start_time')}, text={repr(seg.get('text'))}, translation={repr(seg.get('translation'))}")
        print(f"--- END SEGMENTS ({len(segments)} total) ---\n")
    except Exception as e:
        print(f"Error logging segments: {e}")
    
    # Update the last_transcription_data and request state
    global last_transcription_data
    last_transcription_data = transcription
    request.app.state.last_transcription = transcription
    
    return transcription

@app.get("/video/{video_hash}")
async def get_video_file(video_hash: str, request: Request):
    """Serve the video file for a specific transcription by hash"""
    try:
        print(f"Attempting to serve video with hash: {video_hash}")
        transcription = get_transcription(video_hash)
        
        if not transcription:
            print(f"Transcription not found for hash: {video_hash}")
            raise HTTPException(status_code=404, detail="Transcription not found")
            
        if 'file_path' not in transcription or not transcription['file_path']:
            print(f"No file_path in transcription with hash: {video_hash}")
            raise HTTPException(status_code=404, detail="Video file path not found in transcription data")
        
        file_path = transcription['file_path']
        print(f"File path from transcription: {file_path}")
        
        if not os.path.exists(file_path):
            print(f"File does not exist at path: {file_path}")
            
            # Try to find the file in the static/videos directory
            video_dir = os.path.join("static", "videos")
            possible_files = [
                os.path.join(video_dir, f"{video_hash}.mp4"),
                os.path.join(video_dir, f"{video_hash}.webm"),
                os.path.join(video_dir, f"{video_hash}.mov"),
                os.path.join(video_dir, f"{video_hash}.mp3")
            ]
            
            found_file = None
            for p in possible_files:
                if os.path.exists(p):
                    found_file = p
                    break
                    
            if found_file:
                print(f"Found alternative file: {found_file}")
                file_path = found_file
                
                # Update the database with the correct file path
                conn = sqlite3.connect('transcriptions.db')
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE transcriptions SET file_path = ? WHERE video_hash = ?",
                    (file_path, video_hash)
                )
                conn.commit()
                conn.close()
                print(f"Updated database with correct file path: {file_path}")
            else:
                raise HTTPException(status_code=404, detail=f"Video file does not exist: {file_path}")
        
        # Get file extension to determine mime type
        extension = file_path.split('.')[-1].lower()
        media_type = "video/mp4"  # Default
        if extension == "webm":
            media_type = "video/webm"
        elif extension == "mov":
            media_type = "video/quicktime"
        elif extension == "mp3":
            media_type = "audio/mpeg"
            
        # Get file size
        file_size = os.path.getsize(file_path)
        
        # Handle range requests
        range_header = request.headers.get("range")
        
        if range_header:
            try:
                # Parse range header
                start_b = range_header.replace("bytes=", "").split("-")[0]
                start = int(start_b) if start_b else 0
                end = min(start + 1024*1024, file_size - 1)  # Stream in 1MB chunks
                
                # Create response with partial content
                headers = {
                    "Content-Range": f"bytes {start}-{end}/{file_size}",
                    "Accept-Ranges": "bytes",
                    "Content-Length": str(end - start + 1),
                    "Content-Type": media_type
                }
                
                return Response(
                    content=open(file_path, "rb").read()[start:end+1],
                    status_code=206,
                    headers=headers
                )
            except Exception as e:
                print(f"Error handling range request: {str(e)}")
                # Fall back to full file response
                pass
            
        print(f"Serving full file {file_path} with media type {media_type}")
        return FileResponse(
            file_path,
            media_type=media_type,
            filename=os.path.basename(file_path),
            headers={"Accept-Ranges": "bytes"}
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Unexpected error in get_video_file: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error serving video: {str(e)}")

@app.post("/update_file_path/{video_hash}")
async def update_file_path(video_hash: str, file: UploadFile):
    """Update an existing transcription with a new file"""
    try:
        # Check if transcription exists
        transcription = get_transcription(video_hash)
        if not transcription:
            raise HTTPException(status_code=404, detail="Transcription not found")
        
        # Validate file type
        allowed_extensions = {'.mp4', '.mpeg', '.mpga', '.m4a', '.wav', '.webm', '.mp3'}
        file_extension = Path(file.filename).suffix.lower()
        if file_extension not in allowed_extensions:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file format. Supported formats: {', '.join(allowed_extensions)}"
            )
        
        # Save the file to the permanent storage
        permanent_storage_dir = os.path.join("static", "videos")
        os.makedirs(permanent_storage_dir, exist_ok=True)
        permanent_file_path = os.path.join(permanent_storage_dir, f"{video_hash}{file_extension}")
        
        # Save file in chunks
        with open(permanent_file_path, "wb") as buffer:
            while chunk := await file.read(1024 * 1024):  # 1MB chunks
                buffer.write(chunk)
        
        # Update the transcription in the database with the new file path
        conn = sqlite3.connect('transcriptions.db')
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE transcriptions SET file_path = ? WHERE video_hash = ?",
            (permanent_file_path, video_hash)
        )
        conn.commit()
        conn.close()
        
        return {"success": True, "message": "File path updated successfully", "file_path": permanent_file_path}
    except Exception as e:
        print(f"Error updating file path: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error updating file path: {str(e)}")

@app.delete("/transcription/{video_hash}")
async def delete_transcription(video_hash: str):
    """Delete a transcription from the database by hash"""
    try:
        # Check if transcription exists
        transcription = get_transcription(video_hash)
        if not transcription:
            raise HTTPException(status_code=404, detail="Transcription not found")
        
        # Delete the file if it exists
        if 'file_path' in transcription and transcription['file_path']:
            file_path = transcription['file_path']
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    print(f"Deleted file: {file_path}")
                except Exception as e:
                    print(f"Error deleting file {file_path}: {str(e)}")
        
        # Delete from database
        conn = sqlite3.connect('transcriptions.db')
        cursor = conn.cursor()
        cursor.execute("DELETE FROM transcriptions WHERE video_hash = ?", (video_hash,))
        conn.commit()
        conn.close()
        
        return {"success": True, "message": "Transcription deleted successfully"}
    except Exception as e:
        print(f"Error deleting transcription: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error deleting transcription: {str(e)}")

# Endpoint for local transcription using faster-whisper
@app.post("/transcribe_local/")
async def transcribe_local(file: UploadFile, request: Request) -> Dict:
    """Transcribe uploaded audio/video file locally using faster-whisper (optimized for speed, direct English output)."""
    global last_transcription_data
    
    print("[INFO] Using local faster-whisper for transcription (via /transcribe_local/ endpoint)")
    try:
        suffix = Path(file.filename).suffix
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            content = await file.read()
            tmp.write(content)
            temp_path = tmp.name

        # Generate hash for the file
        video_hash = generate_file_hash(temp_path)
        print(f"Generated hash for video: {video_hash}")
        
        # Check if we already have a transcription for this file
        existing_transcription = get_transcription(video_hash)
        if existing_transcription:
            print(f"Found existing transcription for {file.filename} with hash {video_hash}")
            last_transcription_data = existing_transcription
            request.app.state.last_transcription = existing_transcription
            return existing_transcription

        # Save a permanent copy of the video file
        permanent_storage_dir = os.path.join("static", "videos")
        os.makedirs(permanent_storage_dir, exist_ok=True)
        permanent_file_path = os.path.join(permanent_storage_dir, f"{video_hash}{suffix}")
        if not os.path.exists(permanent_file_path):
            shutil.copy2(temp_path, permanent_file_path)
            print(f"Saved permanent copy of video to: {permanent_file_path}")
        else:
            print(f"Permanent copy already exists at: {permanent_file_path}")

        # Get audio duration
        try:
            duration = get_audio_duration(temp_path)
            duration_str = str(timedelta(seconds=int(duration)))
        except Exception as e:
            print(f"Error getting duration: {e}")
            duration_str = "Unknown"

        start_time = time.time()
        # --- KEY: Fast, direct translation, beam_size=1 ---
        segments, info = local_whisper_model.transcribe(
            temp_path,
            task="translate",   # Translates to English in one step
            beam_size=1         # Much faster, tiny accuracy drop
        )
        processing_time = time.time() - start_time

        # Format segments to match expected structure
        formatted_segments = []
        for i, seg in enumerate(segments):
            formatted_segments.append({
                "id": str(uuid.uuid4()),
                "start": seg.start,
                "end": seg.end,
                "start_time": format_timestamp(seg.start),
                "end_time": format_timestamp(seg.end),
                "text": seg.text,    # Now always English if non-English input!
                # Remove manual 'translation' field: text is the translation.
            })

        # Extract screenshots if it's a video file
        screenshots_dir = os.path.join("static", "screenshots")
        os.makedirs(screenshots_dir, exist_ok=True)
        screenshot_count = 0
        
        if suffix.lower() in {'.mp4', '.mpeg', '.webm', '.mov'}:
            print("\nExtracting screenshots for video segments...")
            for segment in formatted_segments:
                screenshot_filename = f"{video_hash}_{segment['start']:.2f}.jpg"
                screenshot_path = os.path.join(screenshots_dir, screenshot_filename)
                
                success = extract_screenshot(temp_path, segment['start'], screenshot_path)
                if success and os.path.exists(screenshot_path):
                    screenshot_url = f"/static/screenshots/{screenshot_filename}"
                    segment["screenshot_url"] = screenshot_url
                    screenshot_count += 1
                else:
                    segment["screenshot_url"] = None
            
            print(f"\nFinished screenshot extraction. Successfully added {screenshot_count} screenshots.")

        result = {
            "filename": file.filename,
            "video_hash": video_hash,
            "transcription": {
                "text": "".join([seg.text for seg in segments]),
                "language": info.language,
                "duration": duration_str,
                "segments": formatted_segments,
                "processing_time": format_eta(int(processing_time))
            }
        }

        # Store the transcription data
        store_transcription(video_hash, file.filename, result, permanent_file_path)
        
        # Store as last transcription in both global variable and request state
        last_transcription_data = result
        request.app.state.last_transcription = result
        
        # Add video URL to the result
        result["video_url"] = f"/video/{video_hash}"

        # Clean up temporary file
        try:
            os.unlink(temp_path)
        except Exception as e:
            print(f"Error cleaning up temp file: {e}")

        return result
    except Exception as e:
        print(f"Error in local transcription: {e}")
        raise HTTPException(status_code=500, detail=str(e))

def get_audio_duration(file_path: str) -> float:
    """Get the duration of an audio/video file using ffmpeg."""
    try:
        probe = ffmpeg.probe(file_path)
        duration = float(probe['format']['duration'])
        return duration
    except Exception as e:
        print(f"Error probing file duration: {e}")
        return 0.0

@app.post("/translate_local/")
async def translate_local_endpoint(request: Request) -> Dict:
    """Translate text to English locally using MarianMT."""
    try:
        body = await request.json()
        text = body.get('text')
        source_lang = body.get('source_lang')
        if not text or not source_lang:
            raise HTTPException(status_code=400, detail="Missing text or source language")
        try:
            tokenizer, model = get_marian_model(source_lang)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Unsupported or unavailable language model: {source_lang}")
        # MarianMT expects a list of sentences
        if isinstance(text, str):
            text_list = [text]
        else:
            text_list = text
        inputs = tokenizer(text_list, return_tensors="pt", padding=True)
        translated = model.generate(**inputs)
        translations = [tokenizer.decode(t, skip_special_tokens=True) for t in translated]
        # Return single string if input was string
        result = translations[0] if isinstance(text, str) else translations
        return {
            "translation": result,
            "source_language": source_lang,
            "target_language": "en"
        }
    except Exception as e:
        print(f"Local translation error: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Local translation failed: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 