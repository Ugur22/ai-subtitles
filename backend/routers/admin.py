"""
Admin dashboard router.

Requires admin authentication. Handles user management, invite codes, and stats.
"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import uuid

from middleware.auth import require_admin
from services.supabase_service import SupabaseService


router = APIRouter(prefix="/api/admin", tags=["Admin"])


# =============================================================================
# Pydantic Models
# =============================================================================

class UserInfo(BaseModel):
    """User information for admin list."""
    id: str
    email: str
    display_name: Optional[str]
    created_at: str
    last_login: Optional[str]
    upload_count: int
    has_groq: bool
    has_xai: bool
    has_openai: bool
    has_anthropic: bool
    is_admin: bool


class InviteCodeInfo(BaseModel):
    """Invite code information."""
    code: str
    created_at: str
    created_by: Optional[str]
    used_by: Optional[str]
    used_at: Optional[str]


class CreateInviteResponse(BaseModel):
    """Response after creating invite code."""
    code: str
    message: str


class DeleteResponse(BaseModel):
    """Generic delete response."""
    success: bool
    message: str


class StatsResponse(BaseModel):
    """Admin stats dashboard."""
    total_users: int
    active_today: int
    uploads_today: int
    chat_messages_today: int


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/users", response_model=List[UserInfo])
@require_admin
async def list_users(request: Request):
    """List all users with stats."""
    try:
        client = SupabaseService.get_client()

        # Get users
        users_response = client.table("user_profiles").select("*").execute()

        user_list = []
        for user in users_response.data:
            user_id = user["id"]

            # Get API key status
            keys_response = client.table("user_api_keys").select("provider").eq("user_id", user_id).execute()
            providers = {k["provider"] for k in keys_response.data}

            # Get upload count
            upload_response = client.table("usage_logs").select("id", count="exact").eq("user_id", user_id).eq("action", "upload").execute()
            upload_count = upload_response.count or 0

            # Get last login
            login_response = client.table("usage_logs").select("created_at").eq("user_id", user_id).eq("action", "login").order("created_at", desc=True).limit(1).execute()
            last_login = login_response.data[0]["created_at"] if login_response.data else None

            user_list.append(UserInfo(
                id=user_id,
                email=user["email"],
                display_name=user.get("display_name"),
                created_at=user["created_at"],
                last_login=last_login,
                upload_count=upload_count,
                has_groq="groq" in providers,
                has_xai="xai" in providers,
                has_openai="openai" in providers,
                has_anthropic="anthropic" in providers,
                is_admin=user.get("is_admin", False)
            ))

        return user_list

    except Exception as e:
        print(f"[Admin] Error listing users: {e}")
        raise HTTPException(status_code=500, detail="Failed to list users")


@router.post("/invite-codes", response_model=CreateInviteResponse)
@require_admin
async def create_invite_code(request: Request):
    """Create a new invite code."""
    try:
        admin_id = request.state.user["id"]
        client = SupabaseService.get_client()

        # Generate UUID code
        code = str(uuid.uuid4())

        # Insert into database
        client.table("invite_codes").insert({
            "code": code,
            "created_by": admin_id
        }).execute()

        print(f"[Admin] Created invite code: {code}")

        return CreateInviteResponse(
            code=code,
            message="Invite code created successfully"
        )

    except Exception as e:
        print(f"[Admin] Error creating invite code: {e}")
        raise HTTPException(status_code=500, detail="Failed to create invite code")


@router.get("/invite-codes", response_model=List[InviteCodeInfo])
@require_admin
async def list_invite_codes(request: Request):
    """List all invite codes."""
    try:
        client = SupabaseService.get_client()

        response = client.table("invite_codes").select("*").order("created_at", desc=True).execute()

        codes = []
        for row in response.data:
            codes.append(InviteCodeInfo(
                code=row["code"],
                created_at=row["created_at"],
                created_by=row.get("created_by"),
                used_by=row.get("used_by"),
                used_at=row.get("used_at")
            ))

        return codes

    except Exception as e:
        print(f"[Admin] Error listing invite codes: {e}")
        raise HTTPException(status_code=500, detail="Failed to list invite codes")


@router.delete("/invite-codes/{code}", response_model=DeleteResponse)
@require_admin
async def delete_invite_code(request: Request, code: str):
    """Delete an invite code."""
    try:
        client = SupabaseService.get_client()

        response = client.table("invite_codes").delete().eq("code", code).execute()

        if not response.data or len(response.data) == 0:
            raise HTTPException(status_code=404, detail="Invite code not found")

        print(f"[Admin] Deleted invite code: {code}")

        return DeleteResponse(
            success=True,
            message="Invite code deleted successfully"
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"[Admin] Error deleting invite code: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete invite code")


@router.delete("/users/{user_id}", response_model=DeleteResponse)
@require_admin
async def delete_user(request: Request, user_id: str):
    """
    Hard delete user (GDPR compliant).

    Cascading deletes handle related data (jobs, keys, logs, etc).
    """
    try:
        # Prevent self-deletion
        if user_id == request.state.user["id"]:
            raise HTTPException(status_code=400, detail="Cannot delete your own account")

        client = SupabaseService.get_client()

        # Delete from user_profiles (cascades to other tables via FK constraints)
        response = client.table("user_profiles").delete().eq("id", user_id).execute()

        if not response.data or len(response.data) == 0:
            raise HTTPException(status_code=404, detail="User not found")

        # Also delete from Supabase auth (requires admin API)
        try:
            client.auth.admin.delete_user(user_id)
        except Exception as e:
            print(f"[Admin] Failed to delete auth user (non-critical): {e}")

        print(f"[Admin] Deleted user: {user_id}")

        return DeleteResponse(
            success=True,
            message="User deleted successfully"
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"[Admin] Error deleting user: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete user")


@router.post("/users/{user_id}/invalidate-keys", response_model=DeleteResponse)
@require_admin
async def invalidate_user_keys(request: Request, user_id: str):
    """Force user to re-enter all API keys."""
    try:
        client = SupabaseService.get_client()

        # Delete all API keys for user
        response = client.table("user_api_keys").delete().eq("user_id", user_id).execute()

        key_count = len(response.data) if response.data else 0

        print(f"[Admin] Invalidated {key_count} keys for user: {user_id}")

        return DeleteResponse(
            success=True,
            message=f"Invalidated {key_count} API key(s) for user"
        )

    except Exception as e:
        print(f"[Admin] Error invalidating keys: {e}")
        raise HTTPException(status_code=500, detail="Failed to invalidate API keys")


@router.get("/stats", response_model=StatsResponse)
@require_admin
async def get_stats(request: Request):
    """Get admin dashboard stats."""
    try:
        client = SupabaseService.get_client()
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

        # Total users
        total_response = client.table("user_profiles").select("id", count="exact").execute()
        total_users = total_response.count or 0

        # Active today (logged in today)
        active_response = client.table("usage_logs").select("user_id").eq("action", "login").gte("created_at", today).execute()
        active_today = len(set(log["user_id"] for log in active_response.data))

        # Uploads today
        uploads_response = client.table("usage_logs").select("id", count="exact").eq("action", "upload").gte("created_at", today).execute()
        uploads_today = uploads_response.count or 0

        # Chat messages today
        chat_response = client.table("usage_logs").select("id", count="exact").eq("action", "chat_message").gte("created_at", today).execute()
        chat_messages_today = chat_response.count or 0

        return StatsResponse(
            total_users=total_users,
            active_today=active_today,
            uploads_today=uploads_today,
            chat_messages_today=chat_messages_today
        )

    except Exception as e:
        print(f"[Admin] Error getting stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to get stats")
