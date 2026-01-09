"""
Chat and RAG (Retrieval-Augmented Generation) endpoints
"""
import asyncio
from typing import Dict, Optional, List, Callable, Any
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, HTTPException, Request

# Executor for CPU/GPU-bound operations (CLIP, embeddings, ChromaDB)
# This prevents blocking the event loop during visual search and chat operations
_chat_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="chat_embed")


async def _run_in_executor(func: Callable, *args, **kwargs) -> Any:
    """Run blocking function in executor to avoid blocking event loop."""
    loop = asyncio.get_event_loop()
    if kwargs:
        return await loop.run_in_executor(_chat_executor, lambda: func(*args, **kwargs))
    return await loop.run_in_executor(_chat_executor, func, *args)

from database import get_transcription
from dependencies import _last_transcription_data
from middleware.auth import require_auth


def get_transcription_from_any_source(video_hash: str) -> Optional[Dict]:
    """
    Get transcription from any available source:
    1. First check legacy database (SQLite/Firestore)
    2. If not found, check Supabase jobs table

    Args:
        video_hash: The video hash to look up

    Returns:
        Transcription data dict or None if not found
    """
    # Try legacy database first
    transcription = get_transcription(video_hash)
    if transcription:
        return transcription

    # Try Supabase jobs table
    try:
        from services.supabase_service import supabase
        client = supabase()

        # Look for completed job with this video_hash
        response = (
            client.table("jobs")
            .select("result_json, filename, gcs_path")
            .eq("video_hash", video_hash)
            .eq("status", "completed")
            .limit(1)
            .execute()
        )

        if response.data and len(response.data) > 0:
            job = response.data[0]
            result_json = job.get("result_json")

            if result_json:
                # The result_json from jobs already has the right structure
                # It contains: filename, gcs_path, video_hash, transcription (with segments)
                print(f"[Chat] Found transcription in Supabase job for video_hash={video_hash}")
                return result_json

    except Exception as e:
        print(f"[Chat] Error checking Supabase for transcription: {e}")

    return None


from models import (
    IndexVideoResponse,
    IndexImagesResponse,
    ChatRequest,
    ChatResponse,
    TestLLMRequest,
    TestLLMResponse,
    SearchImagesRequest,
    SearchImagesResponse,
    ImageSearchResult,
    ErrorResponse
)

# Import LLM and vector store modules
try:
    from llm_providers import llm_manager
    from vector_store import vector_store
    LLM_AVAILABLE = True
except ImportError as e:
    print(f"Warning: LLM features not available: {str(e)}")
    LLM_AVAILABLE = False

# Import Supabase image embedding service (new persistent storage)
try:
    from services.image_embedding_service import image_embedding_service
    SUPABASE_IMAGES_AVAILABLE = True
except Exception as e:
    print(f"Warning: Supabase image embeddings not available: {e}")
    SUPABASE_IMAGES_AVAILABLE = False

router = APIRouter(prefix="/api", tags=["Chat & RAG"])


def _use_supabase_for_images() -> bool:
    """
    Determine whether to use Supabase for image embeddings.
    Uses Supabase when:
    1. ENABLE_GCS_UPLOADS is true (production/Cloud Run)
    2. Supabase image service is available
    """
    from config import settings
    return SUPABASE_IMAGES_AVAILABLE and settings.ENABLE_GCS_UPLOADS


def _extract_speaker_from_query(query: str, video_hash: str) -> Optional[str]:
    """
    Extract speaker name from query by checking against enrolled speakers
    and segment speaker labels.

    Args:
        query: User's question/query
        video_hash: Video hash to get segments from

    Returns:
        Speaker name/label if found in query, None otherwise
    """
    speakers = _extract_all_speakers_from_query(query, video_hash)
    return speakers[0] if speakers else None


