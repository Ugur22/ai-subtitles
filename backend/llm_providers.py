"""
LLM Provider Abstraction Layer
Supports multiple LLM providers: Ollama (local), Groq, OpenAI, Anthropic, Grok (xAI)
"""

import os
import httpx
import base64
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Union, Any
from dotenv import load_dotenv

load_dotenv()


class BaseLLMProvider(ABC):
    """Base class for all LLM providers"""

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
        except:
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
        self.model = os.getenv("OPENAI_MODEL", "gpt-4")
        self.base_url = "https://api.openai.com/v1"

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
        except Exception as e:
            raise Exception(f"OpenAI generation failed: {str(e)}")

    def is_available(self) -> bool:
        """Check if OpenAI API key is configured"""
        return bool(self.api_key and self.api_key != "your_openai_api_key_here")

    def supports_vision(self) -> bool:
        """OpenAI supports vision with gpt-4-vision models"""
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

        try:
            # Convert images to base64
            image_data = []
            for img_path in image_paths:
                try:
                    with open(img_path, "rb") as image_file:
                        encoded_image = base64.b64encode(image_file.read()).decode('utf-8')
                        image_data.append(encoded_image)
                except Exception as e:
                    print(f"Warning: Failed to load image {img_path}: {str(e)}")

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

            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": self.model if "vision" in self.model.lower() else "gpt-4-vision-preview",
                        "messages": formatted_messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens
                    }
                )
                response.raise_for_status()
                result = response.json()
                return result["choices"][0]["message"]["content"]
        except Exception as e:
            raise Exception(f"OpenAI vision generation failed: {str(e)}")


class AnthropicProvider(BaseLLMProvider):
    """Anthropic (Claude) cloud LLM provider"""

    def __init__(self):
        self.api_key = os.getenv("ANTHROPIC_API_KEY")
        self.model = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")
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

        try:
            # Convert images to base64
            image_data = []
            for img_path in image_paths:
                try:
                    with open(img_path, "rb") as image_file:
                        encoded_image = base64.b64encode(image_file.read()).decode('utf-8')
                        # Detect image type
                        ext = img_path.lower().split('.')[-1]
                        media_type = f"image/{ext}" if ext in ['jpeg', 'jpg', 'png', 'gif', 'webp'] else "image/jpeg"
                        image_data.append({
                            "data": encoded_image,
                            "media_type": media_type
                        })
                except Exception as e:
                    print(f"Warning: Failed to load image {img_path}: {str(e)}")

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

            async with httpx.AsyncClient(timeout=120.0) as client:
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
            raise Exception(f"Anthropic vision generation failed: {str(e)}")


class GrokProvider(BaseLLMProvider):
    """xAI Grok cloud LLM provider (OpenAI-compatible API)"""

    def __init__(self):
        self.api_key = os.getenv("XAI_API_KEY")
        self.model = os.getenv("XAI_MODEL", "grok-beta")
        self.base_url = "https://api.x.ai/v1"

    async def generate(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1000
    ) -> str:
        """Generate response using Grok (xAI)"""
        if not self.api_key or self.api_key == "your_xai_api_key_here":
            raise Exception("xAI API key not configured")

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
            # Log the full error response from xAI
            error_detail = e.response.text if hasattr(e.response, 'text') else str(e)
            raise Exception(f"Grok generation failed: {str(e)}\nResponse: {error_detail}")
        except Exception as e:
            raise Exception(f"Grok generation failed: {str(e)}")

    def is_available(self) -> bool:
        """Check if xAI API key is configured"""
        return bool(self.api_key and self.api_key != "your_xai_api_key_here")

    def supports_vision(self) -> bool:
        """Grok supports vision with grok-vision models"""
        return True

    async def generate_with_images(
        self,
        messages: List[Dict[str, Any]],
        image_paths: List[str],
        temperature: float = 0.7,
        max_tokens: int = 2000
    ) -> str:
        """Generate response with images using Grok Vision API (OpenAI-compatible)"""
        if not self.api_key or self.api_key == "your_xai_api_key_here":
            raise Exception("xAI API key not configured")

        try:
            # Convert images to base64
            image_data = []
            for img_path in image_paths:
                try:
                    with open(img_path, "rb") as image_file:
                        encoded_image = base64.b64encode(image_file.read()).decode('utf-8')
                        image_data.append(encoded_image)
                except Exception as e:
                    print(f"Warning: Failed to load image {img_path}: {str(e)}")

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

            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": self.model if "vision" in self.model.lower() else "grok-2-vision-1212",
                        "messages": formatted_messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens
                    }
                )
                response.raise_for_status()
                result = response.json()
                return result["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as e:
            error_detail = e.response.text if hasattr(e.response, 'text') else str(e)
            raise Exception(f"Grok vision generation failed: {str(e)}\nResponse: {error_detail}")
        except Exception as e:
            raise Exception(f"Grok vision generation failed: {str(e)}")


class LLMManager:
    """Manager for LLM providers"""

    def __init__(self):
        self.providers = {
            "ollama": OllamaProvider(),
            "groq": GroqProvider(),
            "openai": OpenAIProvider(),
            "anthropic": AnthropicProvider(),
            "grok": GrokProvider()
        }
        self.default_provider = os.getenv("DEFAULT_LLM_PROVIDER", "local")

        # Map 'local' to 'ollama'
        if self.default_provider == "local":
            self.default_provider = "ollama"

    def get_provider(self, provider_name: Optional[str] = None) -> BaseLLMProvider:
        """Get a specific LLM provider or the default one"""
        name = provider_name or self.default_provider

        # Map 'local' to 'ollama'
        if name == "local":
            name = "ollama"

        if name not in self.providers:
            raise ValueError(f"Unknown provider: {name}")

        provider = self.providers[name]

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
