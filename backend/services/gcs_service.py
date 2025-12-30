"""
GCS (Google Cloud Storage) service for handling large file uploads.

This service enables direct-to-GCS uploads which bypass Cloud Run's 32MB request limit.
"""
import os
import tempfile
from datetime import timedelta
from typing import Optional, Tuple
from google.cloud import storage
from google.cloud.storage import Blob
from google.auth import default
from google.auth.transport import requests as auth_requests

from config import settings


class GCSService:
    """Service for Google Cloud Storage operations."""

    _client: Optional[storage.Client] = None
    _bucket: Optional[storage.Bucket] = None
    _credentials = None
    _service_account_email: Optional[str] = None

    @classmethod
    def _get_credentials(cls):
        """Get credentials and service account email for IAM signing."""
        if cls._credentials is None:
            cls._credentials, project = default()

            # Get service account email - always fetch from metadata server on Cloud Run
            # because compute_engine.Credentials.service_account_email returns "default"
            cls._service_account_email = None

            # First try metadata server (works on Cloud Run)
            try:
                import requests
                response = requests.get(
                    "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/email",
                    headers={"Metadata-Flavor": "Google"},
                    timeout=5
                )
                if response.status_code == 200 and "@" in response.text:
                    cls._service_account_email = response.text.strip()
                    print(f"[GCS] Got service account email from metadata: {cls._service_account_email}")
            except Exception as e:
                print(f"[GCS] Metadata server not available: {e}")

            # Fall back to credentials attribute (works with service account key files)
            if cls._service_account_email is None:
                if hasattr(cls._credentials, 'service_account_email'):
                    email = cls._credentials.service_account_email
                    if email and "@" in email:
                        cls._service_account_email = email
                        print(f"[GCS] Got service account email from credentials: {email}")

            if cls._service_account_email is None:
                print("[GCS] WARNING: Could not determine service account email!")

        # Refresh credentials if needed
        if not cls._credentials.valid:
            cls._credentials.refresh(auth_requests.Request())

        return cls._credentials

    @classmethod
    def _get_client(cls) -> storage.Client:
        """Get or create a GCS client (singleton)."""
        if cls._client is None:
            credentials = cls._get_credentials()
            cls._client = storage.Client(credentials=credentials)
        return cls._client

    @classmethod
    def _get_bucket(cls) -> storage.Bucket:
        """Get or create a bucket reference (singleton)."""
        if cls._bucket is None:
            client = cls._get_client()
            cls._bucket = client.bucket(settings.GCS_BUCKET_NAME)
        return cls._bucket

    @classmethod
    def generate_upload_signed_url(
        cls,
        filename: str,
        content_type: str = "video/mp4",
        expiry_seconds: Optional[int] = None
    ) -> Tuple[str, str]:
        """
        Generate a signed URL for direct upload to GCS.

        Use this for files < 100MB. For larger files, use resumable upload.
        Uses IAM signBlob API for Cloud Run compatibility (no private key needed).

        Args:
            filename: Original filename (will be sanitized)
            content_type: MIME type of the file
            expiry_seconds: URL expiry time (default from settings)

        Returns:
            Tuple of (signed_url, gcs_path)
        """
        import uuid

        # Get credentials for IAM signing
        credentials = cls._get_credentials()
        bucket = cls._get_bucket()
        expiry = expiry_seconds or settings.GCS_SIGNED_URL_EXPIRY

        # Generate unique path: uploads/{uuid}_{filename}
        safe_filename = filename.replace(" ", "_").replace("/", "_")
        gcs_path = f"{settings.GCS_UPLOAD_PREFIX}{uuid.uuid4()}_{safe_filename}"

        blob = bucket.blob(gcs_path)

        # Generate signed URL using IAM signBlob (works on Cloud Run)
        signed_url = blob.generate_signed_url(
            version="v4",
            expiration=timedelta(seconds=expiry),
            method="PUT",
            content_type=content_type,
            service_account_email=cls._service_account_email,
            access_token=credentials.token,
        )

        print(f"[GCS] Generated signed URL for upload: {gcs_path}")
        return signed_url, gcs_path

    @classmethod
    def generate_resumable_upload_url(
        cls,
        filename: str,
        content_type: str = "video/mp4",
        expiry_seconds: Optional[int] = None
    ) -> Tuple[str, str]:
        """
        Generate a resumable upload URL for large files (>100MB).

        Resumable uploads support:
        - Pause and resume
        - Automatic retry on network failures
        - Progress tracking
        Uses IAM signBlob API for Cloud Run compatibility.

        Args:
            filename: Original filename
            content_type: MIME type of the file
            expiry_seconds: Session expiry time

        Returns:
            Tuple of (resumable_upload_url, gcs_path)
        """
        import uuid

        # Get credentials for IAM signing
        credentials = cls._get_credentials()
        bucket = cls._get_bucket()
        expiry = expiry_seconds or settings.GCS_SIGNED_URL_EXPIRY

        # Generate unique path
        safe_filename = filename.replace(" ", "_").replace("/", "_")
        gcs_path = f"{settings.GCS_UPLOAD_PREFIX}{uuid.uuid4()}_{safe_filename}"

        blob = bucket.blob(gcs_path)

        # Generate signed URL that initiates a resumable upload (using IAM signing)
        signed_url = blob.generate_signed_url(
            version="v4",
            expiration=timedelta(seconds=expiry),
            method="POST",
            headers={"x-goog-resumable": "start"},
            content_type=content_type,
            service_account_email=cls._service_account_email,
            access_token=credentials.token,
        )

        print(f"[GCS] Generated resumable upload URL for: {gcs_path}")
        return signed_url, gcs_path

    @classmethod
    def file_exists(cls, gcs_path: str) -> bool:
        """Check if a file exists in GCS."""
        bucket = cls._get_bucket()
        blob = bucket.blob(gcs_path)
        return blob.exists()

    @classmethod
    def get_file_size(cls, gcs_path: str) -> int:
        """Get the size of a file in GCS (bytes)."""
        bucket = cls._get_bucket()
        blob = bucket.blob(gcs_path)
        blob.reload()
        return blob.size or 0

    @classmethod
    def download_to_temp(cls, gcs_path: str, suffix: str = "") -> str:
        """
        Download a file from GCS to a temporary local file.

        Args:
            gcs_path: Path in GCS (e.g., "uploads/uuid_video.mp4")
            suffix: File suffix for temp file (e.g., ".mp4")

        Returns:
            Path to the downloaded temporary file
        """
        bucket = cls._get_bucket()
        blob = bucket.blob(gcs_path)

        # Create temp file with proper suffix
        if not suffix and "." in gcs_path:
            suffix = "." + gcs_path.rsplit(".", 1)[-1]

        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            temp_path = tmp.name

        print(f"[GCS] Downloading {gcs_path} to {temp_path}...")
        blob.download_to_filename(temp_path)

        file_size = os.path.getsize(temp_path)
        print(f"[GCS] Downloaded {file_size / (1024*1024):.1f} MB")

        return temp_path

    @classmethod
    def move_to_processed(cls, gcs_path: str) -> str:
        """
        Move a file from uploads/ to processed/ folder.

        This is called after successful transcription to:
        1. Keep the file for video playback
        2. Apply different lifecycle rules (7 days instead of 1 day)

        Args:
            gcs_path: Current path in GCS

        Returns:
            New path in processed/ folder
        """
        bucket = cls._get_bucket()

        # Calculate new path
        filename = gcs_path.rsplit("/", 1)[-1]
        new_path = f"{settings.GCS_PROCESSED_PREFIX}{filename}"

        # Copy to new location
        source_blob = bucket.blob(gcs_path)
        bucket.copy_blob(source_blob, bucket, new_path)

        # Delete original
        source_blob.delete()

        print(f"[GCS] Moved {gcs_path} -> {new_path}")
        return new_path

    @classmethod
    def generate_download_signed_url(
        cls,
        gcs_path: str,
        expiry_seconds: Optional[int] = None
    ) -> str:
        """
        Generate a signed URL for downloading/streaming a file.

        Use this for video playback - URLs are valid for 24 hours by default.
        Uses IAM signBlob API for Cloud Run compatibility.

        Args:
            gcs_path: Path in GCS
            expiry_seconds: URL expiry time (default 24 hours)

        Returns:
            Signed URL for GET request
        """
        # Get credentials for IAM signing
        credentials = cls._get_credentials()
        bucket = cls._get_bucket()
        blob = bucket.blob(gcs_path)
        expiry = expiry_seconds or settings.GCS_DOWNLOAD_URL_EXPIRY

        signed_url = blob.generate_signed_url(
            version="v4",
            expiration=timedelta(seconds=expiry),
            method="GET",
            service_account_email=cls._service_account_email,
            access_token=credentials.token,
        )

        return signed_url

    @classmethod
    def delete_file(cls, gcs_path: str) -> bool:
        """Delete a file from GCS."""
        try:
            bucket = cls._get_bucket()
            blob = bucket.blob(gcs_path)
            blob.delete()
            print(f"[GCS] Deleted {gcs_path}")
            return True
        except Exception as e:
            print(f"[GCS] Failed to delete {gcs_path}: {e}")
            return False

    @classmethod
    def cleanup_old_uploads(cls, max_age_hours: int = 24) -> int:
        """
        Clean up old uploads that weren't processed.

        This is a backup to the lifecycle policy - called on app startup.

        Args:
            max_age_hours: Delete files older than this

        Returns:
            Number of files deleted
        """
        from datetime import datetime, timezone

        bucket = cls._get_bucket()
        deleted_count = 0
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)

        # List files in uploads/ prefix
        blobs = bucket.list_blobs(prefix=settings.GCS_UPLOAD_PREFIX)

        for blob in blobs:
            if blob.time_created and blob.time_created < cutoff_time:
                try:
                    blob.delete()
                    deleted_count += 1
                    print(f"[GCS] Cleaned up old upload: {blob.name}")
                except Exception as e:
                    print(f"[GCS] Failed to clean up {blob.name}: {e}")

        if deleted_count > 0:
            print(f"[GCS] Cleanup complete: deleted {deleted_count} old files")

        return deleted_count


# Singleton instance for easy import
gcs_service = GCSService
