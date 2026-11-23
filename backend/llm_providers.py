"""
LLM Provider Abstraction Layer
Supports multiple LLM providers: Ollama (local), Groq, OpenAI, Anthropic, Grok (xAI), DeepSeek
"""

import os
import asyncio
import httpx
import base64
import io
import copy
from abc import ABC, abstractmethod
from typing import AsyncIterator, Dict, List, Optional, Any
from dotenv import load_dotenv
from pathlib import Path
from PIL import Image
from services.model_catalog import ReasoningEffort, reasoning_effort_options
from services.provider_http import VisionGenerationError, VisionTimeoutError

load_dotenv()

# Get the backend directory path for resolving relative paths
BACKEND_DIR = Path(__file__).parent.absolute()


def _compress_image(image_bytes: bytes, max_dimension: int = 1024, quality: int = 85) -> bytes:
    """Resize and compress an image to reduce payload size for vision APIs."""
    img = Image.open(io.BytesIO(image_bytes))

    # Convert RGBA/palette to RGB for JPEG output
    if img.mode in ('RGBA', 'LA', 'P'):
        img = img.convert('RGB')

    # Resize if larger than max_dimension
    w, h = img.size
    if max(w, h) > max_dimension:
        scale = max_dimension / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=quality)
    return buf.getvalue()


def _load_image_as_base64(img_path: str) -> Optional[tuple[str, str]]:
    """
    Load an image from a URL or local path, compress it, and return as base64.

    Args:
        img_path: URL (http/https) or local file path

    Returns:
        Tuple of (base64_data, media_type) or None if failed
    """
    try:
        # Check if it's a URL
        if img_path.startswith('http://') or img_path.startswith('https://'):
            # Download from URL
            import httpx
            with httpx.Client(timeout=30.0, follow_redirects=True) as client:
                response = client.get(img_path)
                response.raise_for_status()
                image_bytes = response.content
        else:
            # Local file path
            if img_path.startswith('./') or img_path.startswith('static/'):
                abs_path = BACKEND_DIR / img_path.lstrip('./')
            elif img_path.startswith('/static/'):
                abs_path = BACKEND_DIR / img_path.lstrip('/')
            else:
                abs_path = Path(img_path)

            if not abs_path.exists():
                print(f"Warning: Image file does not exist: {abs_path}")
                return None

            with open(abs_path, "rb") as image_file:
                image_bytes = image_file.read()

        # Compress and resize to reduce payload
        compressed = _compress_image(image_bytes)
        encoded = base64.b64encode(compressed).decode('utf-8')
        return (encoded, 'image/jpeg')

    except Exception as e:
        print(f"Warning: Failed to load image {img_path}: {str(e)}")
        return None


async def _load_images_as_base64(paths: List[str]) -> tuple[List[tuple[str, str]], List[str]]:
    """Load images off the event loop, in parallel; returns (loaded, failed_paths) in input order."""
    results = await asyncio.gather(*(asyncio.to_thread(_load_image_as_base64, path) for path in paths))
    loaded = [result for result in results if result]
    failed = [path for path, result in zip(paths, results) if not result]
    return loaded, failed


def _vision_retry_failure(
    provider_label: str,
    exc: BaseException,
    *,
    timeout_seconds: float,
    model: str,
    image_count: int,
) -> VisionGenerationError:
    # str(asyncio.TimeoutError()) is "", which hid the cause and defeated error classification.
    context = f"(model {model}, {image_count} images)"
    if isinstance(exc, (asyncio.TimeoutError, httpx.TimeoutException)):
        return VisionTimeoutError(f"{provider_label} vision request timed out after {timeout_seconds:.0f}s {context}")
    return VisionGenerationError(
        f"{provider_label} vision request failed: {type(exc).__name__}: {str(exc) or 'no detail'} {context}"
    )


