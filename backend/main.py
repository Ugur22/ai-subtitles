import os
import traceback
from fastapi import FastAPI, UploadFile, HTTPException, Request, Response, Form
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# Load environment variables immediately
load_dotenv()

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
from fastapi.responses import FileResponse, StreamingResponse
import uuid
from faster_whisper import WhisperModel
# MarianMT for local translation
from transformers import MarianMTModel, MarianTokenizer
# Import the necessary libraries for local summarization
from transformers import pipeline, AutoTokenizer, AutoModelForSeq2SeqLM
import torch

# Import speaker diarization module
try:
    from speaker_diarization import SpeakerDiarizer, format_speaker_label
    SPEAKER_DIARIZATION_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Speaker diarization not available: {str(e)}")
    SPEAKER_DIARIZATION_AVAILABLE = False

# Import LLM and vector store modules
try:
    from llm_providers import llm_manager
    from vector_store import vector_store
    LLM_AVAILABLE = True
except ImportError as e:
    print(f"Warning: LLM features not available: {str(e)}")
    LLM_AVAILABLE = False

# Global variable to store the last transcription
last_transcription_data = None

# Global variable for speaker diarization
speaker_diarizer = None

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

# Speaker Diarization functions
def get_speaker_diarizer():
    """Get or initialize the speaker diarization pipeline"""
    global speaker_diarizer

    if not SPEAKER_DIARIZATION_AVAILABLE:
        print("Speaker diarization module not available")
        return None

    # Check if feature is enabled
    enable_diarization = os.getenv("ENABLE_SPEAKER_DIARIZATION", "true").lower() == "true"
    if not enable_diarization:
        print("Speaker diarization is disabled in .env")
        return None

    if speaker_diarizer is None:
        try:
            hf_token = os.getenv("HUGGINGFACE_TOKEN")
            if not hf_token:
                print("Warning: HUGGINGFACE_TOKEN not found in .env file")
                print("Speaker diarization will be disabled")
                print("Get token from: https://huggingface.co/settings/tokens")
                print("Accept conditions at: https://huggingface.co/pyannote/speaker-diarization")
                return None

            speaker_diarizer = SpeakerDiarizer(use_auth_token=hf_token)
            print("Speaker diarization module initialized successfully")
        except Exception as e:
            print(f"Error initializing speaker diarization: {str(e)}")
            return None

    return speaker_diarizer

def add_speaker_labels(audio_path: str, segments: List[Dict], num_speakers: int = None, min_speakers: int = None, max_speakers: int = None) -> List[Dict]:
    """
    Add speaker labels to transcription segments

    Args:
        audio_path: Path to the audio file
        segments: List of transcription segments
        num_speakers: Optional number of speakers (if known)
        min_speakers: Optional minimum number of speakers
        max_speakers: Optional maximum number of speakers

    Returns:
        Segments with speaker labels added
    """
    try:
        diarizer = get_speaker_diarizer()

        if diarizer is None:
            print("Speaker diarization not available, adding default speaker labels...")
            # Add default speaker to all segments
            for seg in segments:
                seg['speaker'] = "SPEAKER_00"
            return segments

        print(f"\n{'='*60}")
        print("🎤 Starting speaker diarization...")
        print(f"{'='*60}")

        # Get min/max speakers from environment or use defaults
        # PRIORITIZE function arguments over environment variables
        env_min = int(os.getenv("MIN_SPEAKERS", "1"))
        env_max = int(os.getenv("MAX_SPEAKERS", "5")) # Changed default from 10 to 5

        final_min_speakers = min_speakers if min_speakers is not None else env_min
        final_max_speakers = max_speakers if max_speakers is not None else env_max

        # Prepare audio for diarization
        # Pyannote prefers WAV files and sometimes fails with MP4/other containers
        temp_wav_path = None
        diarization_input_path = audio_path

        try:
            # Check if conversion is needed (if not .wav or if we just want to be safe)
            if not audio_path.lower().endswith('.wav'):
                print("Converting input to WAV for speaker diarization...")
                # Create a temporary WAV file
                fd, temp_wav_path = tempfile.mkstemp(suffix='.wav')
                os.close(fd)
                
                # Convert to mono 16kHz WAV using ffmpeg
                command = [
                    'ffmpeg', '-i', audio_path,
                    '-vn', '-ac', '1', '-ar', '16000',
                    temp_wav_path, '-y'
                ]
                subprocess.run(command, check=True, capture_output=True)
                diarization_input_path = temp_wav_path
                print(f"Created temporary WAV file for diarization: {temp_wav_path}")

            # Perform diarization
            speaker_segments = diarizer.diarize(
                diarization_input_path,
                num_speakers=num_speakers,
                min_speakers=final_min_speakers if num_speakers is None else None,
                max_speakers=final_max_speakers if num_speakers is None else None
            )

            # Assign speakers to transcription segments
            segments_with_speakers = diarizer.assign_speakers_to_transcription(
                segments,
                speaker_segments
            )

            # Print statistics
            unique_speakers = set(seg.get('speaker', 'UNKNOWN') for seg in segments_with_speakers)
            speaker_counts = {}
            for seg in segments_with_speakers:
                spk = seg.get('speaker', 'UNKNOWN')
                speaker_counts[spk] = speaker_counts.get(spk, 0) + 1

            print(f"\n{'='*60}")
            print(f"✅ Speaker diarization complete!")
            print(f"Found {len(unique_speakers)} unique speakers:")
            for spk in sorted(unique_speakers):
                formatted_name = format_speaker_label(spk)
                print(f"  - {formatted_name}: {speaker_counts.get(spk, 0)} segments")
            print(f"{'='*60}\n")

            return segments_with_speakers

        finally:
            # Clean up temporary WAV file
            if temp_wav_path and os.path.exists(temp_wav_path):
                try:
                    os.unlink(temp_wav_path)
                    print(f"Cleaned up temporary diarization file: {temp_wav_path}")
                except Exception as e:
                    print(f"Warning: Failed to delete temp file {temp_wav_path}: {e}")

    except Exception as e:
        print(f"❌ Error in speaker diarization: {str(e)}")
        import traceback
        traceback.print_exc()

        # If diarization fails, add default speaker to all segments
        print("⚠️  Falling back to single speaker...")
        for seg in segments:
            seg['speaker'] = "SPEAKER_00"
        return segments

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
    """Convert seconds to HH:MM:SS.mmm format with millisecond precision"""
    # Use int() and modulo to handle any duration correctly
    total_secs = int(seconds)
    milliseconds = int((seconds - total_secs) * 1000)

    hours = total_secs // 3600
    minutes = (total_secs % 3600) // 60
    secs = total_secs % 60

    # Return format with milliseconds for better subtitle sync
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{milliseconds:03d}"

