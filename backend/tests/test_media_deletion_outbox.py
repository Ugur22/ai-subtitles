import asyncio
from types import SimpleNamespace

import pytest

from services import job_queue_service
from services.job_queue_service import JobQueueService


class RpcCall:
    def __init__(self, response):
        self.response = response

    def execute(self):
        if isinstance(self.response, Exception):
            raise self.response
        return SimpleNamespace(data=self.response)


class Client:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def rpc(self, name, params):
        self.calls.append((name, params))
        response = self.responses[name]
        if isinstance(response, list) and response and isinstance(response[0], list):
            response = response.pop(0)
        return RpcCall(response)


class Storage:
    def __init__(self, error=None, result=True):
        self.error = error
        self.result = result
        self.deleted = []

    def delete_file(self, media_key):
        self.deleted.append(media_key)
        if self.error:
            raise self.error
        return self.result


def test_storage_success_marks_claim_complete(monkeypatch):
    client = Client({
        "claim_media_deletes": [{"id": "outbox-1", "media_key": "processed/user-a/i/video.mp4"}],
        "finish_media_delete": True,
    })
    storage = Storage()
    monkeypatch.setattr(job_queue_service, "supabase", lambda: client)

    result = JobQueueService.process_media_delete_outbox(storage=storage)

    assert result == {"claimed": 1, "completed": 1, "pending": 0}
    assert storage.deleted == ["processed/user-a/i/video.mp4"]
    assert client.calls[-1] == (
        "finish_media_delete",
        {"p_outbox_id": "outbox-1", "p_error": None},
    )


def test_storage_failure_returns_claim_to_pending(monkeypatch):
    client = Client({
        "claim_media_deletes": [{"id": "outbox-1", "media_key": "processed/user-a/i/video.mp4"}],
        "finish_media_delete": True,
    })
    storage = Storage(RuntimeError("storage unavailable"))
    monkeypatch.setattr(job_queue_service, "supabase", lambda: client)

    result = JobQueueService.process_media_delete_outbox(storage=storage)

    assert result == {"claimed": 1, "completed": 0, "pending": 1}
    assert client.calls[-1][0] == "finish_media_delete"
    assert "storage unavailable" in client.calls[-1][1]["p_error"]


def test_storage_false_result_returns_claim_to_pending(monkeypatch):
    client = Client({
        "claim_media_deletes": [{"id": "outbox-1", "media_key": "processed/user-a/i/video.mp4"}],
        "finish_media_delete": True,
    })
    storage = Storage(result=False)
    monkeypatch.setattr(job_queue_service, "supabase", lambda: client)

    result = JobQueueService.process_media_delete_outbox(storage=storage)

    assert result == {"claimed": 1, "completed": 0, "pending": 1}
    assert client.calls[-1][1]["p_error"] == "delete_file returned False"


class JobsTable:
    def __init__(self, rows):
        self.rows = rows
        self.filters = {}

    def select(self, _columns):
        return self

    def eq(self, column, value):
        self.filters[column] = value
        return self

    def limit(self, _count):
        return self

    def execute(self):
        return SimpleNamespace(data=[
            row for row in self.rows
            if all(row.get(column) == value for column, value in self.filters.items())
        ])


class ClientWithJobs(Client):
    def __init__(self, responses, jobs=()):
        super().__init__(responses)
        self.jobs = list(jobs)

    def table(self, name):
        assert name == "jobs"
        return JobsTable(self.jobs)


class ScreenshotStorage(Storage):
    def __init__(self, result=True):
        super().__init__(result=result)
        self.folders = []

    def delete_screenshots(self, user_id, video_hash):
        self.folders.append((user_id, video_hash))
        return self.result


SCREENSHOT_FOLDER = "screenshots/user-a/hash-a/"


def _screenshot_claim(jobs=()):
    return ClientWithJobs({
        "claim_media_deletes": [{"id": "outbox-s", "media_key": SCREENSHOT_FOLDER}],
        "finish_media_delete": True,
    }, jobs)


