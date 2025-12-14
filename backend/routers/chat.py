"""
Chat and RAG (Retrieval-Augmented Generation) endpoints
"""
from typing import Dict
from fastapi import APIRouter, HTTPException, Request

from database import get_transcription
from dependencies import _last_transcription_data
from models import (
    IndexVideoResponse,
    ChatRequest,
    ChatResponse,
    TestLLMRequest,
    TestLLMResponse,
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