def translate_segments(segments: List[Dict], source_lang: str) -> List[Dict]:
    """Translate a batch of segments using local MarianMT model, preserving original text"""
    BATCH_SIZE = 10
    for i in range(0, len(segments), BATCH_SIZE):
        batch = segments[i:i + BATCH_SIZE]
        # Only translate segments with non-empty text
        batch_to_translate = [s for s in batch if s.get('text') and not s.get('text').isspace()]
        if not batch_to_translate:
            for segment in batch:
                segment['translation'] = '[No speech detected]'
            continue
        
        try:
            # Use local translation model instead of OpenAI
            tokenizer, model = get_marian_model(source_lang)
            
            # Translate each segment individually to preserve accuracy
            for segment in batch_to_translate:
                text = segment.get('text', '').strip()
                if not text:
                    segment['translation'] = '[No speech detected]'
                    continue
                
                # Translate using MarianMT
                inputs = tokenizer(text, return_tensors="pt", padding=True)
                translated = model.generate(**inputs)
                translation = tokenizer.decode(translated[0], skip_special_tokens=True)
                segment['translation'] = translation.strip()
            
            print(f"Successfully translated {len(batch_to_translate)} segments using local model")
        except Exception as e:
            print(f"Error in translation process: {str(e)}")
            # If translation fails, set placeholder translations
            for segment in batch_to_translate:
                segment['translation'] = f"[Translation pending for: {segment['text']}]"
    
    # Ensure all segments have a translation field
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