def test_screenshot_folder_row_deletes_the_owners_folder(monkeypatch):
    client = _screenshot_claim(jobs=[{"user_id": "user-b", "video_hash": "hash-a"}])
    storage = ScreenshotStorage()
    monkeypatch.setattr(job_queue_service, "supabase", lambda: client)

    result = JobQueueService.process_media_delete_outbox(storage=storage)

    assert result == {"claimed": 1, "completed": 1, "pending": 0}
    assert storage.folders == [("user-a", "hash-a")]
    assert storage.deleted == []


def test_screenshot_folder_is_kept_when_the_file_was_uploaded_again(monkeypatch):
    client = _screenshot_claim(jobs=[{"user_id": "user-a", "video_hash": "hash-a"}])
    storage = ScreenshotStorage()
    monkeypatch.setattr(job_queue_service, "supabase", lambda: client)

    result = JobQueueService.process_media_delete_outbox(storage=storage)

    assert result == {"claimed": 1, "completed": 1, "pending": 0}
    assert storage.folders == []


def test_screenshot_folder_stays_pending_when_screenshots_remain(monkeypatch):
    client = _screenshot_claim()
    storage = ScreenshotStorage(result=False)
    monkeypatch.setattr(job_queue_service, "supabase", lambda: client)

    result = JobQueueService.process_media_delete_outbox(storage=storage)

    assert result == {"claimed": 1, "completed": 0, "pending": 1}
    assert client.calls[-1][1]["p_error"] == "screenshots remain after delete"


def test_malformed_folder_row_is_never_deleted(monkeypatch):
    client = ClientWithJobs({
        "claim_media_deletes": [{"id": "outbox-s", "media_key": "screenshots/user-a/"}],
        "finish_media_delete": True,
    })
    storage = ScreenshotStorage()
    monkeypatch.setattr(job_queue_service, "supabase", lambda: client)

    result = JobQueueService.process_media_delete_outbox(storage=storage)

    assert result["pending"] == 1
    assert storage.folders == []


class GcsFake:
    """Bucket and client whose deletes are recorded per batch request."""

    def __init__(self, keys, undeletable=()):
        self.keys = set(keys)
        self.undeletable = set(undeletable)
        self.batches = []

    def blob(self, key):
        def delete():
            self.batches[-1].append(key)
            if key not in self.undeletable:
                self.keys.discard(key)
        return SimpleNamespace(delete=delete)

    def list_blobs(self, prefix):
        return [SimpleNamespace(name=key) for key in sorted(self.keys) if key.startswith(prefix)]

    def batch(self, raise_exception=True):
        assert raise_exception is False
        fake = self

        class Batch:
            def __enter__(self):
                fake.batches.append([])

            def __exit__(self, *_exc):
                return False

        return Batch()


def _gcs_storage(monkeypatch, fake):
    from services.gcs_service import GCSService
    from services.media_storage import GCSMediaStorage

    monkeypatch.setattr(GCSService, "_get_bucket", classmethod(lambda cls: fake))
    monkeypatch.setattr(GCSService, "_get_client", classmethod(lambda cls: fake))
    # Skip __init__: it only checks production settings.
    return GCSMediaStorage.__new__(GCSMediaStorage)


def test_gcs_screenshot_delete_sends_batches_of_at_most_100(monkeypatch):
    keys = [f"screenshots/user-a/hash-a/{n}.00.jpg" for n in range(250)]
    other = "screenshots/user-a/hash-b/1.00.jpg"
    fake = GcsFake(keys + [other])

    assert _gcs_storage(monkeypatch, fake).delete_screenshots("user-a", "hash-a") is True
    assert [len(batch) for batch in fake.batches] == [100, 100, 50]
    assert fake.keys == {other}


def test_gcs_screenshot_delete_reports_screenshots_left_behind(monkeypatch):
    keys = [f"screenshots/user-a/hash-a/{n}.00.jpg" for n in range(3)]
    fake = GcsFake(keys, undeletable=[keys[1]])

    assert _gcs_storage(monkeypatch, fake).delete_screenshots("user-a", "hash-a") is False


