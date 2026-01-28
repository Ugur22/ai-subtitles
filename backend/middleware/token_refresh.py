"""
Token Refresh Middleware for automatic JWT token refresh.

This middleware intercepts responses and sets new auth cookies when tokens
have been refreshed by the require_auth decorator.
"""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class TokenRefreshMiddleware(BaseHTTPMiddleware):
    """
    Middleware to set refreshed auth tokens as cookies.

    When the require_auth decorator successfully refreshes an expired token,
    it stores the new tokens in request.state.refreshed_tokens. This middleware
    reads those tokens and sets them as HttpOnly cookies on the response.

    This separation allows the token refresh to happen in the decorator while
    cookie setting happens at the middleware level (after the response is created).
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # Process the request
        response = await call_next(request)

        # Check if tokens were refreshed during this request
        if hasattr(request.state, 'refreshed_tokens'):
            tokens = request.state.refreshed_tokens

            # Set the new access token cookie
            response.set_cookie(
                key="auth_token",
                value=tokens["access_token"],
                httponly=True,
                secure=True,
                samesite="none",
                max_age=7 * 24 * 60 * 60,  # 7 days
                path="/"
            )

            # Set the new refresh token cookie
            response.set_cookie(
                key="auth_refresh_token",
                value=tokens["refresh_token"],
                httponly=True,
                secure=True,
                samesite="none",
                max_age=7 * 24 * 60 * 60,  # 7 days
                path="/"
            )

            print(f"[TokenRefreshMiddleware] Set refreshed tokens in response cookies")

        return response