def extract_audio(video_path: str, chunk_duration: int = 600, overlap: int = 5) -> list:
    """
    Extract audio from video and split into chunks if needed, with overlap
    Returns list of paths to compressed audio chunks
    """
    audio_chunks = []
    with VideoFileClip(video_path) as video:
        duration = video.duration
        if duration <= chunk_duration:
            temp_audio_path = video_path + "_temp.wav"
            compressed_audio_path = video_path + ".wav"
            video.audio.write_audiofile(temp_audio_path, codec='pcm_s16le')
            compress_audio(temp_audio_path, compressed_audio_path)
            os.unlink(temp_audio_path)
            audio_chunks.append(compressed_audio_path)
        else:
            num_chunks = math.ceil(duration / chunk_duration)
            for i in range(num_chunks):
                # Add overlap: previous chunk ends at (i * chunk_duration), next chunk starts overlap seconds before
                start_time = max(0, i * chunk_duration - (overlap if i > 0 else 0))
                end_time = min((i + 1) * chunk_duration + (overlap if i < num_chunks - 1 else 0), duration)
                chunk = video.subclip(start_time, end_time)
                temp_chunk_path = f"{video_path}_chunk_{i}_temp.wav"
                compressed_chunk_path = f"{video_path}_chunk_{i}.wav"
                chunk.audio.write_audiofile(temp_chunk_path, codec='pcm_s16le')
                compress_audio(temp_chunk_path, compressed_chunk_path)
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
        # print(f"Attempting initial audio extraction with bitrate={initial_bitrate}, sample_rate={initial_sample_rate}")

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
    """Load MarianMT translation model for source_lang -> English.

    Args:
        source_lang: ISO language code (e.g., 'es', 'it', 'fr')

    Returns:
        Tuple of (tokenizer, model)

    Raises:
        Exception: If model doesn't exist for this language pair
    """
    model_name = f"Helsinki-NLP/opus-mt-{source_lang}-en"

    # Check if already loaded
    if model_name in marian_models:
        print(f"[INFO] Using cached translation model: {model_name}")
        return marian_models[model_name]

    # Try to load model with proper error handling
    try:
        print(f"[INFO] Loading translation model: {model_name}")
        tokenizer = MarianTokenizer.from_pretrained(model_name)
        model = MarianMTModel.from_pretrained(model_name)
        marian_models[model_name] = (tokenizer, model)
        print(f"[SUCCESS] Model loaded: {model_name}")
        return marian_models[model_name]

    except Exception as e:
        # Suggest alternatives if model doesn't exist
        available_alternatives = {
            'es': ['Helsinki-NLP/opus-mt-es-en'],
            'it': ['Helsinki-NLP/opus-mt-it-en'],
            'fr': ['Helsinki-NLP/opus-mt-fr-en'],
            'de': ['Helsinki-NLP/opus-mt-de-en'],
            'pt': ['Helsinki-NLP/opus-mt-pt-en'],
            'ru': ['Helsinki-NLP/opus-mt-ru-en'],
            'zh': ['Helsinki-NLP/opus-mt-zh-en'],
            'ja': ['Helsinki-NLP/opus-mt-ja-en'],
        }

        alt_models = available_alternatives.get(source_lang, [])
        error_msg = f"Translation model '{model_name}' not found. "

        if alt_models:
            error_msg += f"Alternatives: {', '.join(alt_models)}"
        else:
            error_msg += f"No translation model available for '{source_lang}' -> 'en'"

        print(f"[ERROR] {error_msg}")
        print(f"[ERROR] Original error: {str(e)}")
        raise Exception(error_msg)

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
                chunk_overlap = 5  # seconds, must match extract_audio
                print(f"Using moviepy to extract audio chunks ({chunk_duration_seconds}s duration, {chunk_overlap}s overlap)...")
                
                # Ensure extract_audio handles compression for each chunk
                # Assuming extract_audio compresses each chunk and returns paths
                audio_chunks = extract_audio(temp_input_path, chunk_duration=chunk_duration_seconds, overlap=chunk_overlap)

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
                    if chunk_size_mb > 25:
                        print(f"WARNING: Chunk {i+1} ({chunk_size_mb:.2f} MB) exceeds 25MB limit. Skipping this chunk.")
                        continue
                    with open(chunk_path, "rb") as chunk_file:
                        print(f"Calling Whisper API for chunk {i+1}...")
                        # Always use task="transcribe" to get original language text
                        segments, info = local_whisper_model.transcribe(
                            chunk_path,
                            task="transcribe",
                            language=language if language else None,
                            beam_size=1  # Faster processing
                        )
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
                        detected_language = chunk_response.language
                        print(f"Detected language for chunk {i+1}: {detected_language}")
                        if audio_language is None:
                            audio_language = detected_language
                            print(f"Overall audio language set to: {audio_language}")
                        full_text.append(chunk_response.text)
                        # --- Overlap segment discarding logic ---
                        chunk_offset = i * chunk_duration_seconds
                        chunk_length = chunk_duration_seconds + (chunk_overlap if i < total_chunks - 1 else 0) + (chunk_overlap if i > 0 else 0)
                        segments = chunk_response.segments
                        # Discard first segment if not the first chunk and it starts within overlap
                        if i > 0 and segments and segments[0]['start'] < chunk_overlap:
                            segments = segments[1:]
                        # Discard last segment if not the last chunk and it ends after chunk_length - overlap
                        if i < total_chunks - 1 and segments and segments[-1]['end'] > (chunk_length - chunk_overlap):
                            segments = segments[:-1]
                        # Adjust segment times by chunk offset (minus overlap for all but first chunk)
                        for segment in segments:
                            segment['start'] += chunk_offset - (chunk_overlap if i > 0 else 0)
                            segment['end'] += chunk_offset - (chunk_overlap if i > 0 else 0)
                        # Append to all_segments
                        for segment in segments:
                            segment_text = segment.get('text', '')
                            if segment_text and not segment_text.isspace():
                                all_segments.append(segment)
                            else:
                                all_segments.append({
                                    'start': segment['start'],
                                    'end': segment['end'],
                                    'text': '[No speech detected]',
                                    'translation': '[No speech detected]'
                                })
                
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

            # Add speaker diarization
            try:
                print("\n" + "="*60)
                print("Adding speaker labels to segments...")
                print("="*60)

                # Use the original input file for diarization (better quality)
                all_segments = add_speaker_labels(
                    audio_path=temp_input_path,
                    segments=all_segments,
                    num_speakers=None  # Auto-detect number of speakers
                )

                # Update response segments with speaker information
                response.segments = all_segments

                print("Speaker labeling complete!")
            except Exception as e:
                print(f"⚠️  Speaker diarization failed: {str(e)}")
                # Continue without speaker labels
                import traceback
                traceback.print_exc()
                # Ensure all segments have a speaker field
                for seg in all_segments:
                    if 'speaker' not in seg:
                        seg['speaker'] = "SPEAKER_00"

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
                    segment_speaker = segment.get('speaker', 'SPEAKER_00')  # Get speaker label
                    segment_dict = {
                        "id": segment_id,
                        "start": segment_start,
                        "end": segment_end,
                        "start_time": format_timestamp(segment_start),
                        "end_time": format_timestamp(segment_end),
                        "text": segment_text,
                        "translation": segment_translation,  # Always include translation field
                        "speaker": segment_speaker  # Add speaker field
                    }
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
async def get_subtitles(language: str, request: Request, video_hash: str = None) -> Response:
    """
    Get subtitles in SRT format. Language can be 'original' or 'english'.
    - 'original': Returns subtitles in the original language (stored in 'text' field)
    - 'english': Returns subtitles in English (stored in 'translation' field)
    """
    # Try to get transcription from video_hash parameter, app state, or last_transcription_data
    transcription = None

    if video_hash:
        # Get from database using video_hash
        transcription = get_transcription(video_hash)
        if not transcription:
            raise HTTPException(status_code=404, detail=f"Transcription not found for video_hash: {video_hash}")
    elif hasattr(request.app.state, 'last_transcription'):
        transcription = request.app.state.last_transcription
    else:
        # Fall back to global last_transcription_data
        global last_transcription_data
        if last_transcription_data:
            transcription = last_transcription_data
        else:
            raise HTTPException(status_code=404, detail="No transcription available. Please transcribe a video first.")

    
    if language not in ['original', 'english']:
        raise HTTPException(status_code=400, detail="Language must be 'original' or 'english'")
    
    # Verify we have segments
    if not transcription['transcription']['segments']:
        raise HTTPException(status_code=500, detail="No segments found in transcription")
    
    # Get source language and normalize it
    source_lang = transcription['transcription']['language'].lower()
    
    # Determine if we should use the translation field
    # For 'original' request: always use 'text' field (original language)
    # For 'english' request: use 'translation' field if source is not English, otherwise use 'text'
    use_translation = False
    
    if language == 'english':
        # For English subtitles
        if source_lang not in ['en', 'english']:
            # Source is not English, so we need to use translations
            use_translation = True
            
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
                            segment['translation'] = '[No speech detected]'
                            continue
                        
                        # Translate using MarianMT
                        inputs = tokenizer(text, return_tensors="pt", padding=True)
                        translated = model.generate(**inputs)
                        translation = tokenizer.decode(translated[0], skip_special_tokens=True)
                        segment['translation'] = translation.strip()
                    
                    print("Successfully translated missing segments using local model")
                except Exception as e:
                    print(f"Error in translation process: {str(e)}")
                    # If translation fails, set placeholder translations
                    for segment in segments_to_translate:
                        segment['translation'] = f"[Translation pending for: {segment['text']}]"
        else:
            # Source is already English, use text field
            use_translation = False
    else:
        # For 'original' request: always use text field (original language)
        use_translation = False
        print(f"Generating subtitles in original language ({source_lang})")
    
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
        parts = time_str.split(':')
        if len(parts) == 3:
            h, m, s = parts
            return float(h) * 3600 + float(m) * 60 + float(s)
        elif len(parts) == 2:
            m, s = parts
            return float(m) * 60 + float(s)
        return 0.0
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
    """List all saved transcriptions with additional metadata"""
    try:
        conn = sqlite3.connect('transcriptions.db')
        cursor = conn.cursor()
        cursor.execute("SELECT video_hash, filename, created_at, file_path, transcription_data FROM transcriptions ORDER BY created_at DESC")
        
        transcriptions = []
        for row in cursor.fetchall():
            video_hash, filename, created_at, file_path, transcription_data_json = row
            
            thumbnail_url = None
            if transcription_data_json:
                try:
                    transcription_data = json.loads(transcription_data_json)
                    # Find a segment from the middle with a screenshot URL
                    segments = transcription_data.get("transcription", {}).get("segments", [])
                    segments_with_screenshots = [s for s in segments if s.get("screenshot_url")]
                    
                    if segments_with_screenshots:
                        # Get the middle segment's screenshot
                        middle_index = len(segments_with_screenshots) // 2
                        thumbnail_url = segments_with_screenshots[middle_index].get("screenshot_url")

                except (json.JSONDecodeError, KeyError):
                    pass  # Ignore if data is not valid JSON or keys are missing

            transcriptions.append({
                "video_hash": video_hash,
                "filename": filename,
                "created_at": created_at,
                "file_path": file_path,
                "thumbnail_url": thumbnail_url
            })
            
        conn.close()
        
        return {"transcriptions": transcriptions}
    except Exception as e:
        print(f"Error listing transcriptions: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to list transcriptions")

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
        else:
            # If English source, ensure all segments have a translation field (set to text for consistency)
            for seg in segments:
                if 'translation' not in seg or not seg.get('translation'):
                    seg['translation'] = seg.get('text', '')
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
       # print(f"Attempting to serve video with hash: {video_hash}")
        transcription = get_transcription(video_hash)
        
        if not transcription:
            print(f"Transcription not found for hash: {video_hash}")
            raise HTTPException(status_code=404, detail="Transcription not found")
            
        if 'file_path' not in transcription or not transcription['file_path']:
            print(f"No file_path in transcription with hash: {video_hash}")
            raise HTTPException(status_code=404, detail="Video file path not found in transcription data")
        
        file_path = transcription['file_path']
        # print(f"File path from transcription: {file_path}")
        
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
async def transcribe_local(
    file: UploadFile,
    request: Request,
    num_speakers: int = Form(None),
    min_speakers: int = Form(None),
    max_speakers: int = Form(None),
    language: str = Form(None),
    force_language: bool = Form(False)
) -> Dict:
    """Transcribe uploaded audio/video file locally using faster-whisper.

    Args:
        file: Audio/video file to transcribe
        num_speakers: Exact number of speakers (if known)
        min_speakers: Minimum number of speakers for diarization
        max_speakers: Maximum number of speakers for diarization
        language: Optional language code (e.g., 'es', 'it', 'en'). If provided,
                  Whisper will use this instead of auto-detection.
        force_language: If True, completely override Whisper's detection with provided language
    """
    global last_transcription_data

    print(f"[INFO] Using local faster-whisper. Params: num_speakers={num_speakers}, min={min_speakers}, max={max_speakers}, language={language}, force_language={force_language}")
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
            # Check if the cached transcription is valid (has segments)
            segments_count = len(existing_transcription.get('transcription', {}).get('segments', []))
            if segments_count == 0:
                print(f"⚠ WARNING: Found cached transcription with 0 segments. Deleting and re-transcribing...")
                # Delete the invalid cached transcription
                try:
                    conn = sqlite3.connect('transcriptions.db')
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM transcriptions WHERE video_hash = ?", (video_hash,))
                    conn.commit()
                    conn.close()
                    print(f"Deleted invalid cached transcription for {video_hash}")
                except Exception as e:
                    print(f"Error deleting invalid transcription: {str(e)}")
                # Continue with new transcription (don't return, fall through)
            else:
                print(f"Found existing transcription for {file.filename} with hash {video_hash} ({segments_count} segments)")
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
        duration = 0.0
        try:
            duration = get_audio_duration(temp_path)
            duration_str = str(timedelta(seconds=int(duration)))
        except Exception as e:
            print(f"Error getting duration: {e}")
            duration_str = "Unknown"

        # Intelligently determine max_speakers based on duration if not provided
        if max_speakers is None and num_speakers is None:
            if duration < 300: # Less than 5 minutes
                print(f"Short video detected ({duration}s). Setting max_speakers=5.")
                max_speakers = 5
            else:
                print(f"Long video detected ({duration}s). Setting max_speakers=20.")
                max_speakers = 20

        start_time = time.time()
        
        # Convert to WAV first to avoid 'av' decoding issues with MP4
        # Create a temporary WAV file
        wav_suffix = ".wav"
        temp_wav_path = None
        with tempfile.NamedTemporaryFile(suffix=wav_suffix, delete=False) as wav_tmp:
            temp_wav_path = wav_tmp.name
            
        print(f"Converting input to WAV: {temp_wav_path}")
        try:
            # Convert to mono 16kHz WAV using ffmpeg
            command = [
                'ffmpeg', '-i', temp_path,
                '-vn', '-ac', '1', '-ar', '16000',
                temp_wav_path, '-y'
            ]
            result = subprocess.run(command, check=True, capture_output=True)
            print("Conversion to WAV successful")
            transcribe_input = temp_wav_path
        except subprocess.CalledProcessError as e:
            print(f"FFmpeg conversion failed with exit code {e.returncode}")
            print(f"FFmpeg stderr: {e.stderr.decode()}")
            raise HTTPException(status_code=400, detail=f"Failed to process audio: {e.stderr.decode()}")
        except Exception as e:
            print(f"Unexpected error during audio conversion: {e}")
            raise HTTPException(status_code=500, detail=f"Audio conversion error: {str(e)}")

        # --- KEY: Transcribe to original language, then translate if needed ---
        # Build transcription parameters
        transcribe_params = {
            "task": "transcribe",
            "beam_size": 5,  # Improved: Increase from 1 to 5 for better accuracy
            "vad_filter": True,  # Add Voice Activity Detection for better timing
            "vad_parameters": dict(
                min_silence_duration_ms=500,
                threshold=0.5
            )
        }

        # Add language parameter if provided
        if language:
            transcribe_params["language"] = language
            print(f"[INFO] Using specified language: {language}")

        segments, info = local_whisper_model.transcribe(
            transcribe_input,
            **transcribe_params
        )
        processing_time = time.time() - start_time

        # Detect language from transcription
        detected_language = info.language
        print(f"[INFO] Whisper detected language: {detected_language}")

        # Validate and potentially override detected language
        if language and not force_language:
            if detected_language != language:
                print(f"[WARNING] Language mismatch! Specified: {language}, Detected: {detected_language}")
                print(f"[WARNING] Using specified language: {language}")
                detected_language = language
        elif force_language and language:
            print(f"[INFO] Force override - using: {language}")
            detected_language = language
        
        # Format segments to match expected structure and preserve original language
        # IMPORTANT: Convert generator to list first, as generators can only be consumed once
        segments_list = list(segments)
        print(f"Total segments from Whisper: {len(segments_list)}")
        
        formatted_segments = []
        for i, seg in enumerate(segments_list):
            formatted_segments.append({
                "id": str(uuid.uuid4()),
                "start": seg.start,
                "end": seg.end,
                "start_time": format_timestamp(seg.start),
                "end_time": format_timestamp(seg.end),
                "text": seg.text,    # Original language text
                "translation": None,  # Will be populated by translate_segments if needed
            })
        
        print(f"Formatted {len(formatted_segments)} segments")

        # Language code normalization map
        language_code_map = {
            'spanish': 'es', 'español': 'es', 'es': 'es',
            'italian': 'it', 'italiano': 'it', 'it': 'it',
            'french': 'fr', 'français': 'fr', 'fr': 'fr',
            'german': 'de', 'deutsch': 'de', 'de': 'de',
            'portuguese': 'pt', 'português': 'pt', 'pt': 'pt',
            'russian': 'ru', 'русский': 'ru', 'ru': 'ru',
            'chinese': 'zh', 'zh': 'zh',
            'japanese': 'ja', 'ja': 'ja',
            'korean': 'ko', 'ko': 'ko',
            'english': 'en', 'en': 'en'
        }

        # Normalize language code
        normalized_lang = language_code_map.get(detected_language.lower(), detected_language.lower())
        print(f"[INFO] Normalized language code: '{detected_language}' -> '{normalized_lang}'")

        # Translate if source language is not English
        should_translate = normalized_lang not in ['en', 'english']

        if should_translate:
            print(f"[INFO] Detected language: {normalized_lang}. Translating {len(formatted_segments)} segments to English...")

            try:
                # Check if MarianMT model exists for this language
                model_name = f"Helsinki-NLP/opus-mt-{normalized_lang}-en"
                print(f"[INFO] Using translation model: {model_name}")

                formatted_segments = translate_segments(formatted_segments, normalized_lang)

                # Validate translations were actually generated
                translated_count = sum(1 for s in formatted_segments if s.get('translation'))
                if translated_count == 0:
                    raise Exception(f"Translation generated 0 translations for {len(formatted_segments)} segments!")

                print(f"[SUCCESS] Translation completed: {translated_count}/{len(formatted_segments)} segments translated")

            except Exception as e:
                error_msg = f"Translation failed: {str(e)}"
                print(f"[ERROR] {error_msg}")
                import traceback
                traceback.print_exc()

                # Store error in segments for user visibility
                for segment in formatted_segments:
                    segment['translation'] = f"[Translation Error: {normalized_lang}->en model not available]"
                    segment['translation_error'] = str(e)
        else:
            print("[INFO] Language is English. No translation needed.")
            # Populate translation field with same text for consistency
            for segment in formatted_segments:
                segment['translation'] = segment['text']

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

        # Add speaker diarization
        try:
            print("\nAdding speaker labels...")
            formatted_segments = add_speaker_labels(
                audio_path=temp_path,
                segments=formatted_segments,
                num_speakers=num_speakers,
                min_speakers=min_speakers,
                max_speakers=max_speakers
            )
            print("Speaker labeling complete")
        except Exception as e:
            print(f"⚠️  Speaker diarization failed: {str(e)}")
            # Continue without speaker labels - ensure all segments have speaker field
            for seg in formatted_segments:
                if 'speaker' not in seg:
                    seg['speaker'] = "SPEAKER_00"

        # Calculate translation statistics for user feedback
        translation_stats = {
            'total_segments': len(formatted_segments),
            'segments_translated': sum(1 for s in formatted_segments if s.get('translation') and not s.get('translation_error')),
            'translation_errors': sum(1 for s in formatted_segments if s.get('translation_error')),
            'detected_language': detected_language,
            'normalized_language': normalized_lang,
            'translation_attempted': should_translate
        }
        print(f"[STATS] Translation: {translation_stats['segments_translated']}/{translation_stats['total_segments']} successful")

        result = {
            "filename": file.filename,
            "video_hash": video_hash,
            "transcription": {
                "text": "".join([seg.text for seg in segments_list]),
                "language": info.language,
                "duration": duration_str,
                "segments": formatted_segments,
                "processing_time": format_eta(int(processing_time))
            },
            "translation_stats": translation_stats
        }

        # Store the transcription data
        store_transcription(video_hash, file.filename, result, permanent_file_path)
        
        # Store as last transcription in both global variable and request state
        last_transcription_data = result
        request.app.state.last_transcription = result
        
        # Add video URL to the result
        result["video_url"] = f"/video/{video_hash}"

        # Clean up temporary files
        try:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            if temp_wav_path and os.path.exists(temp_wav_path):
                os.unlink(temp_wav_path)
        except Exception as e:
            print(f"Error cleaning up temp file: {e}")

        return result
    except Exception as e:
        print(f"Error in local transcription: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/transcribe_local_stream/")