def _extract_all_speakers_from_query(query: str, video_hash: str) -> List[str]:
    """
    Extract ALL speaker names from query by checking against enrolled speakers
    and segment speaker labels.

    Args:
        query: User's question/query
        video_hash: Video hash to get segments from

    Returns:
        List of speaker names/labels found in query
    """
    if not query:
        return []

    query_lower = query.lower()
    found_speakers = []

    # First, check enrolled speakers (e.g., "Concetta", "John")
    try:
        from speaker_recognition import get_speaker_recognition_system
        sr_system = get_speaker_recognition_system()
        enrolled_speakers = sr_system.list_speakers()

        for speaker_name in enrolled_speakers:
            if speaker_name.lower() in query_lower:
                print(f"Found enrolled speaker in query: {speaker_name}")
                found_speakers.append(speaker_name)
    except Exception as e:
        print(f"Could not load speaker recognition system: {e}")

    # Also check for SPEAKER_XX labels in segments
    # This handles cases where segments use labels like "SPEAKER_19"
    try:
        transcription = get_transcription_from_any_source(video_hash)
        if transcription:
            segments = transcription.get('transcription', {}).get('segments', [])

            # Build a set of unique speaker labels
            speaker_labels = set()
            for segment in segments:
                speaker = segment.get('speaker')
                if speaker:
                    speaker_labels.add(speaker)

            # Check if any speaker label is mentioned in the query
            for speaker_label in speaker_labels:
                if speaker_label.lower() in query_lower and speaker_label not in found_speakers:
                    print(f"Found speaker label in query: {speaker_label}")
                    found_speakers.append(speaker_label)
    except Exception as e:
        print(f"Could not check segment speakers: {e}")

    return found_speakers


@router.post(
    "/index_video/",
    response_model=IndexVideoResponse,
    summary="Index video for chat",
    description="Index a video's transcription for chat/Q&A using vector search",
    responses={
        503: {"model": ErrorResponse, "description": "LLM features not available"},
        404: {"model": ErrorResponse, "description": "Transcription not found"}
    }
)
@require_auth
async def index_video_for_chat(request: Request, video_hash: str = None) -> IndexVideoResponse:
    """
    Index a video's transcription for chat/Q&A

    Args:
        video_hash: Optional video hash. If not provided, uses last transcription
    """
    if not LLM_AVAILABLE:
        raise HTTPException(status_code=503, detail="LLM features not available. Install required dependencies.")

    try:
        # Get transcription data from any available source (legacy DB or Supabase jobs)
        if video_hash:
            transcription = get_transcription_from_any_source(video_hash)
            if not transcription:
                raise HTTPException(status_code=404, detail="Transcription not found")
        else:
            # Use last transcription
            global _last_transcription_data
            if not _last_transcription_data:
                raise HTTPException(status_code=404, detail="No transcription available")
            transcription = _last_transcription_data
            video_hash = transcription.get('video_hash')

        # Get segments
        segments = transcription.get('transcription', {}).get('segments', [])
        if not segments:
            raise HTTPException(status_code=400, detail="No segments found in transcription")

        # Index in vector database (run in executor to avoid blocking)
        print(f"Indexing video {video_hash} with {len(segments)} segments...")
        num_chunks = await _run_in_executor(vector_store.index_transcription, video_hash, segments)

        return IndexVideoResponse(
            success=True,
            video_hash=video_hash,
            segments_count=len(segments),
            chunks_indexed=num_chunks,
            message=f"Successfully indexed {num_chunks} chunks from {len(segments)} segments"
        )
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error indexing video: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to index video: {str(e)}")


