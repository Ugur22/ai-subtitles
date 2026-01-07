"""
Auth router for simple password-based app protection.

Single shared password with session token management.
Password is validated against APP_PASSWORD_HASH environment variable (SHA-256).
"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
import hashlib
import secrets
import time

from config import settings
from services.supabase_service import SupabaseService


router = APIRouter(prefix="/api/auth", tags=["Auth"])

SESSION_DURATION_SECONDS = 7 * 24 * 60 * 60  # 7 days


# =============================================================================
# Pydantic Models
# =============================================================================

class LoginRequest(BaseModel):
    """Request model for login."""
    password: str


class LoginResponse(BaseModel):
    """Response model for successful login."""
    session_token: str
    expires_at: int  # Unix timestamp


class ValidateResponse(BaseModel):
    """Response model for session validation."""
    valid: bool
    expires_at: Optional[int] = None


class AuthStatusResponse(BaseModel):
    """Response model for auth status check."""
    password_protection_enabled: bool


# =============================================================================
# Helper Functions
# =============================================================================

def hash_password(password: str) -> str:
    """Hash password with SHA-256 (same method used to create APP_PASSWORD_HASH)"""
    return hashlib.sha256(password.encode()).hexdigest()


def cleanup_expired_sessions() -> int:
    """Remove expired sessions from database. Returns count of removed sessions."""
    now = int(time.time())
    try:
        client = SupabaseService.get_client()
        response = client.table("sessions").delete().lt("expires_at", now).execute()
        return len(response.data) if response.data else 0
    except Exception as e:
        print(f"Error cleaning up sessions: {e}")
        return 0


# =============================================================================
# Endpoints
# =============================================================================

@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    """
    Validate password and create session token.

    Returns session token valid for 7 days.
    """
    # Check if password protection is enabled
    if not settings.APP_PASSWORD_HASH:
        raise HTTPException(
            status_code=501,
            detail="Password protection not configured"
        )

    # Validate password
    input_hash = hash_password(request.password)
    if not secrets.compare_digest(input_hash, settings.APP_PASSWORD_HASH):
        raise HTTPException(
            status_code=401,
            detail="Invalid password"
        )

    # Create session token
    cleanup_expired_sessions()
    session_token = secrets.token_urlsafe(32)
    expires_at = int(time.time() + SESSION_DURATION_SECONDS)

    # Store session in Supabase
    try:
        client = SupabaseService.get_client()
        client.table("sessions").insert({
            "token": session_token,
            "expires_at": expires_at
        }).execute()
    except Exception as e:
        print(f"Error storing session: {e}")
        raise HTTPException(status_code=500, detail="Failed to create session")

    return LoginResponse(
        session_token=session_token,
        expires_at=expires_at
    )


@router.post("/validate", response_model=ValidateResponse)
async def validate_session(session_token: str = Query(..., description="Session token to validate")):
    """
    Validate a session token.

    Returns whether token is valid and its expiry time.
    """
    cleanup_expired_sessions()

    try:
        client = SupabaseService.get_client()
        response = client.table("sessions").select("expires_at").eq("token", session_token).execute()

        if response.data and len(response.data) > 0:
            return ValidateResponse(
                valid=True,
                expires_at=response.data[0]["expires_at"]
            )
    except Exception as e:
        print(f"Error validating session: {e}")

    return ValidateResponse(valid=False)


@router.post("/logout")
async def logout(session_token: str = Query(..., description="Session token to invalidate")):
    """Invalidate a session token."""
    try:
        client = SupabaseService.get_client()
        client.table("sessions").delete().eq("token", session_token).execute()
    except Exception as e:
        print(f"Error deleting session: {e}")
    return {"success": True}


@router.get("/status", response_model=AuthStatusResponse)
async def auth_status():
    """
    Check if password protection is enabled.

    Frontend can use this to skip the login screen if protection is disabled.
    """
    return AuthStatusResponse(
        password_protection_enabled=bool(settings.APP_PASSWORD_HASH)
    )
