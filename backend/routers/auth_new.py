"""
Authentication router with Supabase Auth integration.

Handles user registration, login, email verification, password reset.
Uses HttpOnly cookies for session management (7 days).
Uses ThreadPoolExecutor to prevent blocking the event loop during GPU processing.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Callable, Any
from datetime import datetime

from fastapi import APIRouter, HTTPException, Response, Request
from pydantic import BaseModel, EmailStr

from services.supabase_service import SupabaseService


# Executor for non-blocking auth database operations
# This prevents Supabase calls from blocking the event loop during heavy GPU processing
_auth_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="auth_login")


async def _run_in_executor(func: Callable, *args, **kwargs) -> Any:
    """Run blocking function in executor to avoid blocking event loop."""
    loop = asyncio.get_event_loop()
    if kwargs:
        return await loop.run_in_executor(_auth_executor, lambda: func(*args, **kwargs))
    return await loop.run_in_executor(_auth_executor, func, *args)


from services.email import send_welcome_email
from middleware.auth import require_auth, clear_token_cache


router = APIRouter(prefix="/api/auth", tags=["Authentication"])


# =============================================================================
# Pydantic Models
# =============================================================================

class RegisterRequest(BaseModel):
    """Request model for user registration."""
    email: EmailStr
    password: str
    invite_code: str


class RegisterResponse(BaseModel):
    """Response model for registration."""
    user_id: str
    message: str


class VerifyEmailRequest(BaseModel):
    """Request model for email verification."""
    user_id: str
    code: str


class VerifyEmailResponse(BaseModel):
    """Response model for email verification."""
    success: bool
    message: str


class LoginRequest(BaseModel):
    """Request model for login."""
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    """Response model for login."""
    success: bool
    message: str


class ForgotPasswordRequest(BaseModel):
    """Request model for password reset."""
    email: EmailStr


class ForgotPasswordResponse(BaseModel):
    """Response model for forgot password."""
    message: str


class ResetPasswordRequest(BaseModel):
    """Request model for password reset with code."""
    email: EmailStr
    code: str
    new_password: str


class ResetPasswordResponse(BaseModel):
    """Response model for password reset."""
    success: bool
    message: str


class UserProfileResponse(BaseModel):
    """Response model for user profile."""
    user_id: str
    email: str
    display_name: Optional[str]
    default_llm_provider: str
    visual_search_terms: Optional[str] = None
    visual_search_phrases: Optional[str] = None
    is_admin: bool
    email_verified: bool
    created_at: str


class LogoutResponse(BaseModel):
    """Response model for logout."""
    success: bool
    message: str


class ResendVerificationRequest(BaseModel):
    """Request model for resending verification code."""
    email: EmailStr


class ResendVerificationResponse(BaseModel):
    """Response model for resend verification."""
    message: str


# =============================================================================
# Helper Functions
# =============================================================================

def _verify_invite_code(code: str) -> bool:
    """
    Verify invite code is valid and unused.

    Args:
        code: UUID invite code

    Returns:
        True if valid and unused, False otherwise
    """
    try:
        client = SupabaseService.get_client()

        response = (
            client.table("invite_codes")
            .select("*")
            .eq("code", code)
            .is_("used_by", "null")
            .execute()
        )

        return response.data and len(response.data) > 0

    except Exception as e:
        print(f"[Auth] Error verifying invite code: {e}")
        return False


def _mark_invite_used(code: str, user_id: str) -> None:
    """
    Mark invite code as used by a user.

    Args:
        code: UUID invite code
        user_id: User UUID who used the code
    """
    try:
        client = SupabaseService.get_client()

        client.table("invite_codes").update({
            "used_by": user_id,
            "used_at": datetime.utcnow().isoformat()
        }).eq("code", code).execute()

    except Exception as e:
        print(f"[Auth] Error marking invite as used: {e}")


# =============================================================================
# Endpoints
# =============================================================================

@router.post("/register", response_model=RegisterResponse)
async def register(request: RegisterRequest):
    """
    Register a new user with email, password, and invite code.

    Creates Supabase auth user and user_profile entry.
    Sends verification email with 6-digit code.

    Raises:
        400: Invalid invite code, weak password, or duplicate email
    """
    try:
        # Verify invite code
        if not _verify_invite_code(request.invite_code):
            raise HTTPException(
                status_code=400,
                detail="Invalid or already used invite code"
            )

        # Validate password strength
        if len(request.password) < 8:
            raise HTTPException(
                status_code=400,
                detail="Password must be at least 8 characters"
            )

        client = SupabaseService.get_client()

        # Pre-check: reject if a profile already exists for this email so we
        # return a clear 400 instead of failing later with a duplicate-key 500.
        existing = (
            client.table("user_profiles")
            .select("id")
            .eq("email", request.email)
            .execute()
        )
        if existing.data and len(existing.data) > 0:
            raise HTTPException(
                status_code=400,
                detail="An account with this email already exists."
            )

        # Create Supabase auth user (on the dedicated auth client so the data
        # client's session/headers are never mutated by sign_up)
        auth_client = SupabaseService.get_auth_client()
        try:
            auth_response = auth_client.auth.sign_up({
                "email": request.email,
                "password": request.password,
                "options": {
                    "email_redirect_to": None,  # We handle verification ourselves
                    "data": {
                        "email_verified": False
                    }
                }
            })

            if not auth_response.user:
                raise HTTPException(
                    status_code=400,
                    detail="Registration failed. Email may already be in use."
                )

            user_id = auth_response.user.id

        except HTTPException:
            raise
        except Exception as e:
            error_msg = str(e).lower()
            if "already registered" in error_msg or "already exists" in error_msg:
                # Generic error for privacy (don't reveal if email exists)
                raise HTTPException(
                    status_code=400,
                    detail="An account with this email already exists."
                )
            raise HTTPException(
                status_code=400,
                detail=f"Registration failed: {str(e)}"
            )

        # Create user profile
        try:
            client.table("user_profiles").insert({
                "id": user_id,
                "email": request.email,
                "display_name": None,
                "default_llm_provider": "groq",
                "email_verified": False,
                "is_admin": False
            }).execute()

        except Exception as e:
            # Rollback: delete the auth user so we don't leave an orphan that
            # blocks every future registration attempt for this email.
            try:
                auth_client.auth.admin.delete_user(user_id)
                print(f"[Auth] Rolled back orphaned auth user {user_id} after profile insert failed: {e}")
            except Exception as rollback_error:
                print(f"[Auth] Failed to create profile AND failed to roll back auth user {user_id}: {e} / rollback: {rollback_error}")

            # A duplicate-key conflict means the email is already taken -> 400, not 500.
            error_msg = str(e).lower()
            if "duplicate" in error_msg or "already exists" in error_msg or "409" in error_msg or "conflict" in error_msg:
                raise HTTPException(
                    status_code=400,
                    detail="An account with this email already exists."
                )

            raise HTTPException(
                status_code=500,
                detail="Failed to create user profile"
            )

        # Mark invite code as used
        _mark_invite_used(request.invite_code, user_id)

        # The verification email (6-digit OTP) is sent by Supabase as part of
        # sign_up above, because "Confirm email" is enabled on the project and
        # the "Confirm signup" template uses {{ .Token }}. We verify it later
        # via auth.verify_otp in /verify-email.

        print(f"[Auth] User registered successfully: {user_id}")

        return RegisterResponse(
            user_id=user_id,
            message="Registration successful. Please check your email for verification code."
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"[Auth] Registration error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail="Registration failed. Please try again."
        )


@router.post("/verify-email", response_model=VerifyEmailResponse)
async def verify_email(request: VerifyEmailRequest, response: Response):
    """
    Verify email with the 6-digit OTP that Supabase emailed at sign-up.

    Confirms the Supabase auth user via auth.verify_otp (type="signup"),
    marks the profile verified, and sets HttpOnly session cookies so the
    user lands logged in.

    Raises:
        400: Invalid or expired code
        404: User not found
    """
    try:
        client = SupabaseService.get_client()

        # The frontend sends user_id; Supabase OTP verification needs the email.
        user_response = (
            client.table("user_profiles")
            .select("email")
            .eq("id", request.user_id)
            .single()
            .execute()
        )

        if not user_response.data:
            raise HTTPException(status_code=404, detail="User not found")

        email = user_response.data["email"]

        # Verify the OTP against Supabase (confirms the auth user + returns a session).
        try:
            otp_response = SupabaseService.get_auth_client().auth.verify_otp({
                "email": email,
                "token": request.code,
                "type": "signup"
            })
        except Exception as e:
            print(f"[Auth] verify_otp failed for {request.user_id}: {e}")
            raise HTTPException(
                status_code=400,
                detail="Invalid or expired verification code"
            )

        if not otp_response or not otp_response.user:
            raise HTTPException(
                status_code=400,
                detail="Invalid or expired verification code"
            )

        # Mark the profile verified (login checks user_profiles.email_verified).
        client.table("user_profiles").update({
            "email_verified": True,
            "updated_at": datetime.utcnow().isoformat()
        }).eq("id", request.user_id).execute()

        # Set session cookies from the OTP session so the user is logged in
        # immediately (mirrors the cookie handling in /login).
        session = otp_response.session
        if session and session.access_token:
            response.set_cookie(
                key="auth_token",
                value=session.access_token,
                httponly=True,
                secure=True,
                samesite="none",
                max_age=7 * 24 * 60 * 60,
                path="/"
            )
            if session.refresh_token:
                response.set_cookie(
                    key="auth_refresh_token",
                    value=session.refresh_token,
                    httponly=True,
                    secure=True,
                    samesite="none",
                    max_age=7 * 24 * 60 * 60,
                    path="/"
                )

        # Send welcome email
        await send_welcome_email(email)

        print(f"[Auth] Email verified successfully for user: {request.user_id}")

        return VerifyEmailResponse(
            success=True,
            message="Email verified successfully."
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"[Auth] Email verification error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail="Email verification failed"
        )


@router.post("/resend-verification", response_model=ResendVerificationResponse)
async def resend_verification(request: ResendVerificationRequest):
    """
    Resend the email verification OTP via Supabase.

    Always returns success for security (don't reveal if email exists).

    Security:
        - Generic response to prevent email enumeration
        - Only resends if account exists AND email_verified is false
    """
    try:
        client = SupabaseService.get_client()

        # Check if email exists and is unverified (but don't reveal this in response)
        response_data = (
            client.table("user_profiles")
            .select("id, email, email_verified")
            .eq("email", request.email)
            .execute()
        )

        if response_data.data and len(response_data.data) > 0:
            profile = response_data.data[0]
            email_verified = profile.get("email_verified", False)

            # Only send if email is not verified
            if not email_verified:
                # Ask Supabase to resend the signup confirmation OTP email
                SupabaseService.get_auth_client().auth.resend({
                    "type": "signup",
                    "email": request.email
                })

                print(f"[Auth] Verification code resent to {request.email}")
            else:
                # Already verified - but don't reveal this
                print(f"[Auth] Resend verification requested for already verified email: {request.email}")
        else:
            # Email doesn't exist - but don't reveal this
            print(f"[Auth] Resend verification requested for non-existent email: {request.email}")

        # Always return success message for security
        return ResendVerificationResponse(
            message="If account exists and is unverified, code has been sent"
        )

    except Exception as e:
        print(f"[Auth] Resend verification error: {e}")
        import traceback
        traceback.print_exc()
        # Still return success for security
        return ResendVerificationResponse(
            message="If account exists and is unverified, code has been sent"
        )


def _sign_in_with_password(email: str, password: str):
    """Blocking sign in - runs in executor.

    Uses the dedicated auth client so the sign-in session never poisons the
    shared data client (which background jobs/crons rely on for service-role
    access).
    """
    client = SupabaseService.get_auth_client()
    return client.auth.sign_in_with_password({
        "email": email,
        "password": password
    })


def _check_email_verified(user_id: str):
    """Blocking profile check - runs in executor."""
    client = SupabaseService.get_client()
    response = (
        client.table("user_profiles")
        .select("email_verified")
        .eq("id", user_id)
        .limit(1)
        .execute()
    )
    if response.data and len(response.data) > 0:
        return response.data[0]
    return None


def _log_login_event(user_id: str, email: str):
    """Blocking usage log - runs in executor."""
    client = SupabaseService.get_client()
    client.table("usage_logs").insert({
        "user_id": user_id,
        "action": "login",
        "metadata": {"email": email}
    }).execute()


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest, response: Response):
    """
    Login with email and password.

    Sets HttpOnly cookie with auth token (7 days).
    Uses executor to prevent blocking event loop during GPU processing.

    Raises:
        401: Invalid credentials or email not verified
    """
    try:
        # Attempt sign in with Supabase (non-blocking)
        try:
            auth_response = await _run_in_executor(
                _sign_in_with_password,
                request.email,
                request.password
            )

            if not auth_response.user or not auth_response.session:
                raise HTTPException(
                    status_code=401,
                    detail="Invalid credentials"
                )

            user_id = auth_response.user.id
            access_token = auth_response.session.access_token
            refresh_token = auth_response.session.refresh_token

        except HTTPException:
            raise
        except Exception as e:
            # Generic error for security (don't reveal if email exists)
            print(f"[Auth] Login failed for {request.email}: {e}")
            raise HTTPException(
                status_code=401,
                detail="Invalid credentials"
            )

        # Check if email verified (non-blocking)
        profile = await _run_in_executor(_check_email_verified, user_id)

        if not profile or not profile.get("email_verified", False):
            raise HTTPException(
                status_code=403,
                detail="Email not verified. Please check your email for verification code."
            )

        # Set HttpOnly cookie for access token (7 days)
        # samesite="none" required for cross-origin (frontend on different domain)
        response.set_cookie(
            key="auth_token",
            value=access_token,
            httponly=True,
            secure=True,  # HTTPS only in production
            samesite="none",  # Required for cross-origin cookies
            max_age=7 * 24 * 60 * 60,  # 7 days
            path="/"
        )

        # Set HttpOnly cookie for refresh token (7 days)
        # Used to automatically refresh expired access tokens
        response.set_cookie(
            key="auth_refresh_token",
            value=refresh_token,
            httponly=True,
            secure=True,
            samesite="none",
            max_age=7 * 24 * 60 * 60,  # 7 days
            path="/"
        )

        # Log login event (non-blocking, fire and forget)
        try:
            await _run_in_executor(_log_login_event, user_id, request.email)
        except Exception as e:
            print(f"[Auth] Failed to log login event: {e}")

        print(f"[Auth] User logged in successfully: {user_id}")

        return LoginResponse(
            success=True,
            message="Login successful"
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"[Auth] Login error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail="Login failed"
        )


@router.post("/logout", response_model=LogoutResponse)
async def logout(request: Request, response: Response):
    """
    Logout user and clear session cookie.

    Clears HttpOnly cookie and invalidates cache.
    """
    try:
        # Get token to clear from cache
        token = request.cookies.get("auth_token")

        if token:
            # Clear from cache
            clear_token_cache(token)

            # Sign out from Supabase (on the auth client, not the data client)
            try:
                client = SupabaseService.get_auth_client()
                client.auth.sign_out()
            except Exception as e:
                print(f"[Auth] Error signing out from Supabase: {e}")

        # Clear both auth cookies
        response.delete_cookie(
            key="auth_token",
            path="/"
        )
        response.delete_cookie(
            key="auth_refresh_token",
            path="/"
        )

        return LogoutResponse(
            success=True,
            message="Logout successful"
        )

    except Exception as e:
        print(f"[Auth] Logout error: {e}")
        # Don't fail logout even if there's an error - clear both cookies
        response.delete_cookie(key="auth_token", path="/")
        response.delete_cookie(key="auth_refresh_token", path="/")

        return LogoutResponse(
            success=True,
            message="Logout successful"
        )


@router.post("/forgot-password", response_model=ForgotPasswordResponse)
async def forgot_password(request: ForgotPasswordRequest):
    """
    Request password reset code.

    Sends a 6-digit recovery OTP via Supabase if the account exists.
    Always returns success for security (don't reveal if email exists).
    """
    try:
        client = SupabaseService.get_client()

        # Check if email exists (but don't reveal this in response)
        response = (
            client.table("user_profiles")
            .select("id, email")
            .eq("email", request.email)
            .execute()
        )

        if response.data and len(response.data) > 0:
            # Email exists - ask Supabase to email a recovery OTP
            SupabaseService.get_auth_client().auth.reset_password_for_email(request.email)

            print(f"[Auth] Password reset code sent to {request.email}")
        else:
            # Email doesn't exist - but don't reveal this
            print(f"[Auth] Password reset requested for non-existent email: {request.email}")

        # Always return success message for security
        return ForgotPasswordResponse(
            message="If an account exists with this email, a reset code has been sent."
        )

    except Exception as e:
        print(f"[Auth] Forgot password error: {e}")
        # Still return success for security
        return ForgotPasswordResponse(
            message="If an account exists with this email, a reset code has been sent."
        )


@router.post("/reset-password", response_model=ResetPasswordResponse)
async def reset_password(request: ResetPasswordRequest):
    """
    Reset password with the recovery OTP that Supabase emailed.

    Verifies the OTP (type="recovery") and updates the password on the
    resulting session.

    Raises:
        400: Invalid code, expired code, or weak password
    """
    try:
        # Validate new password
        if len(request.new_password) < 8:
            raise HTTPException(
                status_code=400,
                detail="Password must be at least 8 characters"
            )

        auth_client = SupabaseService.get_auth_client()

        # Verify the recovery OTP - this establishes a session for the user.
        try:
            otp_response = auth_client.auth.verify_otp({
                "email": request.email,
                "token": request.code,
                "type": "recovery"
            })
        except Exception as e:
            print(f"[Auth] Recovery verify_otp failed for {request.email}: {e}")
            raise HTTPException(
                status_code=400,
                detail="Invalid or expired reset code"
            )

        if not otp_response or not otp_response.user:
            raise HTTPException(
                status_code=400,
                detail="Invalid or expired reset code"
            )

        # Update the password for the now-authenticated (recovery) session.
        try:
            auth_client.auth.update_user({"password": request.new_password})
            print(f"[Auth] Password reset successfully for user: {otp_response.user.id}")
        except Exception as e:
            print(f"[Auth] Failed to update password: {e}")
            raise HTTPException(
                status_code=500,
                detail="Failed to reset password. Please try again."
            )
        finally:
            # Clean up the recovery session so it doesn't linger on the auth client.
            try:
                auth_client.auth.sign_out()
            except Exception:
                pass

        return ResetPasswordResponse(
            success=True,
            message="Password reset successful. You can now log in with your new password."
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"[Auth] Reset password error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail="Password reset failed"
        )


@router.get("/me", response_model=UserProfileResponse)
@require_auth
async def get_current_user(request: Request):
    """
    Get current user profile.

    Requires authentication (HttpOnly cookie).

    Returns:
        User profile with ID, email, display_name, settings, etc.
    """
    try:
        user = request.state.user
        profile = request.state.profile

        return UserProfileResponse(
            user_id=user["id"],
            email=user["email"],
            display_name=profile.get("display_name"),
            default_llm_provider=profile.get("default_llm_provider", "groq"),
            visual_search_terms=profile.get("visual_search_terms") or "",
            visual_search_phrases=profile.get("visual_search_phrases") or "",
            is_admin=profile.get("is_admin", False),
            email_verified=profile.get("email_verified", False),
            created_at=profile.get("created_at", "")
        )

    except Exception as e:
        print(f"[Auth] Get current user error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to get user profile"
        )