@router.post(
    "/chat/",
    response_model=ChatResponse,
    summary="Chat with video",
    description="Chat with a video using RAG (Retrieval-Augmented Generation)",
    responses={
        503: {"model": ErrorResponse, "description": "LLM features not available"},
        404: {"model": ErrorResponse, "description": "Video not found"},
        400: {"model": ErrorResponse, "description": "Invalid request"}
    }
)
@require_auth
async def chat_with_video(request: Request, chat_request: ChatRequest) -> Dict:
    """
    Chat with a video using RAG (Retrieval-Augmented Generation)
    """
    if not LLM_AVAILABLE:
        raise HTTPException(status_code=503, detail="LLM features not available")

    try:
        question = chat_request.question
        video_hash = chat_request.video_hash
        provider_name = chat_request.provider
        n_results = chat_request.n_results or 8
        include_visuals = chat_request.include_visuals or False
        n_images = chat_request.n_images or 6
        custom_instructions = chat_request.custom_instructions

        if not question:
            raise HTTPException(status_code=400, detail="Question is required")

        # Get video_hash from last transcription if not provided
        if not video_hash:
            global _last_transcription_data
            if not _last_transcription_data:
                raise HTTPException(status_code=404, detail="No video available for chat")
            video_hash = _last_transcription_data.get('video_hash')

        # Check if video is indexed
        if not vector_store.collection_exists(video_hash):
            # Auto-index if not already indexed
            transcription = get_transcription_from_any_source(video_hash)
            if transcription:
                segments = transcription.get('transcription', {}).get('segments', [])
                print(f"Auto-indexing video {video_hash}...")
                await _run_in_executor(vector_store.index_transcription, video_hash, segments)
            else:
                raise HTTPException(
                    status_code=404,
                    detail="Video not indexed. Please index it first using /api/index_video/"
                )

        # Retrieve relevant context using vector search (run in executor - embedding generation)
        print(f"Searching for relevant context for question: {question}")
        search_results = await _run_in_executor(vector_store.search, video_hash, question, n_results=n_results)

        if not search_results:
            return {
                "answer": "I couldn't find relevant information in the video to answer your question.",
                "sources": [],
                "provider_used": provider_name or "none",
                "video_hash": video_hash
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

        # Search for relevant images if include_visuals is True
        image_paths = []
        visual_context = ""
        visual_sources = []
        visual_query_used = None  # Track the transformed query for visual search

        if include_visuals:
            print(f"Visual analysis requested, searching for {n_images} relevant images...")

            # Determine which image service to use
            use_supabase = _use_supabase_for_images()
            if use_supabase:
                images_indexed = image_embedding_service.image_collection_exists(video_hash)
            else:
                images_indexed = vector_store.image_collection_exists(video_hash)

            # Check if images are indexed
            if images_indexed:
                try:
                    # Extract ALL speaker names from the query
                    speaker_names = _extract_all_speakers_from_query(question, video_hash)

                    # Create a visual-optimized query for CLIP
                    # CLIP doesn't know specific people by name, so we replace all speaker names
                    # and let CLIP focus on the visual concepts (e.g., "swimming", "talking")
                    visual_query = question
                    if speaker_names:
                        import re
                        # Replace all speaker names with "person" (or "people" if multiple speakers)
                        replacement = "person" if len(speaker_names) == 1 else "people"

                        for speaker_name in speaker_names:
                            visual_query = re.sub(
                                rf'\b{re.escape(speaker_name)}\b',
                                replacement,
                                visual_query,
                                flags=re.IGNORECASE
                            )

                        print(f"Visual search: transformed '{question}' -> '{visual_query}'")
                        visual_query_used = visual_query
                    else:
                        visual_query_used = question

                    # Search for relevant images using the visual-optimized query
                    # No speaker filter - CLIP searches by visual similarity, not speaker metadata
                    # Run in executor - CLIP encoding is CPU/GPU intensive
                    if use_supabase:
                        image_results = await _run_in_executor(
                            image_embedding_service.search_images,
                            video_hash,
                            visual_query,
                            n_results=n_images,
                            speaker_filter=None
                        )
                    else:
                        image_results = await _run_in_executor(
                            vector_store.search_images,
                            video_hash,
                            visual_query,
                            n_results=n_images,
                            speaker_filter=None  # Don't filter by speaker - let CLIP find visual matches
                        )

                    # Phase 1: Temporal Correlation Scoring
                    # Score visual results by temporal overlap with speaker segments
                    if speaker_names and image_results:
                        print(f"Applying temporal correlation scoring for speakers: {speaker_names}")

                        # Get speaker segments from transcript
                        transcription = get_transcription_from_any_source(video_hash)
                        if transcription:
                            segments = transcription.get('transcription', {}).get('segments', [])

                            # Build timeline for each speaker mentioned
                            speaker_timelines = {}
                            for name in speaker_names:
                                speaker_timelines[name] = [
                                    (seg['start'], seg['end'])
                                    for seg in segments
                                    if seg.get('speaker', '').lower() == name.lower()
                                ]
                                print(f"  Speaker '{name}': {len(speaker_timelines[name])} segments")

                            # Score each visual result by overlap with speaker timelines
                            for result in image_results:
                                img_start = result['metadata'].get('start', 0)
                                img_end = result['metadata'].get('end', 0)

                                overlap_score = 0
                                overlapping_speakers = []

                                for speaker, timeline in speaker_timelines.items():
                                    for seg_start, seg_end in timeline:
                                        # Check for temporal overlap
                                        if img_start <= seg_end and img_end >= seg_start:
                                            overlap_score += 1
                                            if speaker not in overlapping_speakers:
                                                overlapping_speakers.append(speaker)

                                result['overlap_score'] = overlap_score
                                result['likely_speakers'] = overlapping_speakers

                            # Sort by overlap score (highest first)
                            image_results.sort(key=lambda x: x.get('overlap_score', 0), reverse=True)

                            print(f"Scored {len(image_results)} visual results by speaker timeline overlap")
                            for i, result in enumerate(image_results[:3]):  # Log top 3
                                print(f"  Result {i+1}: overlap_score={result.get('overlap_score', 0)}, "
                                      f"speakers={result.get('likely_speakers', [])}")

                    if image_results:
                        print(f"Found {len(image_results)} relevant images")
                        image_paths = [result['screenshot_path'] for result in image_results]

                        # Build visual context description and sources
                        visual_parts = []
                        for i, img_result in enumerate(image_results):
                            metadata = img_result['metadata']
                            screenshot_path = img_result['screenshot_path']

                            # Convert local path to URL
                            # screenshot_path can be absolute like "/path/to/backend/static/screenshots/hash_123.45.jpg"
                            # or relative like "./static/screenshots/hash_123.45.jpg"
                            if 'static/screenshots/' in screenshot_path:
                                # Extract the filename from the path
                                filename = screenshot_path.split('static/screenshots/')[-1]
                                screenshot_url = f"/static/screenshots/{filename}"
                            else:
                                # Fallback: try the old approach
                                screenshot_url = screenshot_path.replace('./static/', '/static/')

                            visual_parts.append(
                                f"Screenshot {i+1} - Timestamp: {metadata['start']:.2f}s - {metadata['end']:.2f}s, "
                                f"Speaker: {metadata['speaker']}"
                            )

                            # Add to visual sources
                            visual_sources.append({
                                "start_time": f"{int(metadata['start'] // 3600):02d}:{int((metadata['start'] % 3600) // 60):02d}:{int(metadata['start'] % 60):02d}",
                                "end_time": f"{int(metadata['end'] // 3600):02d}:{int((metadata['end'] % 3600) // 60):02d}:{int(metadata['end'] % 60):02d}",
                                "start": metadata['start'],
                                "end": metadata['end'],
                                "speaker": metadata['speaker'],
                                "screenshot_url": screenshot_url,
                                "type": "visual",
                                "likely_speakers": img_result.get('likely_speakers', []),
                                "overlap_score": img_result.get('overlap_score', 0)
                            })

                        visual_context = "\n".join(visual_parts)
                        print(f"Visual context: {visual_context}")
                    else:
                        print("No relevant images found for the query")
                except Exception as e:
                    print(f"Warning: Failed to search images: {str(e)}")
                    # Continue without images
            else:
                print(f"Images not indexed for video {video_hash}. Continuing with text-only analysis.")

        # Search for relevant audio events if available
        audio_context = ""
        audio_sources = []

        if vector_store.audio_collection_exists(video_hash):
            try:
                # Run in executor - embedding generation is CPU intensive
                audio_results = await _run_in_executor(
                    vector_store.search_audio_events,
                    video_hash,
                    question,
                    n_results=5
                )

                if audio_results:
                    print(f"Found {len(audio_results)} relevant audio events")
                    audio_parts = []

                    for i, audio_result in enumerate(audio_results):
                        metadata = audio_result['metadata']
                        description = audio_result['description']

                        audio_parts.append(
                            f"Audio Event {i+1} - Timestamp: {metadata['start']:.2f}s - {metadata['end']:.2f}s, "
                            f"Events: {description}"
                        )

                        # Parse description to extract individual events
                        # Description format: "laughter (85%), speech (62%), ..."
                        # Split by comma and parse each event
                        events_list = description.split(", ")

                        for event_str in events_list[:3]:  # Limit to top 3 events per segment
                            # Parse "event_type (confidence%)" format
                            if "(" in event_str and ")" in event_str:
                                event_type = event_str.split("(")[0].strip()
                                confidence_str = event_str.split("(")[1].split("%")[0].strip()

                                try:
                                    confidence = float(confidence_str) / 100.0
                                except ValueError:
                                    confidence = 0.5  # Default confidence

                                # Skip low confidence or "emotion:" prefix events for cleaner UI
                                if confidence < 0.3:
                                    continue

                                # Handle emotion prefix (e.g., "emotion: happy")
                                if event_type.startswith("emotion:"):
                                    event_type = event_type.replace("emotion:", "").strip()

                                # Add individual audio source for each event
                                audio_sources.append({
                                    "start_time": f"{int(float(metadata['start']) // 3600):02d}:{int((float(metadata['start']) % 3600) // 60):02d}:{int(float(metadata['start']) % 60):02d}",
                                    "end_time": f"{int(float(metadata['end']) // 3600):02d}:{int((float(metadata['end']) % 3600) // 60):02d}:{int(float(metadata['end']) % 60):02d}",
                                    "start": float(metadata['start']),
                                    "end": float(metadata['end']),
                                    "speaker": metadata.get('speaker', 'Unknown'),
                                    "event_type": event_type,
                                    "confidence": confidence,
                                    "type": "audio"
                                })

                    audio_context = "\n".join(audio_parts)
            except Exception as e:
                print(f"Warning: Failed to search audio events: {str(e)}")
                import traceback
                traceback.print_exc()

        # Build prompt for LLM
        if include_visuals and image_paths:
            system_message = """You are an expert AI assistant specialized in analyzing video content, combining both visual and textual information.

Your role:
- Analyze both the visual content (screenshots) and transcript text
- Provide detailed, comprehensive answers based on what you see and what is said
- Always cite specific timestamps when referencing information (use format [HH:MM:SS])
- Identify speakers and their contributions clearly
- Describe visual elements when relevant to the question
- Connect visual and textual information to provide richer insights
- Offer insights and analysis, not just basic summaries
- Use markdown formatting for better readability (bold, bullet points, etc.)

Communication style:
- Think through your analysis out loud: "Looking at this section, I notice...", "What's interesting here is..."
- Express when something is ambiguous: "The transcript isn't entirely clear on this, but based on the visual context..."
- Offer constructive observations: "One thing worth noting...", "A potential concern here is..."
- When you see multiple interpretations, acknowledge them: "This could mean X or Y - based on what I see, I lean toward X because..."
- If the question could be interpreted multiple ways, briefly ask for clarification at the end
- Be honest about limitations: "I can see X in the screenshot, but I'd need more context to determine..."

Guidelines:
- When analyzing screenshots, describe what you observe and how it relates to the question
- Include relevant quotes from speakers when appropriate
- Explain context, implications, and connections between ideas
- If asked to summarize, organize information logically with bullet points or sections
- Reference multiple sources/timestamps to support your answers
- If the context is insufficient, explain what information is missing"""

            # Append custom instructions if provided
            if custom_instructions:
                system_message += f"\n\nUser's custom instructions (follow these preferences):\n{custom_instructions}"

            user_message_parts = [
                "Based on the following transcript segments and screenshots from the video, please answer the question comprehensively.",
                "",
                "VIDEO TRANSCRIPT CONTEXT:",
                context,
                "",
                "VISUAL CONTEXT (Screenshots provided):",
                visual_context
            ]

            if audio_context:
                user_message_parts.extend([
                    "",
                    "AUDIO CONTEXT (Sound Events):",
                    audio_context
                ])

            user_message_parts.extend([
                "",
                f"QUESTION: {question}",
                "",
                "Please provide a detailed, well-structured answer that:",
                "1. Directly addresses the question",
                "2. Analyzes both the visual content in the screenshots AND the transcript text"
            ])

            if audio_context:
                user_message_parts.append("3. Considers relevant audio events and sound cues")
                user_message_parts.append("4. Cites specific timestamps and speakers")
                user_message_parts.append("5. Describes relevant visual elements you observe")
                user_message_parts.append("6. Provides context and analysis connecting visual, audio, and textual information")
                user_message_parts.append("7. Uses markdown formatting for clarity")
            else:
                user_message_parts.append("3. Cites specific timestamps and speakers")
                user_message_parts.append("4. Describes relevant visual elements you observe")
                user_message_parts.append("5. Provides context and analysis connecting visual and textual information")
                user_message_parts.append("6. Uses markdown formatting for clarity")

            user_message = "\n".join(user_message_parts)
        else:
            system_message = """You are an expert AI assistant specialized in analyzing video content and transcripts.

Your role:
- Provide detailed, comprehensive answers based on the video transcript
- Always cite specific timestamps when referencing information (use format [HH:MM:SS])
- Identify speakers and their contributions clearly
- Connect related points across different parts of the video
- Offer insights and analysis, not just basic summaries
- Use markdown formatting for better readability (bold, bullet points, etc.)

Communication style:
- Think through your analysis out loud: "Looking at this section, I notice...", "What's interesting here is..."
- Express when something is ambiguous: "The transcript isn't entirely clear on this, but based on the context..."
- Offer constructive observations: "One thing worth noting...", "A potential concern here is..."
- When you see multiple interpretations, acknowledge them: "This could mean X or Y - based on the surrounding discussion, I lean toward X because..."
- If the question could be interpreted multiple ways, briefly ask for clarification at the end
- Be honest about limitations: "Based on what's in the transcript, I can tell you X, but I'd need more context to determine..."

Guidelines:
- Be thorough and detailed in your responses
- Include relevant quotes from speakers when appropriate
- Explain context, implications, and connections between ideas
- If asked to summarize, organize information logically with bullet points or sections
- Reference multiple sources/timestamps to support your answers
- If the context is insufficient, explain what information is missing"""

            # Append custom instructions if provided
            if custom_instructions:
                system_message += f"\n\nUser's custom instructions (follow these preferences):\n{custom_instructions}"

            user_message_parts = [
                "Based on the following transcript segments from the video, please answer the question comprehensively.",
                "",
                "VIDEO TRANSCRIPT CONTEXT:",
                context
            ]

            if audio_context:
                user_message_parts.extend([
                    "",
                    "AUDIO CONTEXT (Sound Events):",
                    audio_context
                ])

            user_message_parts.extend([
                "",
                f"QUESTION: {question}",
                "",
                "Please provide a detailed, well-structured answer that:",
                "1. Directly addresses the question",
                "2. Cites specific timestamps and speakers",
                "3. Provides context and analysis"
            ])

            if audio_context:
                user_message_parts.append("4. Considers relevant audio events and sound cues")
                user_message_parts.append("5. Uses markdown formatting for clarity")
                user_message_parts.append("6. Connects related information from different parts of the video")
            else:
                user_message_parts.append("4. Uses markdown formatting for clarity")
                user_message_parts.append("5. Connects related information from different parts of the video")

            user_message = "\n".join(user_message_parts)

        messages = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message}
        ]

        # Get LLM provider and generate response
        try:
            provider = llm_manager.get_provider(provider_name)

            # Use vision API if images are available and provider supports it
            if include_visuals and image_paths and provider.supports_vision():
                print(f"Using vision-capable model for analysis with {len(image_paths)} images")
                answer = await provider.generate_with_images(
                    messages,
                    image_paths,
                    temperature=0.7,
                    max_tokens=2000
                )
            else:
                if include_visuals and not provider.supports_vision():
                    print(f"Warning: Provider {provider_name} does not support vision. Falling back to text-only.")
                answer = await provider.generate(messages, temperature=0.7, max_tokens=2000)
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"LLM generation failed: {str(e)}"
            )

        # Combine text, visual, and audio sources
        all_sources = sources + visual_sources + audio_sources

        # Debug logging
        print(f"DEBUG: text sources: {len(sources)}, visual sources: {len(visual_sources)}, audio sources: {len(audio_sources)}")
        if audio_sources:
            print(f"DEBUG: First audio source: {audio_sources[0]}")

        response = {
            "answer": answer,
            "sources": all_sources,
            "provider_used": provider_name or llm_manager.default_provider,
            "video_hash": video_hash
        }

        # Add visual query if it was used
        if visual_query_used:
            response["visual_query_used"] = visual_query_used

        return response

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in chat: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Chat failed: {str(e)}")


