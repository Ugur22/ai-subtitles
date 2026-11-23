"""
API Keys management router.

Handles user API keys for LLM providers (groq, xai, openai, anthropic, deepseek).
Keys are encrypted at rest using AES-256-GCM.
"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

from middleware.auth import require_auth
from services.supabase_service import SupabaseService
from services.encryption import encrypt_api_key, get_encryption_key, get_key_suffix
from services.key_validator import test_provider_key


router = APIRouter(prefix="/api/keys", tags=["API Keys"])

# Supported providers
SUPPORTED_PROVIDERS = ["groq", "xai", "openai", "anthropic", "deepseek"]


# =============================================================================
# Pydantic Models
# =============================================================================

class APIKeyInfo(BaseModel):
    """API key information (encrypted, only suffix visible)."""
    provider: str
    key_suffix: str
    is_valid: Optional[bool]  # None=pending, True=valid, False=invalid
    validation_error: Optional[str]
    validated_at: Optional[str]
    created_at: str


class AddKeyRequest(BaseModel):
    """Request to add new API key."""
    provider: str
    api_key: str


class AddKeyResponse(BaseModel):
    provider: str
    key_suffix: str
    message: str


class DeleteKeyResponse(BaseModel):
    """Response after deleting API key."""
    success: bool
    message: str


class TestKeyRequest(BaseModel):
    """Request to test API key."""
    api_key: Optional[str] = None  # If None, tests saved key


class TestKeyResponse(BaseModel):
    """Response from key test."""
    provider: str
    valid: bool
    error: Optional[str]


# =============================================================================
# Endpoints
# =============================================================================

@router.get("", response_model=List[APIKeyInfo])
@require_auth
async def list_keys(request: Request):
    """
    List user's API keys.

    Returns encrypted keys with only last 4 characters visible.
    Includes validation status for each key.
    """
    try:
        user_id = request.state.user["id"]
        client = SupabaseService.get_client()

        response = (
            client.table("user_api_keys")
            .select("provider, key_suffix, is_valid, validation_error, validated_at, created_at")
            .eq("user_id", user_id)
            .order("created_at", desc=False)
            .execute()
        )

        keys = []
        for row in response.data:
            keys.append(APIKeyInfo(
                provider=row["provider"],
                key_suffix=row["key_suffix"],
                is_valid=row.get("is_valid"),
                validation_error=row.get("validation_error"),
                validated_at=row.get("validated_at"),
                created_at=row["created_at"]
            ))

        return keys

    except Exception as e:
        print(f"[Keys] Error listing keys: {e}")
        raise HTTPException(status_code=500, detail="Failed to list API keys")


@router.post("", response_model=AddKeyResponse)
@require_auth
async def add_key(request: Request, body: AddKeyRequest):
    """
    Add or update API key for a provider.

    The key is checked against the provider first and only stored if it works.
    Rejected keys are never written, so an existing working key stays in place.

    Raises:
        400: Invalid provider, empty key, or key rejected by the provider
    """
    try:
        if body.provider not in SUPPORTED_PROVIDERS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid provider. Must be one of: {', '.join(SUPPORTED_PROVIDERS)}"
            )

        if not body.api_key or not body.api_key.strip():
            raise HTTPException(
                status_code=400,
                detail="API key cannot be empty"
            )

        is_valid, validation_error = await test_provider_key(body.provider, body.api_key)
        if not is_valid:
            raise HTTPException(
                status_code=400,
                detail=f"Key not saved: {validation_error or 'the provider rejected it'}. Check the key or use another one."
            )

        user_id = request.state.user["id"]
        client = SupabaseService.get_client()
        validated_at = datetime.utcnow().isoformat()

        encryption_key = await get_encryption_key()

        encrypted_key = encrypt_api_key(body.api_key, encryption_key)
        key_suffix = get_key_suffix(body.api_key)

        existing = (
            client.table("user_api_keys")
            .select("id")
            .eq("user_id", user_id)
            .eq("provider", body.provider)
            .execute()
        )

        key_fields = {
            "encrypted_key": encrypted_key,
            "key_suffix": key_suffix,
            "is_valid": True,
            "validation_error": None,
            "validated_at": validated_at,
        }

        if existing.data:
            client.table("user_api_keys").update(
                {**key_fields, "updated_at": validated_at}
            ).eq("user_id", user_id).eq("provider", body.provider).execute()

            print(f"[Keys] Updated key for user {user_id}, provider {body.provider}")
        else:
            client.table("user_api_keys").insert(
                {**key_fields, "user_id": user_id, "provider": body.provider}
            ).execute()

            print(f"[Keys] Added new key for user {user_id}, provider {body.provider}")

        return AddKeyResponse(
            provider=body.provider,
            key_suffix=key_suffix,
            message=f"{body.provider.upper()} API key verified and saved."
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"[Keys] Error adding key: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to save API key")


@router.delete("/{provider}", response_model=DeleteKeyResponse)
@require_auth
async def delete_key(request: Request, provider: str):
    """
    Delete API key for a provider.

    Raises:
        400: Invalid provider
        404: Key not found
    """
    try:
        # Validate provider
        if provider not in SUPPORTED_PROVIDERS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid provider. Must be one of: {', '.join(SUPPORTED_PROVIDERS)}"
            )

        user_id = request.state.user["id"]
        client = SupabaseService.get_client()

        # Delete key
        response = (
            client.table("user_api_keys")
            .delete()
            .eq("user_id", user_id)
            .eq("provider", provider)
            .execute()
        )

        if not response.data or len(response.data) == 0:
            raise HTTPException(
                status_code=404,
                detail=f"No API key found for provider: {provider}"
            )

        print(f"[Keys] Deleted key for user {user_id}, provider {provider}")

        return DeleteKeyResponse(
            success=True,
            message=f"{provider.upper()} API key deleted successfully"
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"[Keys] Error deleting key: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete API key")


@router.post("/{provider}/test", response_model=TestKeyResponse)
@require_auth
async def test_key(request: Request, provider: str, body: Optional[TestKeyRequest] = None):
    """
    Test API key immediately (sync test).

    If api_key provided in body, tests that key without saving.
    If no api_key provided, tests the saved key for this provider.

    Raises:
        400: Invalid provider or no key to test
    """
    try:
        # Validate provider
        if provider not in SUPPORTED_PROVIDERS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid provider. Must be one of: {', '.join(SUPPORTED_PROVIDERS)}"
            )

        user_id = request.state.user["id"]

        # Determine which key to test
        if body and body.api_key:
            # Test provided key (don't save)
            test_key_value = body.api_key
        else:
            # Test saved key
            client = SupabaseService.get_client()

            response = (
                client.table("user_api_keys")
                .select("encrypted_key")
                .eq("user_id", user_id)
                .eq("provider", provider)
                .single()
                .execute()
            )

            if not response.data:
                raise HTTPException(
                    status_code=404,
                    detail=f"No saved API key found for provider: {provider}"
                )

            # Decrypt saved key
            from services.encryption import decrypt_api_key
            encryption_key = await get_encryption_key()
            test_key_value = decrypt_api_key(response.data["encrypted_key"], encryption_key)

        # Test the key
        is_valid, error = await test_provider_key(provider, test_key_value)

        return TestKeyResponse(
            provider=provider,
            valid=is_valid,
            error=error
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"[Keys] Error testing key: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to test API key")