class BaseLLMProvider(ABC):
    """Base class for all LLM providers"""

    max_vision_images: Optional[int] = None

    @abstractmethod
    async def generate(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1000
    ) -> str:
        """
        Generate a response from the LLM

        Args:
            messages: List of message dicts with 'role' and 'content'
            temperature: Sampling temperature (0-1)
            max_tokens: Maximum tokens to generate

        Returns:
            Generated text response
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the provider is properly configured"""
        pass

    def supports_vision(self) -> bool:
        """Check if the provider supports vision/image inputs"""
        return False

    async def generate_with_images(
        self,
        messages: List[Dict[str, Any]],
        image_paths: List[str],
        temperature: float = 0.7,
        max_tokens: int = 2000
    ) -> str:
        """
        Generate a response with image inputs (for vision-capable models)

        Args:
            messages: List of message dicts with 'role' and 'content'
            image_paths: List of paths to images to include
            temperature: Sampling temperature (0-1)
            max_tokens: Maximum tokens to generate

        Returns:
            Generated text response
        """
        # Default implementation for non-vision models: ignore images
        return await self.generate(messages, temperature, max_tokens)

    async def generate_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1000
    ) -> AsyncIterator[str]:
        """
        Stream a response as text chunks. Default: fall back to generate()
        and yield the whole response in one chunk, so non-streaming providers
        still work behind the streaming API.
        """
        answer = await self.generate(messages, temperature, max_tokens)
        yield answer


class OllamaProvider(BaseLLMProvider):
    """Local Ollama LLM provider"""

    def __init__(self):
        self.base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.model = os.getenv("OLLAMA_MODEL", "llama3.2:3b")

    async def generate(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1000
    ) -> str:
        """Generate response using Ollama"""
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{self.base_url}/api/chat",
                    json={
                        "model": self.model,
                        "messages": messages,
                        "stream": False,
                        "options": {
                            "temperature": temperature,
                            "num_predict": max_tokens
                        }
                    }
                )
                response.raise_for_status()
                result = response.json()
                return result.get("message", {}).get("content", "")
        except Exception as e:
            raise Exception(f"Ollama generation failed: {str(e)}")

    def is_available(self) -> bool:
        """Check if Ollama is running and accessible"""
        try:
            response = httpx.get(f"{self.base_url}/api/tags", timeout=5.0)
            return response.status_code == 200
        except Exception:
            return False


class GroqProvider(BaseLLMProvider):
    """Groq cloud LLM provider"""

    def __init__(self):
        self.api_key = os.getenv("GROQ_API_KEY")
        self.model = os.getenv("GROQ_MODEL", "llama-3.1-70b-versatile")
        self.base_url = "https://api.groq.com/openai/v1"

    async def generate(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1000
    ) -> str:
        """Generate response using Groq"""
        if not self.api_key or self.api_key == "your_groq_api_key_here":
            raise Exception("Groq API key not configured")

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": self.model,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens
                    }
                )
                response.raise_for_status()
                result = response.json()
                return result["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as e:
            # Log the full error response from Groq
            error_detail = e.response.text if hasattr(e.response, 'text') else str(e)
            raise Exception(f"Groq generation failed: {str(e)}\nResponse: {error_detail}")
        except Exception as e:
            raise Exception(f"Groq generation failed: {str(e)}")

    def is_available(self) -> bool:
        """Check if Groq API key is configured"""
        return bool(self.api_key and self.api_key != "your_groq_api_key_here")


class OpenAIProvider(BaseLLMProvider):
    """OpenAI cloud LLM provider"""

    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.model = os.getenv("OPENAI_MODEL", "gpt-5.6-terra")
        self.base_url = "https://api.openai.com/v1"

    def _build_payload(self, messages: List[Dict[str, Any]], max_tokens: int) -> Dict[str, Any]:
        # GPT-5+ rejects max_tokens and any non-default temperature with HTTP 400.
        return {
            "model": self.model,
            "messages": messages,
            "max_completion_tokens": max_tokens,
        }

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        # raise_for_status() drops OpenAI's JSON error body, which is the only place
        # model_not_found / insufficient_quota show up.
        if response.is_error:
            raise Exception(f"HTTP {response.status_code}: {response.text[:500]}")

    async def generate(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1000
    ) -> str:
        """Generate response using OpenAI"""
        if not self.api_key or self.api_key == "your_openai_api_key_here":
            raise Exception("OpenAI API key not configured")

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json=self._build_payload(messages, max_tokens)
                )
                self._raise_for_status(response)
                result = response.json()
                return result["choices"][0]["message"]["content"]
        except Exception as e:
            raise Exception(f"OpenAI generation failed: {str(e)}")

    def is_available(self) -> bool:
        """Check if OpenAI API key is configured"""
        return bool(self.api_key and self.api_key != "your_openai_api_key_here")

    def supports_vision(self) -> bool:
        """Current OpenAI chat models accept image_url content natively"""
        return True

    async def generate_with_images(
        self,
        messages: List[Dict[str, Any]],
        image_paths: List[str],
        temperature: float = 0.7,
        max_tokens: int = 2000
    ) -> str:
        """Generate response with images using OpenAI Vision API"""
        if not self.api_key or self.api_key == "your_openai_api_key_here":
            raise Exception("OpenAI API key not configured")

        request_timeout = 240.0
        try:
            # Convert images to base64 (supports both URLs and local paths)
            loaded, failed_images = await _load_images_as_base64(image_paths)
            image_data = [encoded for encoded, _ in loaded]

            if failed_images:
                print(f"Note: {len(failed_images)} of {len(image_paths)} images could not be loaded. "
                      f"Consider running /cleanup_screenshots to remove orphaned screenshot files.")

            if not image_data:
                # No images could be loaded, fall back to text-only
                return await self.generate(messages, temperature, max_tokens)

            # Format messages for OpenAI Vision API
            formatted_messages = []
            for msg in messages:
                if msg["role"] == "user" and image_data:
                    # Add images to the user message
                    content = [{"type": "text", "text": msg["content"]}]
                    for img_b64 in image_data:
                        content.append({
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{img_b64}"
                            }
                        })
                    formatted_messages.append({
                        "role": msg["role"],
                        "content": content
                    })
                else:
                    formatted_messages.append(msg)

            async with httpx.AsyncClient(timeout=request_timeout) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json=self._build_payload(formatted_messages, max_tokens)
                )
                self._raise_for_status(response)
                result = response.json()
                return result["choices"][0]["message"]["content"]
        except Exception as e:
            raise _vision_retry_failure(
                "OpenAI", e, timeout_seconds=request_timeout, model=self.model, image_count=len(image_paths)
            ) from e