async def transcribe_local_stream(
    file: UploadFile,
    request: Request,
    num_speakers: int = Form(None),
    min_speakers: int = Form(None),
    max_speakers: int = Form(None),
    language: str = Form(None),
    force_language: bool = Form(False)
):
    """Transcribe with real-time progress updates via Server-Sent Events.

    Args:
        language: Optional language code (e.g., 'es', 'it', 'en')
        force_language: If True, override Whisper's detection with provided language
    """

    async def generate_progress():
        global last_transcription_data

        try:
            # Progress helper
            def emit(stage: str, progress: int, message: str = ""):
                return f"data: {json.dumps({'stage': stage, 'progress': progress, 'message': message})}\n\n"

            yield emit("uploading", 10, "Receiving file...")

            # Save uploaded file
            suffix = Path(file.filename).suffix
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                content = await file.read()
                tmp.write(content)
                temp_path = tmp.name

            yield emit("uploading", 20, "File uploaded successfully")

            # Generate hash and check cache
            video_hash = generate_file_hash(temp_path)
            existing_transcription = get_transcription(video_hash)

            if existing_transcription:
                segments_count = len(existing_transcription.get('transcription', {}).get('segments', []))
                if segments_count > 0:
                    print(f"Found cached transcription with {segments_count} segments")
                    yield emit("complete", 100, "Loaded from cache")
                    yield f"data: {json.dumps({'stage': 'complete', 'progress': 100, 'result': existing_transcription})}\n\n"
                    return

            # Save permanent copy
            permanent_storage_dir = os.path.join("static", "videos")
            os.makedirs(permanent_storage_dir, exist_ok=True)
            permanent_file_path = os.path.join(permanent_storage_dir, f"{video_hash}{suffix}")
            if not os.path.exists(permanent_file_path):
                shutil.copy2(temp_path, permanent_file_path)

            # Get duration
            duration = 0.0
            try:
                duration = get_audio_duration(temp_path)
                duration_str = str(timedelta(seconds=int(duration)))
            except Exception as e:
                duration_str = "Unknown"

            # Determine max_speakers
            computed_max_speakers = max_speakers
            if computed_max_speakers is None and num_speakers is None:
                computed_max_speakers = 5 if duration < 300 else 20

            yield emit("extracting", 30, "Converting audio to WAV format...")

            # Convert to WAV
            wav_suffix = ".wav"
            temp_wav_path = None
            with tempfile.NamedTemporaryFile(suffix=wav_suffix, delete=False) as wav_tmp:
                temp_wav_path = wav_tmp.name

            command = [
                'ffmpeg', '-i', temp_path,
                '-vn', '-ac', '1', '-ar', '16000',
                temp_wav_path, '-y'
            ]
            subprocess.run(command, check=True, capture_output=True)

            yield emit("transcribing", 45, "Starting AI transcription...")

            start_time = time.time()

            # Build transcription parameters
            transcribe_params = {
                "task": "transcribe",
                "beam_size": 5,  # Better accuracy
                "vad_filter": True,
                "vad_parameters": dict(
                    min_silence_duration_ms=500,
                    threshold=0.5
                )
            }

            # Add language parameter if provided
            if language:
                transcribe_params["language"] = language
                print(f"[INFO] Stream: Using specified language: {language}")

            segments, info = local_whisper_model.transcribe(
                temp_wav_path,
                **transcribe_params
            )

            yield emit("transcribing", 60, "Processing transcription segments...")

            segments_list = list(segments)
            detected_language = info.language
            print(f"[INFO] Stream: Whisper detected language: {detected_language}")

            # Validate and potentially override detected language
            if language and not force_language:
                if detected_language != language:
                    print(f"[WARNING] Stream: Language mismatch! Specified: {language}, Detected: {detected_language}")
                    detected_language = language
            elif force_language and language:
                print(f"[INFO] Stream: Force override - using: {language}")
                detected_language = language

            formatted_segments = []
            total_segments = len(segments_list)
            for i, seg in enumerate(segments_list):
                formatted_segments.append({
                    "id": str(uuid.uuid4()),
                    "start": seg.start,
                    "end": seg.end,
                    "start_time": format_timestamp(seg.start),
                    "end_time": format_timestamp(seg.end),
                    "text": seg.text,
                    "translation": None,
                })

                # Emit progress every 10 segments
                if i % 10 == 0:
                    segment_progress = 60 + int((i / total_segments) * 10)
                    yield emit("transcribing", segment_progress, f"Processed {i}/{total_segments} segments...")

            processing_time = time.time() - start_time

            yield emit("transcribing", 70, "Translating if needed...")

            # Language code normalization
            language_code_map = {
                'spanish': 'es', 'español': 'es', 'es': 'es',
                'italian': 'it', 'italiano': 'it', 'it': 'it',
                'french': 'fr', 'français': 'fr', 'fr': 'fr',
                'german': 'de', 'deutsch': 'de', 'de': 'de',
                'portuguese': 'pt', 'português': 'pt', 'pt': 'pt',
                'russian': 'ru', 'русский': 'ru', 'ru': 'ru',
                'chinese': 'zh', 'zh': 'zh',
                'japanese': 'ja', 'ja': 'ja',
                'korean': 'ko', 'ko': 'ko',
                'english': 'en', 'en': 'en'
            }

            normalized_lang = language_code_map.get(detected_language.lower(), detected_language.lower())
            print(f"[INFO] Stream: Normalized language: '{detected_language}' -> '{normalized_lang}'")
            should_translate = normalized_lang not in ['en', 'english']

            # Translate if not English
            if should_translate:
                try:
                    formatted_segments = translate_segments(formatted_segments, normalized_lang)
                    translated_count = sum(1 for s in formatted_segments if s.get('translation'))
                    print(f"[SUCCESS] Stream: Translated {translated_count}/{len(formatted_segments)} segments")
                except Exception as e:
                    print(f"[ERROR] Stream: Translation failed: {str(e)}")
                    for segment in formatted_segments:
                        segment['translation'] = f"[Translation Error: {normalized_lang}->en]"
                        segment['translation_error'] = str(e)
            else:
                print("[INFO] Stream: Language is English, no translation needed")
                for segment in formatted_segments:
                    segment['translation'] = segment['text']

            yield emit("extracting", 75, "Extracting video screenshots...")

            # Extract screenshots
            screenshots_dir = os.path.join("static", "screenshots")
            os.makedirs(screenshots_dir, exist_ok=True)
            screenshot_count = 0

            if suffix.lower() in {'.mp4', '.mpeg', '.webm', '.mov'}:
                for idx, segment in enumerate(formatted_segments):
                    screenshot_filename = f"{video_hash}_{segment['start']:.2f}.jpg"
                    screenshot_path = os.path.join(screenshots_dir, screenshot_filename)

                    success = extract_screenshot(temp_path, segment['start'], screenshot_path)
                    if success and os.path.exists(screenshot_path):
                        segment["screenshot_url"] = f"/static/screenshots/{screenshot_filename}"
                        screenshot_count += 1
                    else:
                        segment["screenshot_url"] = None

                    # Progress update every 5 screenshots
                    if idx % 5 == 0:
                        screenshot_progress = 75 + int((idx / len(formatted_segments)) * 10)
                        yield emit("extracting", screenshot_progress, f"Screenshots: {idx}/{len(formatted_segments)}")

            yield emit("transcribing", 85, "Identifying speakers...")

            # Speaker diarization
            try:
                formatted_segments = add_speaker_labels(
                    audio_path=temp_path,
                    segments=formatted_segments,
                    num_speakers=num_speakers,
                    min_speakers=min_speakers,
                    max_speakers=computed_max_speakers
                )
            except Exception as e:
                print(f"Speaker diarization failed: {str(e)}")
                for seg in formatted_segments:
                    if 'speaker' not in seg:
                        seg['speaker'] = "SPEAKER_00"

            yield emit("complete", 95, "Finalizing transcription...")

            # Build result
            result = {
                "filename": file.filename,
                "video_hash": video_hash,
                "transcription": {
                    "text": "".join([seg.text for seg in segments_list]),
                    "language": info.language,
                    "duration": duration_str,
                    "segments": formatted_segments,
                    "processing_time": format_eta(int(processing_time))
                }
            }

            # Store transcription
            store_transcription(video_hash, file.filename, result, permanent_file_path)
            last_transcription_data = result
            request.app.state.last_transcription = result
            result["video_url"] = f"/video/{video_hash}"

            # Clean up
            try:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                if temp_wav_path and os.path.exists(temp_wav_path):
                    os.unlink(temp_wav_path)
            except Exception as e:
                print(f"Error cleaning up: {e}")

            # Send final result
            yield emit("complete", 100, "Transcription complete!")
            yield f"data: {json.dumps({'stage': 'complete', 'progress': 100, 'result': result})}\n\n"

        except Exception as e:
            print(f"Error in streaming transcription: {e}")
            import traceback
            traceback.print_exc()
            yield f"data: {json.dumps({'stage': 'error', 'progress': 0, 'error': str(e)})}\n\n"

    return StreamingResponse(generate_progress(), media_type="text/event-stream")

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

