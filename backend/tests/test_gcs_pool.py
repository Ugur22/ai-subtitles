from google.auth.credentials import AnonymousCredentials

from services.gcs_service import GCS_HTTP_POOL_SIZE, GCS_SCREENSHOT_WORKERS, GCSService


def test_client_pool_fits_parallel_screenshot_threads(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    monkeypatch.setattr(GCSService, "_client", None)
    monkeypatch.setattr(GCSService, "_get_credentials", classmethod(lambda cls: AnonymousCredentials()))

    adapter = GCSService._get_client()._http.adapters["https://"]

    assert adapter._pool_maxsize == GCS_HTTP_POOL_SIZE >= 2 * GCS_SCREENSHOT_WORKERS
