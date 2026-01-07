"""
Authentication router with Supabase Auth integration.

Handles user registration, login, email verification, password reset.
Uses HttpOnly cookies for session management (7 days).
"""
from fastapi import APIRouter, HTTPException, Response, Request
from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime, timedelta
import secrets

from services.supabase_service import SupabaseService
from services.email import (
    generate_verification_code,
    send_verification_email,
    send_password_reset_email,
    send_welcome_email
)
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


def _store_verification_code(user_id: str, code: str) -> None:
    """
    Store email verification code in database (expires in 15 min).

    Args:
        user_id: User UUID
        code: 6-digit verification code
    """
    try:
        client = SupabaseService.get_client()

        expires_at = datetime.utcnow() + timedelta(minutes=15)

        client.table("email_verifications").insert({
            "user_id": user_id,
            "code": code,
            "expires_at": expires_at.isoformat()
        }).execute()

    except Exception as e:
        print(f"[Auth] Error storing verification code: {e}")
        raise


def _verify_email_code(user_id: str, code: str) -> bool:
    """
    Verify email verification code.

    Args:
        user_id: User UUID
        code: 6-digit verification code

    Returns:
        True if valid and not expired, False otherwise
    """
    try:
        client = SupabaseService.get_client()

        # Get most recent code for this user
        response = (
            client.table("email_verifications")
            .select("*")
            .eq("user_id", user_id)
            .eq("code", code)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )

        if not response.data or len(response.data) == 0:
            return False

        record = response.data[0]
        expires_at = datetime.fromisoformat(record["expires_at"].replace('Z', '+00:00'))

        # Check if expired
        if datetime.utcnow() > expires_at.replace(tzinfo=None):
            return False

        # Delete used code
        client.table("email_verifications").delete().eq("id", record["id"]).execute()

        return True

    except Exception as e:
        print(f"[Auth] Error verifying email code: {e}")
        return False


def _store_password_reset_code(email: str, code: str) -> None:
    """
    Store password reset code in database (expires in 15 min).

    Args:
        email: User email
        code: 6-digit reset code
    """
    try:
        client = SupabaseService.get_client()

        expires_at = datetime.utcnow() + timedelta(minutes=15)

        client.table("password_resets").insert({
            "email": email,
            "code": code,
            "expires_at": expires_at.isoformat(),
            "used": False
        }).execute()

    except Exception as e:
        print(f"[Auth] Error storing reset code: {e}")
        raise