def test_local_screenshot_folder_delete_leaves_other_videos(monkeypatch, tmp_path):
    from services.local_storage_service import LocalStorageService

    storage = LocalStorageService(str(tmp_path / "media"))
    for video_hash in ("hash-a", "hash-b"):
        with storage.atomic_writer(storage.screenshot_key("user-a", video_hash, 1.0)) as handle:
            handle.write(b"jpg")
    client = _screenshot_claim()
    monkeypatch.setattr(job_queue_service, "supabase", lambda: client)

    result = JobQueueService.process_media_delete_outbox(storage=storage)

    assert result["completed"] == 1
    assert storage.list_screenshot_keys("user-a", "hash-a") == []
    assert storage.list_screenshot_keys("user-a", "hash-b") == ["screenshots/user-a/hash-b/1.00.jpg"]


def test_permanent_delete_drains_video_and_screenshots(monkeypatch):
    from routers import jobs

    request = SimpleNamespace(state=SimpleNamespace(user={"id": "user-a"}))
    drained = []
    monkeypatch.setattr(
        jobs, "require_job_owner", lambda _job_id, _user_id: {"id": "job-a", "status": "completed"}
    )
    monkeypatch.setattr(
        JobQueueService,
        "claim_permanent_deletion",
        staticmethod(lambda *_args: {
            "deleted": True, "outbox_id": "outbox-v", "screenshots_outbox_id": "outbox-s",
        }),
    )
    monkeypatch.setattr(
        JobQueueService,
        "drain_media_deletions_best_effort",
        staticmethod(lambda **kwargs: drained.append(kwargs["outbox_id"]) or {
            "claimed": 1, "completed": 1, "pending": 0,
        }),
    )

    result = asyncio.run(jobs.delete_job_permanent.__wrapped__(request, "job-a", None))

    assert drained == ["outbox-v", "outbox-s"]
    assert result["deleted_resources"] == {"video": True, "screenshots": True, "database": True}
    assert result["cleanup_pending"] is False


def test_database_claim_failure_never_touches_storage(monkeypatch):
    client = Client({"claim_media_deletes": RuntimeError("database unavailable")})
    storage = Storage()
    monkeypatch.setattr(job_queue_service, "supabase", lambda: client)

    with pytest.raises(RuntimeError, match="database unavailable"):
        JobQueueService.process_media_delete_outbox(storage=storage)

    assert storage.deleted == []


def test_best_effort_drain_is_nonfatal_when_database_is_unavailable(monkeypatch):
    client = Client({"claim_media_deletes": RuntimeError("database unavailable")})
    storage = Storage()
    monkeypatch.setattr(job_queue_service, "supabase", lambda: client)

    result = JobQueueService.drain_media_deletions_best_effort(
        storage=storage,
        limit=3,
    )

    assert result == {"claimed": 0, "completed": 0, "pending": 0}
    assert storage.deleted == []


def test_finish_failure_reclaim_completes_when_local_object_is_absent(
    monkeypatch, tmp_path
):
    from services.local_storage_service import LocalStorageService

    storage = LocalStorageService(str(tmp_path / "media"))
    media_key = storage.upload_path("user-a", "intent-a", "video.mp4")
    with storage.atomic_writer(media_key) as handle:
        handle.write(b"video")
    row = [{"id": "outbox-1", "media_key": media_key}]
    first_client = Client({
        "claim_media_deletes": row,
        "finish_media_delete": RuntimeError("finish unavailable"),
    })
    monkeypatch.setattr(job_queue_service, "supabase", lambda: first_client)

    with pytest.raises(RuntimeError, match="finish unavailable"):
        JobQueueService.process_media_delete_outbox(storage=storage)
    assert not storage.file_exists(media_key)

    retry_client = Client({
        "claim_media_deletes": row,
        "finish_media_delete": True,
    })
    monkeypatch.setattr(job_queue_service, "supabase", lambda: retry_client)
    result = JobQueueService.process_media_delete_outbox(storage=storage)

    assert result == {"claimed": 1, "completed": 1, "pending": 0}
    assert retry_client.calls[-1][1]["p_error"] is None


def test_permanent_claim_passes_authenticated_owner(monkeypatch):
    client = Client({
        "delete_job_permanent_secure": [{
            "deleted": True,
            "outbox_id": "outbox-1",
            "media_key": "processed/user-a/i/video.mp4",
        }],
    })
    monkeypatch.setattr(job_queue_service, "supabase", lambda: client)

    result = JobQueueService.claim_permanent_deletion("job-a", "user-a")

    assert result["outbox_id"] == "outbox-1"
    assert client.calls == [(
        "delete_job_permanent_secure",
        {"p_job_id": "job-a", "p_user_id": "user-a"},
    )]