@router.get(
    "/llm/providers",
    response_model=Dict,
    summary="List LLM providers",
    description="List all available LLM providers and their status",
    responses={
        503: {"model": ErrorResponse, "description": "LLM features not available"}
    }
)
@require_auth
async def list_llm_providers(request: Request) -> Dict:
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


@router.post(
    "/llm/test",
    response_model=TestLLMResponse,
    summary="Test LLM provider",
    description="Test an LLM provider with a simple prompt",
    responses={
        503: {"model": ErrorResponse, "description": "LLM features not available"}
    }
)
@require_auth
async def test_llm_provider(request: Request, test_request: TestLLMRequest) -> TestLLMResponse:
    """Test an LLM provider"""
    if not LLM_AVAILABLE:
        raise HTTPException(status_code=503, detail="LLM features not available")

    try:
        provider_name = test_request.provider
        test_prompt = test_request.prompt or "Hello! Please respond with 'OK' if you can read this."

        provider = llm_manager.get_provider(provider_name)

        # Test with a simple message
        messages = [
            {"role": "user", "content": test_prompt}
        ]

        response = await provider.generate(messages, temperature=0.5, max_tokens=50)

        return TestLLMResponse(
            success=True,
            provider=provider_name or llm_manager.default_provider,
            response=response,
            error=None
        )
    except Exception as e:
        return TestLLMResponse(
            success=False,
            provider=test_request.provider,
            response=None,
            error=str(e)
        )