class AnthropicProvider(BaseLLMProvider):
    """Anthropic (Claude) cloud LLM provider"""

    def __init__(self):
        self.api_key = os.getenv("ANTHROPIC_API_KEY")
        self.model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")
        self.base_url = "https://api.anthropic.com/v1"

    async def generate(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1000
    ) -> str:
        """Generate response using Anthropic"""
        if not self.api_key or self.api_key == "your_anthropic_api_key_here":
            raise Exception("Anthropic API key not configured")

        try:
            # Convert messages to Anthropic format
            system_message = None
            user_messages = []

            for msg in messages:
                if msg["role"] == "system":
                    system_message = msg["content"]
                else:
                    user_messages.append({
                        "role": msg["role"],
                        "content": msg["content"]
                    })

            async with httpx.AsyncClient(timeout=60.0) as client:
                payload = {
                    "model": self.model,
                    "messages": user_messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens
                }

                if system_message:
                    payload["system"] = system_message

                response = await client.post(
                    f"{self.base_url}/messages",
                    headers={
                        "x-api-key": self.api_key,
                        "anthropic-version": "2023-06-01",
                        "Content-Type": "application/json"
                    },
                    json=payload
                )
                response.raise_for_status()
                result = response.json()
                return result["content"][0]["text"]
        except Exception as e:
            raise Exception(f"Anthropic generation failed: {str(e)}")

    def is_available(self) -> bool:
        """Check if Anthropic API key is configured"""
        return bool(self.api_key and self.api_key != "your_anthropic_api_key_here")

    def supports_vision(self) -> bool:
        """Anthropic Claude 3+ models support vision"""
        return True

    async def generate_with_images(
        self,
        messages: List[Dict[str, Any]],
        image_paths: List[str],
        temperature: float = 0.7,
        max_tokens: int = 2000
    ) -> str:
        """Generate response with images using Anthropic Vision API"""
        if not self.api_key or self.api_key == "your_anthropic_api_key_here":
            raise Exception("Anthropic API key not configured")

        request_timeout = 120.0
        try:
            # Convert images to base64 (supports both URLs and local paths)
            loaded, failed_images = await _load_images_as_base64(image_paths)
            image_data = [{"data": encoded, "media_type": media_type} for encoded, media_type in loaded]

            if failed_images:
                print(f"Note: {len(failed_images)} of {len(image_paths)} images could not be loaded. "
                      f"Consider running /cleanup_screenshots to remove orphaned screenshot files.")

            if not image_data:
                # No images could be loaded, fall back to text-only
                return await self.generate(messages, temperature, max_tokens)

            # Convert messages to Anthropic format with images
            system_message = None
            user_messages = []

            for msg in messages:
                if msg["role"] == "system":
                    system_message = msg["content"]
                elif msg["role"] == "user" and image_data:
                    # Add images to the user message as content blocks
                    content_blocks = [{"type": "text", "text": msg["content"]}]
                    for img in image_data:
                        content_blocks.append({
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": img["media_type"],
                                "data": img["data"]
                            }
                        })
                    user_messages.append({
                        "role": msg["role"],
                        "content": content_blocks
                    })
                else:
                    user_messages.append({
                        "role": msg["role"],
                        "content": msg["content"]
                    })

            async with httpx.AsyncClient(timeout=request_timeout) as client:
                payload = {
                    "model": self.model,
                    "messages": user_messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens
                }

                if system_message:
                    payload["system"] = system_message

                response = await client.post(
                    f"{self.base_url}/messages",
                    headers={
                        "x-api-key": self.api_key,
                        "anthropic-version": "2023-06-01",
                        "Content-Type": "application/json"
                    },
                    json=payload
                )
                response.raise_for_status()
                result = response.json()
                return result["content"][0]["text"]
        except Exception as e:
            raise _vision_retry_failure(
                "Anthropic", e, timeout_seconds=request_timeout, model=self.model, image_count=len(image_paths)
            ) from e


