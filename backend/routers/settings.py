"""
User settings router.

Handles user profile settings and account deletion.
"""
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from middleware.auth import require_auth
from services.supabase_service import SupabaseService


router = APIRouter(prefix="/api/settings", tags=["Settings"])


# =============================================================================
# Pydantic Models
# =============================================================================

class UpdateSettingsRequest(BaseModel):
    """Request to update user settings."""
    display_name: Optional[str] = None
    default_llm_provider: Optional[str] = None


class UpdateSettingsResponse(BaseModel):
    """Response after updating settings."""
    success: bool
    message: str


class DeleteAccountResponse(BaseModel):
    """Response after deleting account."""
    success: bool
    message: str


# =============================================================================
# Endpoints
# =============================================================================

@router.patch("", response_model=UpdateSettingsResponse)
@require_auth
async def update_settings(request: Request, body: UpdateSettingsRequest):
    """
    Update user settings.

    Can update display_name and/or default_llm_provider.
    """
    try:
        user_id = request.state.user["id"]
        client = SupabaseService.get_client()

        # Build update dict (only include provided fields)
        updates = {}

        if body.display_name is not None:
            updates["display_name"] = body.display_name.strip() if body.display_name else None

        if body.default_llm_provider is not None:
            # Validate provider
            valid_providers = ["groq", "xai", "openai", "anthropic"]
            if body.default_llm_provider not in valid_providers:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid provider. Must be one of: {', '.join(valid_providers)}"
                )
            updates["default_llm_provider"] = body.default_llm_provider

        if not updates:
            return UpdateSettingsResponse(
                success=True,
                message="No changes to apply"
            )

        # Add updated_at timestamp
        updates["updated_at"] = datetime.utcnow().isoformat()

        # Update database
        client.table("user_profiles").update(updates).eq("id", user_id).execute()

        print(f"[Settings] Updated settings for user {user_id}: {list(updates.keys())}")

        return UpdateSettingsResponse(
            success=True,
            message="Settings updated successfully"
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"[Settings] Error updating settings: {e}")
        raise HTTPException(status_code=500, detail="Failed to update settings")


@router.delete("/account", response_model=DeleteAccountResponse)
@require_auth
async def delete_account(request: Request, response: Response):
    """
    Delete user account (hard delete, GDPR compliant).

    Deletes all user data including profile, API keys, jobs, usage logs.
    Cascading deletes handled by database constraints.
    """
    try:
        user_id = request.state.user["id"]
        client = SupabaseService.get_client()

        # Delete user profile (cascades to related tables)
        profile_response = client.table("user_profiles").delete().eq("id", user_id).execute()

        if not profile_response.data or len(profile_response.data) == 0:
            raise HTTPException(status_code=404, detail="User profile not found")

        # Delete from Supabase auth
        try:
            client.auth.admin.delete_user(user_id)
        except Exception as e:
            print(f"[Settings] Failed to delete auth user (non-critical): {e}")

        # Clear auth cookie
        response.delete_cookie(key="auth_token", path="/")

        print(f"[Settings] Deleted account: {user_id}")

        return DeleteAccountResponse(
            success=True,
            message="Account deleted successfully"
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"[Settings] Error deleting account: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete account")
