"""
LLM Provider Abstraction Layer
Supports multiple LLM providers: Ollama (local), Groq, OpenAI, Anthropic
"""

import os
import httpx
from abc import ABC, abstractmethod
from typing import Dict, List, Optional
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


class LLMManager:
    """Manager for LLM providers"""

    def __init__(self):
        self.providers = {
            "ollama": OllamaProvider(),
            "groq": GroqProvider(),
            "openai": OpenAIProvider(),
            "anthropic": AnthropicProvider()
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
