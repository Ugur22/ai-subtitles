"""
Chat and RAG (Retrieval-Augmented Generation) endpoints
"""
from typing import Dict, Optional
from fastapi import APIRouter, HTTPException, Request

from database import get_transcription
from dependencies import _last_transcription_data
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

router = APIRouter(prefix="/api", tags=["Chat & RAG"])


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
    if not query:
        return None

    query_lower = query.lower()

    # First, check enrolled speakers (e.g., "Concetta", "John")
    try:
        from speaker_recognition import get_speaker_recognition_system
        sr_system = get_speaker_recognition_system()
        enrolled_speakers = sr_system.list_speakers()

        for speaker_name in enrolled_speakers:
            if speaker_name.lower() in query_lower:
                print(f"Found enrolled speaker in query: {speaker_name}")
                return speaker_name
    except Exception as e:
        print(f"Could not load speaker recognition system: {e}")

    # If no enrolled speaker found, check for SPEAKER_XX labels in segments
    # This handles cases where segments use labels like "SPEAKER_19"
    try:
        transcription = get_transcription(video_hash)
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
                if speaker_label.lower() in query_lower:
                    print(f"Found speaker label in query: {speaker_label}")
                    return speaker_label
    except Exception as e:
        print(f"Could not check segment speakers: {e}")

    return None


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
async def index_video_for_chat(video_hash: str = None) -> IndexVideoResponse:
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
            global _last_transcription_data
            if not _last_transcription_data:
                raise HTTPException(status_code=404, detail="No transcription available")
            transcription = _last_transcription_data
            video_hash = transcription.get('video_hash')

        # Get segments
        segments = transcription.get('transcription', {}).get('segments', [])
        if not segments:
            raise HTTPException(status_code=400, detail="No segments found in transcription")

        # Index in vector database
        print(f"Indexing video {video_hash} with {len(segments)} segments...")
        num_chunks = vector_store.index_transcription(video_hash, segments)

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
async def chat_with_video(request: ChatRequest) -> Dict:
    """
    Chat with a video using RAG (Retrieval-Augmented Generation)
    """
    if not LLM_AVAILABLE:
        raise HTTPException(status_code=503, detail="LLM features not available")

    try:
        question = request.question
        video_hash = request.video_hash
        provider_name = request.provider
        n_results = request.n_results or 8
        include_visuals = request.include_visuals or False
        n_images = request.n_images or 3
        custom_instructions = request.custom_instructions

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

        if include_visuals:
            print(f"Visual analysis requested, searching for {n_images} relevant images...")

            # Check if images are indexed
            if vector_store.image_collection_exists(video_hash):
                try:
                    # Check if the query mentions a specific speaker
                    speaker_filter = _extract_speaker_from_query(question, video_hash)

                    # Search for relevant images using the question
                    image_results = vector_store.search_images(
                        video_hash,
                        question,
                        n_results=n_images,
                        speaker_filter=speaker_filter
                    )

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
                                "type": "visual"
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
                audio_results = vector_store.search_audio_events(
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

        return {
            "answer": answer,
            "sources": all_sources,
            "provider_used": provider_name or llm_manager.default_provider,
            "video_hash": video_hash
        }

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


@router.post(
    "/llm/test",
    response_model=TestLLMResponse,
    summary="Test LLM provider",
    description="Test an LLM provider with a simple prompt",
    responses={
        503: {"model": ErrorResponse, "description": "LLM features not available"}
    }
)
async def test_llm_provider(request: TestLLMRequest) -> TestLLMResponse:
    """Test an LLM provider"""
    if not LLM_AVAILABLE:
        raise HTTPException(status_code=503, detail="LLM features not available")

    try:
        provider_name = request.provider
        test_prompt = request.prompt or "Hello! Please respond with 'OK' if you can read this."

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
            provider=request.provider,
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
async def index_video_images(video_hash: str = None, force_reindex: bool = False) -> IndexImagesResponse:
    """
    Index video screenshots using CLIP embeddings for visual search

    Args:
        video_hash: Optional video hash. If not provided, uses last transcription
        force_reindex: If True, delete existing index and re-index all images
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
            global _last_transcription_data
            if not _last_transcription_data:
                raise HTTPException(status_code=404, detail="No transcription available")
            transcription = _last_transcription_data
            video_hash = transcription.get('video_hash')

        # Get segments
        segments = transcription.get('transcription', {}).get('segments', [])
        if not segments:
            raise HTTPException(status_code=400, detail="No segments found in transcription")

        # Index images in vector database
        print(f"Indexing images for video {video_hash} from {len(segments)} segments... (force_reindex={force_reindex})")
        num_images = vector_store.index_video_images(video_hash, segments, force_reindex=force_reindex)

        return IndexImagesResponse(
            success=True,
            video_hash=video_hash,
            images_indexed=num_images,
            message=f"Successfully indexed {num_images} images from {len(segments)} segments"
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
async def search_video_images(request: SearchImagesRequest) -> SearchImagesResponse:
    """
    Search for video screenshots using text queries via CLIP embeddings

    This endpoint allows you to search for visual moments in a video by describing what you're looking for.
    For example: "person pointing at screen", "whiteboard with equations", "close-up of face", etc.
    """
    if not LLM_AVAILABLE:
        raise HTTPException(status_code=503, detail="LLM features not available")

    try:
        query = request.query
        video_hash = request.video_hash
        n_results = request.n_results or 5

        if not query:
            raise HTTPException(status_code=400, detail="Query is required")

        # Get video_hash from last transcription if not provided
        if not video_hash:
            global _last_transcription_data
            if not _last_transcription_data:
                raise HTTPException(status_code=404, detail="No video available for image search")
            video_hash = _last_transcription_data.get('video_hash')

        # Check if images are indexed
        if not vector_store.image_collection_exists(video_hash):
            raise HTTPException(
                status_code=404,
                detail="Images not indexed for this video. Please index images first using /api/index_images/"
            )

        # Check if the query mentions a specific speaker
        speaker_filter = _extract_speaker_from_query(query, video_hash)

        # Search for images
        print(f"Searching images for query: {query}")
        search_results = vector_store.search_images(
            video_hash,
            query,
            n_results=n_results,
            speaker_filter=speaker_filter
        )

        # Format results
        formatted_results = []
        for result in search_results:
            metadata = result['metadata']
            formatted_results.append(
                ImageSearchResult(
                    screenshot_path=result['screenshot_path'],
                    segment_id=metadata['segment_id'],
                    start=metadata['start'],
                    end=metadata['end'],
                    speaker=metadata['speaker'],
                    distance=result.get('distance')
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