@router.post(
    "/index_images/",
    response_model=IndexImagesResponse,
    summary="Index video images",
    description="Index video screenshots using CLIP embeddings for visual search",
    responses={
        503: {"model": ErrorResponse, "description": "LLM features not available"},
        404: {"model": ErrorResponse, "description": "Transcription not found"}
    }
)
@require_auth
async def index_video_images(request: Request, video_hash: str = None, force_reindex: bool = False) -> IndexImagesResponse:
    """
    Index video screenshots using CLIP embeddings for visual search

    Args:
        video_hash: Optional video hash. If not provided, uses last transcription
        force_reindex: If True, delete existing index and re-index all images
    """
    if not LLM_AVAILABLE:
        raise HTTPException(status_code=503, detail="LLM features not available. Install required dependencies.")

    try:
        # Get transcription data from any available source (legacy DB or Supabase jobs)
        if video_hash:
            transcription = get_transcription_from_any_source(video_hash)
            if not transcription:
                raise HTTPException(status_code=404, detail="Transcription not found")
        else:
            # Use last transcription
            global _last_transcription_data
            if not _last_transcription_data:
                raise HTTPException(status_code=404, detail="No transcription available")
            transcription = _last_transcription_data
            video_hash = transcription.get('video_hash')

        # Get segments
        segments = transcription.get('transcription', {}).get('segments', [])
        if not segments:
            raise HTTPException(status_code=400, detail="No segments found in transcription")

        # Index images using appropriate service
        use_supabase = _use_supabase_for_images()
        storage_type = "Supabase pgvector" if use_supabase else "ChromaDB"
        print(f"Indexing images for video {video_hash} from {len(segments)} segments using {storage_type}... (force_reindex={force_reindex})")

        # Run in executor - CLIP batch encoding is very CPU/GPU intensive
        if use_supabase:
            num_images = await _run_in_executor(
                image_embedding_service.index_video_images, video_hash, segments, force_reindex=force_reindex
            )
        else:
            num_images = await _run_in_executor(
                vector_store.index_video_images, video_hash, segments, force_reindex=force_reindex
            )

        return IndexImagesResponse(
            success=True,
            video_hash=video_hash,
            images_indexed=num_images,
            message=f"Successfully indexed {num_images} images from {len(segments)} segments (storage: {storage_type})"
        )
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error indexing images: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to index images: {str(e)}")