def test_gcs_delete_is_idempotent_only_for_not_found(monkeypatch):
    from google.api_core.exceptions import NotFound, ServiceUnavailable
    from services.gcs_service import GCSService

    class Blob:
        def __init__(self, error):
            self.error = error

        def delete(self):
            raise self.error

    class Bucket:
        def __init__(self, error):
            self.error = error

        def blob(self, _key):
            return Blob(self.error)

    monkeypatch.setattr(
        GCSService,
        "_get_bucket",
        classmethod(lambda cls: Bucket(NotFound("already absent"))),
    )
    assert GCSService.delete_file("processed/user-a/i/video.mp4") is True

    monkeypatch.setattr(
        GCSService,
        "_get_bucket",
        classmethod(lambda cls: Bucket(ServiceUnavailable("temporary"))),
    )
    with pytest.raises(ServiceUnavailable):
        GCSService.delete_file("processed/user-a/i/video.mp4")


def test_worker_and_local_startup_drain_pending_media_contract():
    from pathlib import Path

    backend = Path(__file__).parents[1]
    worker_main = (backend / "worker_main.py").read_text()
    worker = (backend / "services" / "background_worker.py").read_text()
    main = (backend / "main.py").read_text()

    worker_run = worker_main[worker_main.index("async def _run"):worker_main.index("def main")]
    assert worker_run.index("drain_media_deletions_best_effort") < worker_run.index(
        "background_worker.process_job"
    )

    process_job = worker[worker.index("async def process_job"):worker.index("async def _resume_finalization")]
    assert process_job.index("drain_media_deletions_best_effort") < process_job.index(
        "JobQueueService.get_job(job_id)"
    )
    settle_index = process_job.index("JobQueueService.settle_finalization(job_id, user_id)")
    assert process_job.index("drain_media_deletions_best_effort", settle_index) > settle_index

    resume = worker[worker.index("async def _resume_finalization"):worker.index("def _generate_vtt")]
    settle_index = resume.index("JobQueueService.settle_finalization(job_id, user_id)")
    assert resume.index("drain_media_deletions_best_effort", settle_index) > settle_index

    startup = main[main.index("async def lifespan"):main.index("app = FastAPI(")]
    local_index = startup.index("if app_settings.LOCAL_MODE:")
    drain_index = startup.index("drain_media_deletions_best_effort")
    assert local_index < drain_index
    assert "asyncio.create_task(asyncio.to_thread(" in startup
    local_block = startup[local_index:startup.index("if app_settings.ENABLE_GCS_UPLOADS:")]
    assert "gcs_service" not in local_block


def test_stale_finalization_dispatch_failure_is_nonfatal(monkeypatch):
    client = Client({
        "claim_stale_finalizing_job": [{
            "job_id": "job-a",
            "action": "redispatch",
            "retry_count": 1,
        }],
    })
    monkeypatch.setattr(job_queue_service, "supabase", lambda: client)
    monkeypatch.setattr(
        JobQueueService,
        "trigger_worker_job",
        staticmethod(lambda _job_id: (_ for _ in ()).throw(RuntimeError("dispatch down"))),
    )

    assert JobQueueService.check_and_recover_stale_jobs() == "job-a"


def test_stale_finalization_max_exhaustion_does_not_dispatch(monkeypatch):
    client = Client({
        "claim_stale_finalizing_job": [{
            "job_id": "job-a",
            "action": "failed",
            "retry_count": 3,
        }],
    })
    dispatched = []
    monkeypatch.setattr(job_queue_service, "supabase", lambda: client)
    monkeypatch.setattr(
        JobQueueService,
        "trigger_worker_job",
        staticmethod(lambda job_id: dispatched.append(job_id)),
    )

    assert JobQueueService.check_and_recover_stale_jobs() == "job-a"
    assert dispatched == []


