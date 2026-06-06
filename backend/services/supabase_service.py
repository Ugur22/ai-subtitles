"""
Supabase service for database operations
"""
from typing import Optional
from supabase import create_client, Client

from config import settings


class SupabaseService:
    """Service for Supabase database operations"""

    _client: Optional[Client] = None
    _auth_client: Optional[Client] = None

    @classmethod
    def get_client(cls) -> Client:
        """
        Get or create a Supabase client (singleton).

        Returns:
            Supabase client instance with service role key

        Raises:
            Exception: If Supabase URL or service key is not configured
        """
        if cls._client is None:
            if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_KEY:
                raise Exception(
                    "Supabase is not configured. Please set SUPABASE_URL and "
                    "SUPABASE_SERVICE_KEY in your environment variables."
                )

            cls._client = create_client(
                settings.SUPABASE_URL,
                settings.SUPABASE_SERVICE_KEY
            )
            print("[Supabase] Client initialized successfully")

        return cls._client

    @classmethod
    def get_auth_client(cls) -> Client:
        """
        Get or create a Supabase client dedicated to auth operations.

        Auth calls (sign_up / sign_in / sign_out / admin.*) mutate the client's
        internal session, which rewrites the Authorization header used by every
        .table() call on the SAME client. Keeping auth on a separate client
        ensures the shared data client (get_client) always stays on the service
        role key — otherwise a user login would poison background jobs/crons with
        an expired user JWT.

        Returns:
            Supabase client instance with service role key, used only for auth.*

        Raises:
            Exception: If Supabase URL or service key is not configured
        """
        if cls._auth_client is None:
            if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_KEY:
                raise Exception(
                    "Supabase is not configured. Please set SUPABASE_URL and "
                    "SUPABASE_SERVICE_KEY in your environment variables."
                )

            cls._auth_client = create_client(
                settings.SUPABASE_URL,
                settings.SUPABASE_SERVICE_KEY
            )
            print("[Supabase] Auth client initialized successfully")

        return cls._auth_client


# Export the client for easy import
supabase = SupabaseService.get_client