@router.post(
    "/search_images/",
    response_model=SearchImagesResponse,
    summary="Search video images",
    description="Search for video screenshots using text queries via CLIP embeddings",
    responses={
        503: {"model": ErrorResponse, "description": "LLM features not available"},
        404: {"model": ErrorResponse, "description": "Video not found or images not indexed"}
    }
)
@require_auth
async def search_video_images(request: Request, search_request: SearchImagesRequest) -> SearchImagesResponse:
    """
    Search for video screenshots using text queries via CLIP embeddings

    This endpoint allows you to search for visual moments in a video by describing what you're looking for.
    For example: "person pointing at screen", "whiteboard with equations", "close-up of face", etc.
    """
    if not LLM_AVAILABLE:
        raise HTTPException(status_code=503, detail="LLM features not available")

    try:
        query = search_request.query
        video_hash = search_request.video_hash
        n_results = search_request.n_results or 5

        if not query:
            raise HTTPException(status_code=400, detail="Query is required")

        # Get video_hash from last transcription if not provided
        if not video_hash:
            global _last_transcription_data
            if not _last_transcription_data:
                raise HTTPException(status_code=404, detail="No video available for image search")
            video_hash = _last_transcription_data.get('video_hash')

        # Determine which service to use
        use_supabase = _use_supabase_for_images()

        # Check if images are indexed in the appropriate store
        if use_supabase:
            images_exist = image_embedding_service.image_collection_exists(video_hash)
        else:
            images_exist = vector_store.image_collection_exists(video_hash)

        if not images_exist:
            raise HTTPException(
                status_code=404,
                detail="Images not indexed for this video. Please index images first using /api/index_images/"
            )

        # Check if the query mentions a specific speaker
        speaker_filter = _extract_speaker_from_query(query, video_hash)

        # Search for images using appropriate service
        # Run in executor - CLIP encoding is CPU/GPU intensive
        storage_type = "Supabase" if use_supabase else "ChromaDB"
        print(f"Searching images for query: {query} (using {storage_type})")

        if use_supabase:
            search_results = await _run_in_executor(
                image_embedding_service.search_images,
                video_hash,
                query,
                n_results=n_results,
                speaker_filter=speaker_filter
            )
        else:
            search_results = await _run_in_executor(
                vector_store.search_images,
                video_hash,
                query,
                n_results=n_results,
                speaker_filter=speaker_filter
            )

        # Format results (handle both Supabase and ChromaDB response formats)
        formatted_results = []
        for result in search_results:
            metadata = result['metadata']
            # Supabase uses 'screenshot_url', ChromaDB uses 'screenshot_path'
            screenshot = result.get('screenshot_url') or result.get('screenshot_path')
            # Supabase uses 'similarity' (0-1), ChromaDB uses 'distance' (lower = better)
            score = result.get('similarity') or result.get('distance')
            formatted_results.append(
                ImageSearchResult(
                    screenshot_path=screenshot,
                    segment_id=metadata['segment_id'],
                    start=metadata['start'],
                    end=metadata['end'],
                    speaker=metadata['speaker'],
                    distance=score
                )
            )

        return SearchImagesResponse(
            results=formatted_results,
            video_hash=video_hash,
            query=query
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error searching images: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Image search failed: {str(e)}")