class GrokProvider(BaseLLMProvider):
    """xAI Grok cloud LLM provider (OpenAI-compatible API)"""

    def __init__(self, model_override: str | None = None):
        self.api_key = os.getenv("XAI_API_KEY")
        self.model = model_override or os.getenv("XAI_MODEL", "grok-beta")
        self.base_url = "https://api.x.ai/v1"
        self.reasoning_effort: Optional[ReasoningEffort] = None

    def _reasoning_parameters(self) -> Dict[str, str]:
        return {"reasoning_effort": self.reasoning_effort} if self.reasoning_effort else {}

    async def generate(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1000
    ) -> str:
        """Generate response using Grok (xAI)"""
        if not self.api_key or self.api_key == "your_xai_api_key_here":
            raise Exception("xai_api_key_missing: xAI API key not configured")

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": self.model,
                        **self._reasoning_parameters(),
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens
                    }
                )
                response.raise_for_status()
                result = response.json()
                return result["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as e:
            # Log the full error response from xAI
            error_detail = e.response.text if hasattr(e.response, 'text') else str(e)
            raise Exception(f"Grok generation failed: {str(e)}\nResponse: {error_detail}")
        except Exception as e:
            raise Exception(f"Grok generation failed: {str(e)}")

    async def generate_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1000
    ) -> AsyncIterator[str]:
        """Stream tokens from Grok (xAI) via SSE."""
        import json as _json

        if not self.api_key or self.api_key == "your_xai_api_key_here":
            raise Exception("xai_api_key_missing: xAI API key not configured")

        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                },
                json={
                    "model": self.model,
                    **self._reasoning_parameters(),
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "stream": True,
                },
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        chunk = _json.loads(payload)
                    except Exception:
                        continue
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    content = delta.get("content")
                    if content:
                        yield content

    def is_available(self) -> bool:
        """Check if xAI API key is configured"""
        return bool(self.api_key and self.api_key != "your_xai_api_key_here")

    def supports_vision(self) -> bool:
        """Grok supports vision with grok-vision models"""
        return True

    @property
    def max_vision_images(self) -> int:
        return int(os.getenv("XAI_VISION_MAX_IMAGES", "6"))

    async def generate_with_images(
        self,
        messages: List[Dict[str, Any]],
        image_paths: List[str],
        temperature: float = 0.7,
        max_tokens: int = 2000
    ) -> str:
        """Generate response with images using Grok Vision API (OpenAI-compatible)"""
        if not self.api_key or self.api_key == "your_xai_api_key_here":
            raise Exception("xai_api_key_missing: xAI API key not configured")

        try:
            # Convert images to base64 (supports both URLs and local paths)
            image_paths = image_paths[: self.max_vision_images]
            loaded, failed_images = await _load_images_as_base64(image_paths)
            image_data = [encoded for encoded, _ in loaded]

            if failed_images:
                print(f"Note: {len(failed_images)} of {len(image_paths)} images could not be loaded. "
                      f"Consider running /cleanup_screenshots to remove orphaned screenshot files.")

            if not image_data:
                # No images could be loaded, fall back to text-only
                return await self.generate(messages, temperature, max_tokens)

            # Format messages for Grok Vision API (OpenAI-compatible format)
            formatted_messages = []
            for msg in messages:
                if msg["role"] == "user" and image_data:
                    # Add images to the user message
                    content = [{"type": "text", "text": msg["content"]}]
                    for img_b64 in image_data:
                        content.append({
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{img_b64}"
                            }
                        })
                    formatted_messages.append({
                        "role": msg["role"],
                        "content": content
                    })
                else:
                    formatted_messages.append(msg)

            vision_model = self.model
            print(f"Using vision model: {vision_model} (thinking effort: {self.reasoning_effort or 'provider-default'})")

            # Reasoning models (grok-4.6+) with several images routinely need more than 45s.
            request_timeout = float(os.getenv("XAI_VISION_TIMEOUT_SECONDS", "120"))
            max_retries = max(1, int(os.getenv("XAI_VISION_MAX_RETRIES", "1")))
            last_exception = None
            for attempt in range(max_retries):
                try:
                    timeout = httpx.Timeout(request_timeout, connect=10.0, write=30.0, pool=10.0)
                    async with httpx.AsyncClient(timeout=timeout) as client:
                        print(
                            f"Calling xAI vision API with {len(image_data)} images "
                            f"(attempt {attempt + 1}/{max_retries}, timeout={request_timeout:.0f}s)"
                        )
                        response = await asyncio.wait_for(
                            client.post(
                                f"{self.base_url}/chat/completions",
                                headers={
                                    "Authorization": f"Bearer {self.api_key}",
                                    "Content-Type": "application/json"
                                },
                                json={
                                    "model": vision_model,
                                    **self._reasoning_parameters(),
                                    "messages": formatted_messages,
                                    "temperature": temperature,
                                    "max_tokens": max_tokens
                                }
                            ),
                            timeout=request_timeout,
                        )
                        response.raise_for_status()
                        result = response.json()
                        return result["choices"][0]["message"]["content"]
                except (asyncio.TimeoutError, httpx.TimeoutException, httpx.ConnectError) as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        print(f"Vision API timeout/connection error (attempt {attempt + 1}/{max_retries}), retrying in 3s...")
                        await asyncio.sleep(3)
                    continue
                except httpx.HTTPStatusError as e:
                    if e.response.status_code in (502, 503, 504) and attempt < max_retries - 1:
                        print(f"Vision API returned {e.response.status_code} (attempt {attempt + 1}/{max_retries}), retrying in 3s...")
                        await asyncio.sleep(3)
                        last_exception = e
                        continue
                    error_detail = e.response.text if hasattr(e.response, 'text') else str(e)
                    raise VisionGenerationError(f"Grok vision generation failed: {str(e)}\nResponse: {error_detail}")
            raise _vision_retry_failure(
                "Grok",
                last_exception,
                timeout_seconds=request_timeout,
                model=vision_model,
                image_count=len(image_data),
            )
        except VisionGenerationError:
            raise
        except Exception as e:
            raise Exception(f"Grok vision generation failed: {type(e).__name__}: {str(e)}")


    async def caption_image(
        self,
        image_path: str,
        prompt: str = "Caption this frame.",
        temperature: float = 0.2,
        max_tokens: int = 250,
    ) -> Optional[str]:
        """Caption a single frame for the search index. Never raises: returns
        None on any failure so bulk captioning is failure-tolerant."""
        if not self.api_key or self.api_key == "your_xai_api_key_here":
            return None

        result = await asyncio.to_thread(_load_image_as_base64, image_path)
        if not result:
            return None
        encoded_image, _ = result

        from config import settings
        caption_model = settings.XAI_CAPTION_MODEL
        request_timeout = float(os.getenv("XAI_VISION_TIMEOUT_SECONDS", "45"))

        payload = {
            "model": caption_model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": CAPTION_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{encoded_image}"},
                        },
                    ],
                },
            ],
        }

        for attempt in range(2):
            try:
                timeout = httpx.Timeout(request_timeout, connect=10.0, write=30.0, pool=10.0)
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await asyncio.wait_for(
                        client.post(
                            f"{self.base_url}/chat/completions",
                            headers={
                                "Authorization": f"Bearer {self.api_key}",
                                "Content-Type": "application/json",
                            },
                            json=payload,
                        ),
                        timeout=request_timeout,
                    )
                    response.raise_for_status()
                    content = response.json()["choices"][0]["message"]["content"]
                    return content.strip() if content else None
            except (asyncio.TimeoutError, httpx.TimeoutException, httpx.ConnectError):
                if attempt == 0:
                    await asyncio.sleep(3)
                    continue
                return None
            except httpx.HTTPStatusError as e:
                if e.response.status_code in (429, 502, 503, 504) and attempt == 0:
                    await asyncio.sleep(3)
                    continue
                print(f"Caption request failed ({e.response.status_code}): {e.response.text[:200]}")
                return None
            except Exception as e:
                print(f"Caption request failed: {e}")
                return None
        return None