@app.post("/transcription/{video_hash}/speaker")
async def update_speaker_name(video_hash: str, request: Request):
    """Update a speaker's name in a transcription"""
    try:
        body = await request.json()
        original_speaker = body.get("original_speaker")
        new_speaker_name = body.get("new_speaker_name")
        
        if not original_speaker or not new_speaker_name:
            raise HTTPException(status_code=400, detail="Missing original_speaker or new_speaker_name")
            
        # Get existing transcription
        transcription_data = get_transcription(video_hash)
        if not transcription_data:
            raise HTTPException(status_code=404, detail="Transcription not found")
            
        # Update segments
        updated_count = 0
        segments = transcription_data.get("transcription", {}).get("segments", [])
        
        for segment in segments:
            current_speaker = segment.get("speaker")
            # Match strictly against the internal label (e.g. SPEAKER_00) or previously renamed name
            if current_speaker == original_speaker:
                segment["speaker"] = new_speaker_name
                updated_count += 1
                
        if updated_count == 0:
            return {
                "success": False, 
                "message": f"No segments found for speaker '{original_speaker}'",
                "updated_count": 0
            }
            
        # Save back to database
        filename = transcription_data.get("filename", "unknown")
        file_path = transcription_data.get("file_path")
        
        success = store_transcription(video_hash, filename, transcription_data, file_path)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to save updates to database")
            
        # Update global cache if it matches
        global last_transcription_data
        if last_transcription_data and last_transcription_data.get("video_hash") == video_hash:
            last_transcription_data = transcription_data
            request.app.state.last_transcription = transcription_data
            
        return {
            "success": True,
            "message": f"Updated {updated_count} segments from '{original_speaker}' to '{new_speaker_name}'",
            "updated_count": updated_count,
            "video_hash": video_hash
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error updating speaker name: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# LLM Chat Endpoints
# ============================================================================

@app.post("/api/index_video/")
async def index_video_for_chat(request: Request, video_hash: str = None) -> Dict:
    """
    Index a video's transcription for chat/Q&A

    Args:
        video_hash: Optional video hash. If not provided, uses last transcription
    """
    if not LLM_AVAILABLE:
        raise HTTPException(status_code=503, detail="LLM features not available. Install required dependencies.")

    try:
        # Get transcription data
        if video_hash:
            transcription = get_transcription(video_hash)
            if not transcription:
                raise HTTPException(status_code=404, detail="Transcription not found")
        else:
            # Use last transcription
            global last_transcription_data
            if not last_transcription_data:
                raise HTTPException(status_code=404, detail="No transcription available")
            transcription = last_transcription_data
            video_hash = transcription.get('video_hash')

        # Get segments
        segments = transcription.get('transcription', {}).get('segments', [])
        if not segments:
            raise HTTPException(status_code=400, detail="No segments found in transcription")

        # Index in vector database
        print(f"Indexing video {video_hash} with {len(segments)} segments...")
        num_chunks = vector_store.index_transcription(video_hash, segments)

        return {
            "success": True,
            "video_hash": video_hash,
            "segments_count": len(segments),
            "chunks_indexed": num_chunks,
            "message": f"Successfully indexed {num_chunks} chunks from {len(segments)} segments"
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error indexing video: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to index video: {str(e)}")


@app.post("/api/chat/")
async def chat_with_video(request: Request) -> Dict:
    """
    Chat with a video using RAG (Retrieval-Augmented Generation)

    Request body:
        {
            "question": "What happens in this video?",
            "video_hash": "abc123",  # optional, uses last transcription if not provided
            "provider": "ollama",     # optional: ollama, groq, openai, anthropic
            "n_results": 5            # optional: number of context chunks to retrieve
        }
    """
    if not LLM_AVAILABLE:
        raise HTTPException(status_code=503, detail="LLM features not available")

    try:
        body = await request.json()
        question = body.get('question')
        video_hash = body.get('video_hash')
        provider_name = body.get('provider')
        n_results = body.get('n_results', 8)  # Increased from 5 to 8 for more context

        if not question:
            raise HTTPException(status_code=400, detail="Question is required")

        # Get video_hash from last transcription if not provided
        if not video_hash:
            global last_transcription_data
            if not last_transcription_data:
                raise HTTPException(status_code=404, detail="No video available for chat")
            video_hash = last_transcription_data.get('video_hash')

        # Check if video is indexed
        if not vector_store.collection_exists(video_hash):
            # Auto-index if not already indexed
            transcription = get_transcription(video_hash)
            if transcription:
                segments = transcription.get('transcription', {}).get('segments', [])
                print(f"Auto-indexing video {video_hash}...")
                vector_store.index_transcription(video_hash, segments)
            else:
                raise HTTPException(
                    status_code=404,
                    detail="Video not indexed. Please index it first using /api/index_video/"
                )

        # Retrieve relevant context using vector search
        print(f"Searching for relevant context for question: {question}")
        search_results = vector_store.search(video_hash, question, n_results=n_results)

        if not search_results:
            return {
                "answer": "I couldn't find relevant information in the video to answer your question.",
                "sources": [],
                "provider": provider_name or "none"
            }

        # Build context from search results
        context_parts = []
        sources = []

        for i, result in enumerate(search_results):
            metadata = result['metadata']
            text = result['text']

            context_parts.append(
                f"[Timestamp: {metadata['start_time']} - {metadata['end_time']}] "
                f"[Speaker: {metadata['speaker']}]\n{text}"
            )

            sources.append({
                "start_time": metadata['start_time'],
                "end_time": metadata['end_time'],
                "start": metadata['start'],
                "end": metadata['end'],
                "speaker": metadata['speaker'],
                "text": text[:200] + "..." if len(text) > 200 else text
            })

        context = "\n\n".join(context_parts)

        # Build prompt for LLM
        system_message = """You are an expert AI assistant specialized in analyzing video content and transcripts.

Your role:
- Provide detailed, comprehensive answers based on the video transcript
- Always cite specific timestamps when referencing information (use format [HH:MM:SS])
- Identify speakers and their contributions clearly
- Connect related points across different parts of the video
- Offer insights and analysis, not just basic summaries
- Use markdown formatting for better readability (bold, bullet points, etc.)

Guidelines:
- Be thorough and detailed in your responses
- Include relevant quotes from speakers when appropriate
- Explain context, implications, and connections between ideas
- If asked to summarize, organize information logically with bullet points or sections
- Reference multiple sources/timestamps to support your answers
- If the context is insufficient, explain what information is missing"""

        user_message = f"""Based on the following transcript segments from the video, please answer the question comprehensively.

VIDEO TRANSCRIPT CONTEXT:
{context}

QUESTION: {question}

Please provide a detailed, well-structured answer that:
1. Directly addresses the question
2. Cites specific timestamps and speakers
3. Provides context and analysis
4. Uses markdown formatting for clarity
5. Connects related information from different parts of the video"""

        messages = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message}
        ]

        # Get LLM provider and generate response
        try:
            provider = llm_manager.get_provider(provider_name)
            answer = await provider.generate(messages, temperature=0.7, max_tokens=2000)
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"LLM generation failed: {str(e)}"
            )

        return {
            "answer": answer,
            "sources": sources,
            "provider": provider_name or llm_manager.default_provider,
            "video_hash": video_hash
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in chat: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Chat failed: {str(e)}")


@app.get("/api/llm/providers")
async def list_llm_providers() -> Dict:
    """List all available LLM providers and their status"""
    if not LLM_AVAILABLE:
        raise HTTPException(status_code=503, detail="LLM features not available")

    try:
        providers = llm_manager.list_available_providers()
        return {
            "providers": providers,
            "default": llm_manager.default_provider
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/llm/test")
async def test_llm_provider(request: Request) -> Dict:
    """
    Test an LLM provider

    Request body:
        {
            "provider": "ollama"  # optional, uses default if not provided
        }
    """
    if not LLM_AVAILABLE:
        raise HTTPException(status_code=503, detail="LLM features not available")

    try:
        body = await request.json()
        provider_name = body.get('provider')

        provider = llm_manager.get_provider(provider_name)

        # Test with a simple message
        messages = [
            {"role": "user", "content": "Hello! Please respond with 'OK' if you can read this."}
        ]

        response = await provider.generate(messages, temperature=0.5, max_tokens=50)

        return {
            "success": True,
            "provider": provider_name or llm_manager.default_provider,
            "response": response
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "provider": provider_name or llm_manager.default_provider
        }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 