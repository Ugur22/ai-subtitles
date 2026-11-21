"""Per-request chat state and the executor shared by every chat module."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from typing import Any, Callable, Dict, Optional
from services.transcription_repository import transcription_repository


# Executor for CPU/GPU-bound operations (CLIP, embeddings)
# This prevents blocking the event loop during visual search and chat operations
_chat_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="chat_embed")


async def _run_in_executor(func: Callable, *args, **kwargs) -> Any:
    """Run blocking function in executor to avoid blocking event loop."""
    loop = asyncio.get_event_loop()
    if kwargs:
        return await loop.run_in_executor(_chat_executor, lambda: func(*args, **kwargs))
    return await loop.run_in_executor(_chat_executor, func, *args)


_chat_user_id: ContextVar[Optional[str]] = ContextVar("chat_user_id", default=None)


_hash_resources_allowed: ContextVar[bool] = ContextVar("hash_resources_allowed", default=False)


def get_transcription_from_any_source(
    video_hash: str,
    user_id: Optional[str] = None,
    refresh_screenshot_urls: bool = False,
) -> Optional[Dict]:
    owner_id = user_id or _chat_user_id.get()
    if not owner_id:
        return None
    return transcription_repository.get_transcription(
        video_hash,
        owner_id,
        refresh_screenshot_urls=refresh_screenshot_urls,
    )