# Captions feed a private per-user search index, not user-facing text, so keep them plain and factual.
CAPTION_SYSTEM_PROMPT = (
    "You are a factual frame-captioning system for a private, user-owned video search index. "
    "Describe exactly what is visible in the frame in 1-3 plain sentences: how many people, their "
    "appearance and clothing, their body positions, the physical actions taking place, and the "
    "setting. Do not identify real people. If nothing notable is visible, describe the scene neutrally."
)


class DeepSeekProvider(BaseLLMProvider):
    """DeepSeek cloud LLM provider using its OpenAI-compatible API."""

    def __init__(self):
        self.api_key = os.getenv("DEEPSEEK_API_KEY")
        self.model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
        self.base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")

    async def generate(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1000
    ) -> str:
        """Generate response using DeepSeek."""
        if not self.api_key or self.api_key == "your_deepseek_api_key_here":
            raise Exception("deepseek_api_key_missing: DeepSeek API key not configured")

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": self.model,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens
                    }
                )
                response.raise_for_status()
                result = response.json()
                return result["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as e:
            error_detail = e.response.text if hasattr(e.response, 'text') else str(e)
            raise Exception(f"DeepSeek generation failed: {str(e)}\nResponse: {error_detail}")
        except Exception as e:
            raise Exception(f"DeepSeek generation failed: {str(e)}")

    async def generate_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1000
    ) -> AsyncIterator[str]:
        """Stream tokens from DeepSeek via OpenAI-compatible SSE."""
        import json as _json

        if not self.api_key or self.api_key == "your_deepseek_api_key_here":
            raise Exception("deepseek_api_key_missing: DeepSeek API key not configured")

        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "stream": True,
                },
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        chunk = _json.loads(payload)
                    except Exception:
                        continue
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    content = delta.get("content")
                    if content:
                        yield content

    def is_available(self) -> bool:
        """Check if DeepSeek API key is configured."""
        return bool(self.api_key and self.api_key != "your_deepseek_api_key_here")