@pytest.mark.parametrize("status", ["pending", "processing"])
def test_cancel_endpoint_allows_active_jobs(monkeypatch, status):
    from routers import jobs

    request = SimpleNamespace(state=SimpleNamespace(user={"id": "user-a"}))
    calls = []
    monkeypatch.setattr(
        jobs,
        "require_job_owner",
        lambda _job_id, _user_id: {"id": "job-a", "status": status},
    )
    monkeypatch.setattr(
        JobQueueService,
        "cancel_job",
        staticmethod(lambda job_id, user_id: calls.append((job_id, user_id)) or True),
    )

    result = asyncio.run(jobs.cancel_job.__wrapped__(request, "job-a", None))

    assert result.status == "cancelled"
    assert calls == [("job-a", "user-a")]


@pytest.mark.parametrize(
    "status",
    ["completed", "failed", "cancelled", "finalizing"],
)
def test_cancel_endpoint_rejects_non_cancellable_jobs(monkeypatch, status):
    from fastapi import HTTPException
    from routers import jobs

    request = SimpleNamespace(state=SimpleNamespace(user={"id": "user-a"}))
    calls = []
    monkeypatch.setattr(
        jobs,
        "require_job_owner",
        lambda _job_id, _user_id: {"id": "job-a", "status": status},
    )
    monkeypatch.setattr(
        JobQueueService,
        "cancel_job",
        staticmethod(lambda *args: calls.append(args) or True),
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(jobs.cancel_job.__wrapped__(request, "job-a", None))

    assert exc.value.status_code == 400
    assert calls == []


@pytest.mark.parametrize("status", ["pending", "processing"])
def test_permanent_delete_endpoint_rejects_active_jobs(monkeypatch, status):
    from fastapi import HTTPException
    from routers import jobs

    request = SimpleNamespace(state=SimpleNamespace(user={"id": "user-a"}))
    cleanup_calls = []
    monkeypatch.setattr(
        jobs,
        "require_job_owner",
        lambda _job_id, _user_id: {"id": "job-a", "status": status},
    )
    monkeypatch.setattr(
        JobQueueService,
        "claim_permanent_deletion",
        staticmethod(
            lambda *_args: {"deleted": False, "error_code": "job_not_terminal"}
        ),
    )
    monkeypatch.setattr(
        JobQueueService,
        "drain_media_deletions_best_effort",
        staticmethod(lambda **kwargs: cleanup_calls.append(kwargs)),
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(jobs.delete_job_permanent.__wrapped__(request, "job-a", None))

    assert exc.value.status_code == 409
    assert cleanup_calls == []


def test_permanent_delete_success_survives_cleanup_failure(monkeypatch):
    from routers import jobs

    request = SimpleNamespace(state=SimpleNamespace(user={"id": "user-a"}))
    monkeypatch.setattr(
        jobs,
        "require_job_owner",
        lambda _job_id, _user_id: {"id": "job-a", "status": "completed"},
    )
    monkeypatch.setattr(
        JobQueueService,
        "claim_permanent_deletion",
        staticmethod(lambda *_args: {"deleted": True, "outbox_id": "outbox-a"}),
    )
    monkeypatch.setattr(
        JobQueueService,
        "drain_media_deletions_best_effort",
        staticmethod(lambda **_kwargs: {"claimed": 0, "completed": 0, "pending": 0}),
    )

    result = asyncio.run(
        jobs.delete_job_permanent.__wrapped__(request, "job-a", None)
    )

    assert result["success"] is True
    assert result["deleted_resources"]["database"] is True
    assert result["cleanup_pending"] is True


def test_permanent_delete_db_failure_never_attempts_cleanup(monkeypatch):
    from fastapi import HTTPException
    from routers import jobs

    request = SimpleNamespace(state=SimpleNamespace(user={"id": "user-a"}))
    cleanup_calls = []
    monkeypatch.setattr(
        jobs,
        "require_job_owner",
        lambda _job_id, _user_id: {"id": "job-a", "status": "completed"},
    )
    monkeypatch.setattr(
        JobQueueService,
        "claim_permanent_deletion",
        staticmethod(lambda *_args: (_ for _ in ()).throw(RuntimeError("database down"))),
    )
    monkeypatch.setattr(
        JobQueueService,
        "drain_media_deletions_best_effort",
        staticmethod(lambda **kwargs: cleanup_calls.append(kwargs)),
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(jobs.delete_job_permanent.__wrapped__(request, "job-a", None))

    assert exc.value.status_code == 500
    assert cleanup_calls == []
