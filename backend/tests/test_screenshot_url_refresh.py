from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from unittest.mock import Mock

import pytest

from services.gcs_service import GCSService


@pytest.mark.parametrize("remaining_hours", [72, 120])
def test_opening_job_reuses_valid_screenshot_urls(monkeypatch, remaining_hours):
    issued = datetime.now(timezone.utc) - timedelta(days=7) + timedelta(hours=remaining_hours)
    url = "https://storage.googleapis.com/test-bucket/screenshots/frame.jpg?" + urlencode({
        "X-Goog-Date": issued.strftime("%Y%m%dT%H%M%SZ"),
        "X-Goog-Expires": "604800",
    })
    signer = Mock(return_value="refreshed-url")
    monkeypatch.setattr(GCSService, "generate_download_signed_url_resilient", signer)
    monkeypatch.setattr("services.gcs_service.settings.GCS_BUCKET_NAME", "test-bucket")
    segments = [{"screenshot_url": url} for _ in range(100)]

    GCSService.refresh_screenshot_urls_in_segments(segments)

    assert all(segment["screenshot_url"] == url for segment in segments)
    signer.assert_not_called()


@pytest.mark.parametrize("date,expiry", [
    ("20000101T000000Z", "604800"),
    ((datetime.now(timezone.utc) - timedelta(days=6)).strftime("%Y%m%dT%H%M%SZ"), "604800"),
    ("invalid", "604800"),
    ("20000101T000000Z", "invalid"),
    ("", ""),
])
def test_refresh_repairs_expired_near_expiry_and_invalid_urls(monkeypatch, date, expiry):
    url = "https://storage.googleapis.com/test-bucket/screenshots/frame.jpg?" + urlencode({
        "X-Goog-Date": date, "X-Goog-Expires": expiry,
    })
    signer = Mock(return_value="refreshed-url")
    monkeypatch.setattr(GCSService, "generate_download_signed_url_resilient", signer)
    monkeypatch.setattr("services.gcs_service.settings.GCS_BUCKET_NAME", "test-bucket")
    segments = [{"screenshot_url": url}, {"screenshot_url": "/static/frame.jpg"}, {}]

    GCSService.refresh_screenshot_urls_in_segments(segments)

    assert segments == [{"screenshot_url": "refreshed-url"}, {"screenshot_url": "/static/frame.jpg"}, {}]
    signer.assert_called_once()
