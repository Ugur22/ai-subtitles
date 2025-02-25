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
    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",  # Much cheaper than GPT-4, still good for translation
            messages=[
                {"role": "system", "content": f"You are a professional translator from {source_lang} to English. Translate the following text accurately while maintaining the original meaning and tone. Only return the translation, nothing else."},
                {"role": "user", "content": text}
            ],
            temperature=0.3
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        raise Exception(f"Translation error: {str(e)}")

def translate_segments(client: OpenAI, segments: List[Dict], source_lang: str) -> List[Dict]:
    """Translate a batch of segments to reduce API calls"""
    # Process segments in larger batches to reduce API calls
    BATCH_SIZE = 50  # Increased from 10 to 50
    
    # Combine all segments first to estimate total length
    all_text = " ".join(segment['text'] for segment in segments)
    total_chars = len(all_text)
    
    # If total text is small enough, translate everything at once
    if total_chars < 15000:  # GPT-3.5 can handle about 15k characters comfortably
        try:
            combined_text = "\n---\n".join([f"[{i}] {segment['text']}" for i, segment in enumerate(segments)])
            translated_text = translate_text(client, combined_text, source_lang)
            
            # Split translations and map back to segments
            translations = {}
            current_index = None
            current_text = []
            
            for line in translated_text.split('\n'):
                line = line.strip()
                if not line:
                    continue
                    
                if line.startswith('[') and ']' in line:
                    if current_index is not None:
                        translations[current_index] = ' '.join(current_text).strip()
                    try:
                        current_index = int(line[line.find('[')+1:line.find(']')])
                        current_text = [line[line.find(']')+1:].strip()]
                    except ValueError:
                        current_text.append(line)
                else:
                    if current_index is not None:
                        current_text.append(line)
            
            if current_index is not None:
                translations[current_index] = ' '.join(current_text).strip()
            
            for i, segment in enumerate(segments):
                segment['translation'] = translations.get(i, "Translation error occurred")
            
            return segments
            
        except Exception as e:
            print(f"Batch translation error: {str(e)}")
    
    # If text is too long, process in batches
    for i in range(0, len(segments), BATCH_SIZE):
        batch = segments[i:i + BATCH_SIZE]
        combined_text = "\n---\n".join([f"[{j}] {segment['text']}" for j, segment in enumerate(batch)])
        
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
                    
                if line.startswith('[') and ']' in line:
                    if current_index is not None:
                        translations[current_index] = ' '.join(current_text).strip()
                    try:
                        current_index = int(line[line.find('[')+1:line.find(']')])
                        current_text = [line[line.find(']')+1:].strip()]
                    except ValueError:
                        current_text.append(line)
                else:
                    if current_index is not None:
                        current_text.append(line)
            
            if current_index is not None:
                translations[current_index] = ' '.join(current_text).strip()
            
            for j, segment in enumerate(batch):
                segment['translation'] = translations.get(j, "Translation error occurred")
                
        except Exception as e:
            for segment in batch:
                segment['translation'] = f"Translation failed: {str(e)}"
    
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

# Initialize FastAPI app
app = FastAPI(title="Video Transcription API")

# Configure CORS with more specific settings
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
    expose_headers=["Content-Disposition"],  # Important for file downloads
    max_age=600,  # Cache preflight requests for 10 minutes
)

# Configure OpenAI with a custom httpx client
http_client = httpx.Client()
client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    http_client=http_client
)