def _verify_reset_code(email: str, code: str) -> bool:
    """
    Verify password reset code.

    Args:
        email: User email
        code: 6-digit reset code

    Returns:
        True if valid and not expired, False otherwise
    """
    try:
        client = SupabaseService.get_client()

        # Get most recent unused code for this email
        response = (
            client.table("password_resets")
            .select("*")
            .eq("email", email)
            .eq("code", code)
            .eq("used", False)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )

        if not response.data or len(response.data) == 0:
            return False

        record = response.data[0]
        expires_at = datetime.fromisoformat(record["expires_at"].replace('Z', '+00:00'))

        # Check if expired
        if datetime.utcnow() > expires_at.replace(tzinfo=None):
            return False

        # Mark as used
        client.table("password_resets").update({
            "used": True
        }).eq("id", record["id"]).execute()

        return True

    except Exception as e:
        print(f"[Auth] Error verifying reset code: {e}")
        return False


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

        # Create Supabase auth user
        try:
            auth_response = client.auth.sign_up({
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

        except Exception as e:
            error_msg = str(e).lower()
            if "already registered" in error_msg or "already exists" in error_msg:
                # Generic error for privacy (don't reveal if email exists)
                raise HTTPException(
                    status_code=400,
                    detail="Registration failed. Please try again or use a different email."
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
            # Rollback: delete auth user if profile creation fails
            try:
                # Note: Supabase doesn't expose admin delete in client SDK
                # This would need service role access
                print(f"[Auth] Failed to create profile, auth user {user_id} may be orphaned: {e}")
            except:
                pass

            raise HTTPException(
                status_code=500,
                detail="Failed to create user profile"
            )

        # Mark invite code as used
        _mark_invite_used(request.invite_code, user_id)

        # Generate and send verification code
        code = generate_verification_code()
        _store_verification_code(user_id, code)
        await send_verification_email(request.email, code)

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
    Verify email with 6-digit code.

    Sets HttpOnly cookie with auth token on success.
    Marks user as email_verified in database.

    Raises:
        400: Invalid or expired code
    """
    try:
        # Verify code
        if not _verify_email_code(request.user_id, request.code):
            raise HTTPException(
                status_code=400,
                detail="Invalid or expired verification code"
            )

        client = SupabaseService.get_client()

        # Update user profile
        client.table("user_profiles").update({
            "email_verified": True,
            "updated_at": datetime.utcnow().isoformat()
        }).eq("id", request.user_id).execute()

        # Update Supabase auth metadata
        # Note: This requires admin access or the user to be signed in
        # For now, we rely on the user_profiles.email_verified field

        # Get user to create session
        user_response = client.table("user_profiles").select("email").eq("id", request.user_id).single().execute()

        if not user_response.data:
            raise HTTPException(status_code=404, detail="User not found")

        email = user_response.data["email"]

        # Create a session token (we'll use Supabase's session)
        # Note: In production, you'd want to have the user log in after verification
        # For now, we'll create a temporary session

        # Send welcome email
        await send_welcome_email(email)

        print(f"[Auth] Email verified successfully for user: {request.user_id}")

        return VerifyEmailResponse(
            success=True,
            message="Email verified successfully. You can now log in."
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
    Resend email verification code.

    Generates a new 6-digit code and sends to email if account exists and is unverified.
    Always returns success for security (don't reveal if email exists).

    Security:
        - Generic response to prevent email enumeration
        - Only sends if account exists AND email_verified is false
        - Deletes old codes before creating new one
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
            user_id = profile["id"]
            email_verified = profile.get("email_verified", False)

            # Only send if email is not verified
            if not email_verified:
                # Delete any existing verification codes for this user
                try:
                    client.table("email_verifications").delete().eq("user_id", user_id).execute()
                except Exception as e:
                    print(f"[Auth] Error deleting old verification codes: {e}")

                # Generate and send new code
                code = generate_verification_code()
                _store_verification_code(user_id, code)
                await send_verification_email(request.email, code)

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


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest, response: Response):
    """
    Login with email and password.

    Sets HttpOnly cookie with auth token (7 days).

    Raises:
        401: Invalid credentials or email not verified
    """
    try:
        client = SupabaseService.get_client()

        # Attempt sign in with Supabase
        try:
            auth_response = client.auth.sign_in_with_password({
                "email": request.email,
                "password": request.password
            })

            if not auth_response.user or not auth_response.session:
                raise HTTPException(
                    status_code=401,
                    detail="Invalid credentials"
                )

            user_id = auth_response.user.id
            access_token = auth_response.session.access_token

        except Exception as e:
            # Generic error for security (don't reveal if email exists)
            print(f"[Auth] Login failed for {request.email}: {e}")
            raise HTTPException(
                status_code=401,
                detail="Invalid credentials"
            )

        # Check if email verified
        profile_response = client.table("user_profiles").select("email_verified").eq("id", user_id).single().execute()

        if not profile_response.data or not profile_response.data.get("email_verified", False):
            raise HTTPException(
                status_code=403,
                detail="Email not verified. Please check your email for verification code."
            )

        # Set HttpOnly cookie (7 days)
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

        # Log login event
        try:
            client.table("usage_logs").insert({
                "user_id": user_id,
                "action": "login",
                "metadata": {"email": request.email}
            }).execute()
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

            # Sign out from Supabase
            try:
                client = SupabaseService.get_client()
                client.auth.sign_out()
            except Exception as e:
                print(f"[Auth] Error signing out from Supabase: {e}")

        # Clear cookie
        response.delete_cookie(
            key="auth_token",
            path="/"
        )

        return LogoutResponse(
            success=True,
            message="Logout successful"
        )

    except Exception as e:
        print(f"[Auth] Logout error: {e}")
        # Don't fail logout even if there's an error
        response.delete_cookie(key="auth_token", path="/")

        return LogoutResponse(
            success=True,
            message="Logout successful"
        )


@router.post("/forgot-password", response_model=ForgotPasswordResponse)
async def forgot_password(request: ForgotPasswordRequest):
    """
    Request password reset code.

    Sends 6-digit code to email if account exists.
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
            # Email exists - send reset code
            code = generate_verification_code()
            _store_password_reset_code(request.email, code)
            await send_password_reset_email(request.email, code)

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
    Reset password with verification code.

    Validates code and updates password in Supabase Auth.

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

        # Verify reset code
        if not _verify_reset_code(request.email, request.code):
            raise HTTPException(
                status_code=400,
                detail="Invalid or expired reset code"
            )

        client = SupabaseService.get_client()

        # Get user ID from email
        profile_response = (
            client.table("user_profiles")
            .select("id")
            .eq("email", request.email)
            .single()
            .execute()
        )

        if not profile_response.data:
            raise HTTPException(
                status_code=404,
                detail="User not found"
            )

        user_id = profile_response.data["id"]

        # Update password in Supabase Auth
        # Note: This requires admin/service role access
        try:
            # Using the admin API
            client.auth.admin.update_user_by_id(
                user_id,
                {"password": request.new_password}
            )

            print(f"[Auth] Password reset successfully for user: {user_id}")

            return ResetPasswordResponse(
                success=True,
                message="Password reset successful. You can now log in with your new password."
            )

        except Exception as e:
            print(f"[Auth] Failed to update password: {e}")
            raise HTTPException(
                status_code=500,
                detail="Failed to reset password. Please try again."
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
