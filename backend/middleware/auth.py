"""
Authentication middleware for FastAPI with Supabase Auth integration.

Provides decorators for protecting routes with authentication and admin checks.
Implements token verification caching (5 min TTL) for performance.
Uses ThreadPoolExecutor to prevent blocking the event loop during GPU processing.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import wraps
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from fastapi import Request, HTTPException, Response
from services.supabase_service import SupabaseService

# Executor for non-blocking auth database operations
# This prevents Supabase calls from blocking the event loop during heavy GPU processing
_auth_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="auth_db")

# Token verification cache (5 min TTL)
# Format: {token: {"user": {...}, "profile": {...}, "expires": datetime}}
_token_cache: Dict[str, Dict[str, Any]] = {}


def _get_token_from_request(request: Request) -> Optional[str]:
    """
    Extract auth token from HttpOnly cookie.

    Args:
        request: FastAPI request object

    Returns:
        Token string or None if not found
    """
    return request.cookies.get("auth_token")


def _cache_token_verification(token: str, user: Dict, profile: Dict) -> None:
    """
    Cache token verification result for 5 minutes.

    Args:
        token: Authentication token
        user: User data from Supabase auth.users
        profile: User profile data from user_profiles table
    """
    _token_cache[token] = {
        "user": user,
        "profile": profile,
        "expires": datetime.utcnow() + timedelta(minutes=5)
    }


def _get_cached_verification(token: str) -> Optional[Dict]:
    """
    Get cached token verification if not expired.

    Args:
        token: Authentication token

    Returns:
        Cached data dict or None if expired/not found
    """
    cached = _token_cache.get(token)
    if cached and cached["expires"] > datetime.utcnow():
        return cached

    # Clean up expired entry
    if cached:
        del _token_cache[token]

    return None


def _verify_supabase_token(token: str) -> Optional[Dict]:
    """
    Verify token with Supabase Auth and get user data.

    Args:
        token: JWT token from cookie

    Returns:
        User data dict or None if invalid
    """
    try:
        client = SupabaseService.get_client()

        # Verify JWT and get user
        response = client.auth.get_user(token)

        if response and response.user:
            return {
                "id": response.user.id,
                "email": response.user.email,
                "email_confirmed_at": response.user.email_confirmed_at,
                "created_at": response.user.created_at
            }

        return None

    except Exception as e:
        print(f"[Auth] Token verification failed: {e}")
        return None


def _get_user_profile(user_id: str) -> Optional[Dict]:
    """
    Get user profile from user_profiles table.

    Args:
        user_id: User UUID

    Returns:
        Profile data dict or None if not found
    """
    try:
        client = SupabaseService.get_client()

        response = client.table("user_profiles").select("*").eq("id", user_id).single().execute()

        if response.data:
            return response.data

        return None

    except Exception as e:
        print(f"[Auth] Failed to get user profile: {e}")
        return None


async def _verify_supabase_token_async(token: str) -> Optional[Dict]:
    """
    Non-blocking token verification using executor.

    Args:
        token: JWT token from cookie

    Returns:
        User data dict or None if invalid
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_auth_executor, _verify_supabase_token, token)


async def _get_user_profile_async(user_id: str) -> Optional[Dict]:
    """
    Non-blocking profile fetch using executor.

    Args:
        user_id: User UUID

    Returns:
        Profile data dict or None if not found
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_auth_executor, _get_user_profile, user_id)


def require_auth(func):
    """
    Decorator to require authentication for an endpoint.

    Checks HttpOnly cookie, verifies with Supabase, caches result for 5 min.
    Adds request.state.user and request.state.profile to the request.

    Usage:
        @router.get("/protected")
        @require_auth
        async def protected_endpoint(request: Request):
            user_id = request.state.user["id"]
            return {"message": f"Hello {user_id}"}

    Raises:
        HTTPException 401: If not authenticated or email not verified
    """
    @wraps(func)
    async def wrapper(request: Request, *args, **kwargs):
        # Get token from cookie
        token = _get_token_from_request(request)

        if not token:
            raise HTTPException(
                status_code=401,
                detail="Authentication required"
            )

        # Check cache first
        cached = _get_cached_verification(token)
        if cached:
            request.state.user = cached["user"]
            request.state.profile = cached["profile"]
            return await func(request, *args, **kwargs)

        # Verify with Supabase (non-blocking)
        user = await _verify_supabase_token_async(token)
        if not user:
            raise HTTPException(
                status_code=401,
                detail="Invalid or expired token"
            )

        # Check email verification
        if not user.get("email_confirmed_at"):
            raise HTTPException(
                status_code=403,
                detail="Email not verified. Please verify your email to continue."
            )

        # Get user profile (non-blocking)
        profile = await _get_user_profile_async(user["id"])
        if not profile:
            raise HTTPException(
                status_code=403,
                detail="User profile not found"
            )

        # Check if email verified in profile as well
        if not profile.get("email_verified", False):
            raise HTTPException(
                status_code=403,
                detail="Email not verified. Please verify your email to continue."
            )

        # Cache result
        _cache_token_verification(token, user, profile)

        # Attach to request
        request.state.user = user
        request.state.profile = profile

        return await func(request, *args, **kwargs)

    return wrapper


def require_admin(func):
    """
    Decorator to require admin authentication for an endpoint.

    Combines require_auth with admin check from user_profiles.is_admin.

    Usage:
        @router.delete("/admin/users/{user_id}")
        @require_admin
        async def delete_user(request: Request, user_id: str):
            return {"message": f"Deleted user {user_id}"}

    Raises:
        HTTPException 401: If not authenticated
        HTTPException 403: If not admin or email not verified
    """
    @wraps(func)
    @require_auth
    async def wrapper(request: Request, *args, **kwargs):
        # Check admin status from profile
        profile = request.state.profile

        if not profile.get("is_admin", False):
            raise HTTPException(
                status_code=403,
                detail="Admin access required"
            )

        return await func(request, *args, **kwargs)

    return wrapper


def clear_token_cache(token: str) -> None:
    """
    Clear a specific token from the verification cache.

    Useful for logout or when user data changes.

    Args:
        token: Token to remove from cache
    """
    if token in _token_cache:
        del _token_cache[token]


def clear_all_token_cache() -> None:
    """Clear entire token verification cache."""
    _token_cache.clear()
