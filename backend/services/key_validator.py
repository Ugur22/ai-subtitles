"""
API key validation service for async background validation.

Tests API keys against provider endpoints and updates validation status in database.
"""
import asyncio
from datetime import datetime
from typing import Tuple, Optional
import httpx
from services.supabase_service import SupabaseService
from services.encryption import get_encryption_key, decrypt_api_key


async def validate_api_key_async(user_id: str, provider: str, encrypted_key: str) -> None:
    """
    Validate API key in background and update database.

    This runs asynchronously after the key is saved. Updates the is_valid field
    and validation_error in user_api_keys table.

    Args:
        user_id: User UUID
        provider: Provider name (groq, xai, openai, anthropic)
        encrypted_key: Encrypted API key from database
    """
    try:
        # Decrypt the key
        encryption_key = await get_encryption_key()
        api_key = decrypt_api_key(encrypted_key, encryption_key)

        # Test the key
        is_valid, error = await test_provider_key(provider, api_key)

        # Update database
        client = SupabaseService.get_client()

        update_data = {
            "is_valid": is_valid,
            "validation_error": error,
            "validated_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        }

        client.table("user_api_keys").update(update_data).eq(
            "user_id", user_id
        ).eq("provider", provider).execute()

        if is_valid:
            print(f"[KeyValidator] Key validated successfully for user {user_id}, provider {provider}")
        else:
            print(f"[KeyValidator] Key validation failed for user {user_id}, provider {provider}: {error}")

    except Exception as e:
        print(f"[KeyValidator] Validation error for user {user_id}, provider {provider}: {e}")

        # Update with error
        try:
            client = SupabaseService.get_client()

            client.table("user_api_keys").update({
                "is_valid": False,
                "validation_error": f"Validation error: {str(e)}",
                "validated_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat()
            }).eq("user_id", user_id).eq("provider", provider).execute()

        except Exception as db_error:
            print(f"[KeyValidator] Failed to update error in database: {db_error}")


async def test_provider_key(provider: str, api_key: str) -> Tuple[bool, Optional[str]]:
    """
    Test if API key is valid by making a minimal API call.

    Args:
        provider: Provider name (groq, xai, openai, anthropic)
        api_key: Plain text API key to test

    Returns:
        Tuple of (is_valid, error_message)
        error_message is None if valid, otherwise contains error details
    """
    try:
        # Set a reasonable timeout for validation requests
        timeout = httpx.Timeout(30.0, connect=10.0)

        if provider == "groq":
            return await _test_groq(api_key, timeout)
        elif provider == "xai":
            return await _test_xai(api_key, timeout)
        elif provider == "openai":
            return await _test_openai(api_key, timeout)
        elif provider == "anthropic":
            return await _test_anthropic(api_key, timeout)
        else:
            return False, f"Unknown provider: {provider}"

    except Exception as e:
        return False, f"Test failed: {str(e)}"


async def _test_groq(api_key: str, timeout: httpx.Timeout) -> Tuple[bool, Optional[str]]:
    """Test Groq API key by listing models."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                "https://api.groq.com/openai/v1/models",
                headers={"Authorization": f"Bearer {api_key}"}
            )

            if response.status_code == 200:
                return True, None
            elif response.status_code == 401:
                return False, "Invalid API key"
            elif response.status_code == 403:
                return False, "API key does not have required permissions"
            else:
                return False, f"API returned status {response.status_code}"

    except httpx.TimeoutException:
        return False, "Request timed out"
    except httpx.ConnectError:
        return False, "Could not connect to Groq API"
    except Exception as e:
        return False, f"Test error: {str(e)}"


async def _test_xai(api_key: str, timeout: httpx.Timeout) -> Tuple[bool, Optional[str]]:
    """Test xAI (Grok) API key by listing models."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                "https://api.x.ai/v1/models",
                headers={"Authorization": f"Bearer {api_key}"}
            )

            if response.status_code == 200:
                return True, None
            elif response.status_code == 401:
                return False, "Invalid API key"
            elif response.status_code == 403:
                return False, "API key does not have required permissions"
            else:
                return False, f"API returned status {response.status_code}"

    except httpx.TimeoutException:
        return False, "Request timed out"
    except httpx.ConnectError:
        return False, "Could not connect to xAI API"
    except Exception as e:
        return False, f"Test error: {str(e)}"


async def _test_openai(api_key: str, timeout: httpx.Timeout) -> Tuple[bool, Optional[str]]:
    """Test OpenAI API key by listing models."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {api_key}"}
            )

            if response.status_code == 200:
                return True, None
            elif response.status_code == 401:
                return False, "Invalid API key"
            elif response.status_code == 403:
                return False, "API key does not have required permissions"
            else:
                return False, f"API returned status {response.status_code}"

    except httpx.TimeoutException:
        return False, "Request timed out"
    except httpx.ConnectError:
        return False, "Could not connect to OpenAI API"
    except Exception as e:
        return False, f"Test error: {str(e)}"


async def _test_anthropic(api_key: str, timeout: httpx.Timeout) -> Tuple[bool, Optional[str]]:
    """
    Test Anthropic API key by making a minimal messages API call.

    Note: Anthropic doesn't have a models listing endpoint, so we make a minimal
    message request. Status 200 or 400 indicates valid key (400 means request format
    issue, but key is valid).
    """
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                },
                json={
                    "model": "claude-3-haiku-20240307",
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "test"}]
                }
            )

            # Both 200 (success) and 400 (bad request format) indicate valid key
            # 401/403 indicate invalid/unauthorized key
            if response.status_code in [200, 400]:
                return True, None
            elif response.status_code == 401:
                return False, "Invalid API key"
            elif response.status_code == 403:
                return False, "API key does not have required permissions"
            else:
                return False, f"API returned status {response.status_code}"

    except httpx.TimeoutException:
        return False, "Request timed out"
    except httpx.ConnectError:
        return False, "Could not connect to Anthropic API"
    except Exception as e:
        return False, f"Test error: {str(e)}"


async def test_provider_key_sync(provider: str, api_key: str) -> Tuple[bool, Optional[str]]:
    """
    Synchronous version of test_provider_key for immediate validation.

    Used by the POST /api/keys/:provider/test endpoint.

    Args:
        provider: Provider name
        api_key: Plain text API key

    Returns:
        Tuple of (is_valid, error_message)
    """
    return await test_provider_key(provider, api_key)