@app.post("/transcribe/")
async def transcribe_video(file: UploadFile, request: Request) -> Dict:
    """
    Endpoint to transcribe video files and return text with timestamps.
    """
    # Check if file is provided
    if not file:
        raise HTTPException(status_code=400, detail="No file provided")

    # Check file extension
    allowed_extensions = {'.mp4', '.mpeg', '.mpga', '.m4a', '.wav', '.webm', '.mp3'}
    file_extension = Path(file.filename).suffix.lower()
    if file_extension not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format. Supported formats: {', '.join(allowed_extensions)}"
        )

    try:
        print(f"\nProcessing video: {file.filename}")
        start_time = time.time()
        
        # Create a temporary file to store the uploaded video
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as temp_file:
            # Write the uploaded file content to temporary file in chunks
            total_size = 0
            chunk_size = 1024 * 1024  # 1MB chunks
            print("\nUploading video...")
            with tqdm(total=None, unit='MB', unit_scale=True, ncols=80) as pbar:
                while chunk := await file.read(chunk_size):
                    temp_file.write(chunk)
                    total_size += len(chunk)
                    pbar.update(len(chunk) / (1024 * 1024))
            temp_file.flush()
            
            # Check file size - if it's slightly over 25MB, we'll use more aggressive compression
            file_size_mb = total_size / (1024 * 1024)
            print(f"\nFile size: {file_size_mb:.2f}MB")
            use_aggressive_compression = file_size_mb > 25 and file_size_mb < 30

        try:
            # Extract and compress audio from video
            print("\nExtracting audio...")
            if use_aggressive_compression:
                print("File slightly exceeds 25MB limit. Using aggressive compression...")
                # Override compress_audio function for this file with more aggressive settings
                def compress_audio_aggressive(input_path: str, output_path: str) -> str:
                    try:
                        # Check if ffmpeg is available
                        if not shutil.which('ffmpeg'):
                            raise Exception("ffmpeg is not installed. Please install ffmpeg first.")

                        # More aggressive compression settings
                        command = [
                            'ffmpeg', '-i', input_path,
                            '-ac', '1',  # Convert to mono
                            '-ar', '8000',  # Lower sample rate to 8kHz
                            '-b:a', '16k',  # Lower bitrate to 16k
                            output_path,
                            '-y'  # Overwrite output file if it exists
                        ]
                        
                        subprocess.run(command, check=True, capture_output=True)
                        return output_path
                    except subprocess.CalledProcessError as e:
                        raise Exception(f"Error compressing audio: {e.stderr.decode()}")
                
                # Temporarily replace the compression function
                original_compress_audio = compress_audio
                globals()['compress_audio'] = compress_audio_aggressive
                
                # Extract audio with the more aggressive compression
                audio_chunks = extract_audio(temp_file.name)
                
                # Restore original compression function
                globals()['compress_audio'] = original_compress_audio
            else:
                # Use standard compression
                audio_chunks = extract_audio(temp_file.name)
            
            # Process each audio chunk
            all_segments = []
            total_duration = 0
            detected_language = None
            
            print("\nTranscribing audio...")
            for chunk_idx, audio_path in enumerate(tqdm(audio_chunks, desc="Transcribing chunks", ncols=80)):
                # Calculate time offset for this chunk
                time_offset = chunk_idx * 600  # 600 seconds per chunk
                
                try:
                    # Print debug info about the audio file
                    audio_file_size = os.path.getsize(audio_path) / (1024 * 1024)
                    print(f"Audio chunk {chunk_idx} size: {audio_file_size:.2f}MB")
                    
                    # Transcribe the audio chunk
                    with open(audio_path, "rb") as audio_file:
                        try:
                            transcript = client.audio.transcriptions.create(
                                model="whisper-1",
                                file=audio_file,
                                response_format="verbose_json"
                            )
                        except Exception as e:
                            print(f"OpenAI API error: {str(e)}")
                            # If file is too large for OpenAI, try more aggressive compression
                            if "file too large" in str(e).lower():
                                print("File too large for OpenAI API, trying more aggressive compression...")
                                compressed_path = audio_path + ".compressed.wav"
                                try:
                                    # Ultra aggressive compression
                                    command = [
                                        'ffmpeg', '-i', audio_path,
                                        '-ac', '1',         # Convert to mono
                                        '-ar', '8000',      # Very low sample rate
                                        '-b:a', '12k',      # Very low bitrate
                                        '-acodec', 'libmp3lame',  # Use MP3 encoding which can be more compressed
                                        compressed_path,
                                        '-y'               # Overwrite output file if it exists
                                    ]
                                    subprocess.run(command, check=True, capture_output=True)
                                    
                                    # Check new file size
                                    new_size = os.path.getsize(compressed_path) / (1024 * 1024)
                                    print(f"Ultra-compressed size: {new_size:.2f}MB")
                                    
                                    # Try again with smaller file
                                    with open(compressed_path, "rb") as compressed_file:
                                        transcript = client.audio.transcriptions.create(
                                            model="whisper-1",
                                            file=compressed_file,
                                            response_format="verbose_json"
                                        )
                                        
                                    # Clean up temporary compressed file
                                    os.unlink(compressed_path)
                                except Exception as comp_error:
                                    print(f"Compression or retry failed: {str(comp_error)}")
                                    raise
                            else:
                                raise

                    # Convert transcript to dict if it's not already
                    if not isinstance(transcript, dict):
                        transcript = transcript.model_dump()

                    # Store detected language from first chunk
                    if chunk_idx == 0:
                        detected_language = transcript['language']
                        print(f"\nDetected language: {detected_language}")

                    # Adjust timestamps and add segments
                    for segment in transcript['segments']:
                        segment['start'] += time_offset
                        segment['end'] += time_offset
                        all_segments.append(segment)

                    # Update total duration
                    total_duration = max(total_duration, time_offset + transcript['duration'])

                    # Clean up audio chunk file
                    os.unlink(audio_path)

                except Exception as e:
                    # Clean up temporary files in case of error
                    if 'temp_file' in locals():
                        try:
                            os.unlink(temp_file.name)
                        except FileNotFoundError:
                            pass
                    # Clean up any remaining audio chunks
                    if 'audio_chunks' in locals():
                        for chunk_path in audio_chunks:
                            try:
                                os.unlink(chunk_path)
                            except FileNotFoundError:
                                pass
                    raise HTTPException(status_code=500, detail=str(e))

            # Clean up the original video file
            os.unlink(temp_file.name)

            # Translate segments in batches
            print("\nTranslating segments...")
            
            # Skip translation if content is already in English
            if detected_language.lower() in ["en", "english"]:
                print("Content already in English, skipping translation...")
                for segment in all_segments:
                    segment['translation'] = segment['text']  # Use original text as translation
                translated_segments = all_segments
            else:
                translated_segments = translate_segments(client, all_segments, detected_language)

            # Format all segments with proper timestamps
            print("\nFormatting results...")
            formatted_segments = []
            for segment in tqdm(translated_segments, desc="Formatting segments", ncols=80):
                formatted_segment = {
                    "id": segment['id'],
                    "start_time": format_timestamp(segment['start']),
                    "end_time": format_timestamp(segment['end']),
                    "text": segment['text'].strip(),
                    "translation": segment['translation']
                }
                formatted_segments.append(formatted_segment)

            # Sort segments by start time
            formatted_segments.sort(key=lambda x: x['start_time'])

            # Calculate total processing time
            total_time = time.time() - start_time
            print(f"\nTotal processing time: {format_eta(int(total_time))}")

            result = {
                "filename": file.filename,
                "transcription": {
                    "text": " ".join(segment['text'] for segment in all_segments),
                    "translated_text": " ".join(segment['translation'] for segment in translated_segments),
                    "language": detected_language,
                    "duration": format_timestamp(total_duration),
                    "segments": formatted_segments,
                    "processing_time": format_eta(int(total_time))
                }
            }
            
            # Store the result for subtitle generation
            request.app.state.last_transcription = result
            
            return result

        except HTTPException:
            # Re-raise HTTP exceptions
            raise
        except Exception as e:
            # Clean up temporary files in case of error
            if 'temp_file' in locals():
                try:
                    os.unlink(temp_file.name)
                except FileNotFoundError:
                    pass
            # Clean up any remaining audio chunks
            if 'audio_chunks' in locals():
                for chunk_path in audio_chunks:
                    try:
                        os.unlink(chunk_path)
                    except FileNotFoundError:
                        pass
            
            # Log the detailed error with traceback
            import traceback
            error_details = f"Error: {str(e)}\n{traceback.format_exc()}"
            print(error_details)
            
            raise HTTPException(status_code=500, detail=f"Transcription failed: {str(e)}")

    except Exception as e:
        # Clean up temporary files in case of error
        if 'temp_file' in locals():
            try:
                os.unlink(temp_file.name)
            except FileNotFoundError:
                pass
        # Clean up any remaining audio chunks
        if 'audio_chunks' in locals():
            for chunk_path in audio_chunks:
                try:
                    os.unlink(chunk_path)
                except FileNotFoundError:
                    pass
        
        # Log the detailed error with traceback
        import traceback
        error_details = f"Error: {str(e)}\n{traceback.format_exc()}"
        print(error_details)
        
        raise HTTPException(status_code=500, detail=f"Transcription failed: {str(e)}")

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
    
    use_translation = (language == 'english')
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
            if (topic_lower in segment['text'].lower() or 
                topic_lower in segment['translation'].lower()):
                
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 