class LLMManager:
    """Manager for LLM providers"""

    def __init__(self):
        self.providers = {
            "ollama": OllamaProvider(),
            "groq": GroqProvider(),
            "openai": OpenAIProvider(),
            "anthropic": AnthropicProvider(),
            "grok": GrokProvider(),
            "deepseek": DeepSeekProvider()
        }
        self.default_provider = os.getenv("DEFAULT_LLM_PROVIDER", "grok")

        # Map 'local' to 'ollama'
        if self.default_provider == "local":
            self.default_provider = "ollama"

    def get_provider(
        self,
        provider_name: Optional[str] = None,
        api_key_override: Optional[str] = None,
        model_override: Optional[str] = None,
        reasoning_effort: Optional[ReasoningEffort] = None,
    ) -> BaseLLMProvider:
        """Get a specific LLM provider or the default one"""
        name = provider_name or self.default_provider

        # Map 'local' to 'ollama'
        if name == "local":
            name = "ollama"

        # The xAI provider is registered as 'grok'; accept the name the
        # API-keys page uses ('xai') as an alias.
        if name == "xai":
            name = "grok"

        if name not in self.providers:
            raise ValueError(f"Unknown provider: {name}")

        provider = self.providers[name]

        if reasoning_effort is not None:
            model = model_override or getattr(provider, "model", "")
            if reasoning_effort not in reasoning_effort_options(name, model):
                raise ValueError(f"Thinking effort '{reasoning_effort}' is not supported by {name}/{model}")

        # Copy once so per-request overrides never leak into the shared instance.
        overrides = {
            attr: value
            for attr, value in (("api_key", api_key_override), ("model", model_override), ("reasoning_effort", reasoning_effort))
            if value and hasattr(provider, attr)
        }
        if overrides:
            provider = copy.copy(provider)
            for attr, value in overrides.items():
                setattr(provider, attr, value)

        if not provider.is_available():
            raise Exception(f"Provider '{name}' is not available. Check configuration.")

        return provider

    def list_available_providers(self) -> List[Dict[str, any]]:
        """List all available providers with their status"""
        providers_status = []
        for name, provider in self.providers.items():
            providers_status.append({
                "name": name,
                "available": provider.is_available(),
                "model": getattr(provider, 'model', 'N/A')
            })
        return providers_status


# Global LLM manager instance
llm_manager = LLMManager()
