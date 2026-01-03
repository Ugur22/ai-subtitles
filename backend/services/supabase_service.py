"""
Supabase service for database operations
"""
from typing import Optional
from supabase import create_client, Client

from config import settings


class SupabaseService:
    """Service for Supabase database operations"""

    _client: Optional[Client] = None

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


# Export the client for easy import
supabase = SupabaseService.get_client
