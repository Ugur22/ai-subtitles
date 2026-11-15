from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from services import job_queue_service, pipeline_cache_service
from services.db_retry import with_db_retry
from services.job_queue_service import JobQueueService
from services.pipeline_cache_service import PipelineCacheService

REPO = Path(__file__).resolve().parents[2]
DISCONNECT = httpx.RemoteProtocolError("Server disconnected")


class Flaky:
    """Callable that raises the given errors in order, then returns the result."""

    def __init__(self, errors, result="ok"):
        self.errors = list(errors)
        self.result = result
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return self.result


@pytest.fixture(autouse=True)
def delays(monkeypatch):
    recorded = []
    monkeypatch.setattr("services.db_retry.time.sleep", recorded.append)
    return recorded


def test_succeeds_after_dropped_connections_with_growing_delays(delays):
    operation = Flaky([DISCONNECT, httpx.ReadError("reset")])

    assert with_db_retry(operation, label="test") == "ok"
    assert operation.calls == 3
    assert delays == [0.5, 2.0]


def test_gives_up_after_three_attempts_and_raises_the_original_error(delays):
    operation = Flaky([DISCONNECT] * 5)

    with pytest.raises(httpx.RemoteProtocolError, match="Server disconnected"):
        with_db_retry(operation, label="test")

    assert operation.calls == 3
    assert len(delays) == 2


@pytest.mark.parametrize("error", [ValueError("bad input"), httpx.ReadTimeout("slow")])
def test_timeouts_and_other_errors_are_not_retried(error):
    operation = Flaky([error])

    with pytest.raises(type(error)):
        with_db_retry(operation, label="test")

    assert operation.calls == 1


class RpcClient:
    """Supabase stand-in whose RPCs and table reads fail with scripted errors first."""

    def __init__(self, rpc_results=None, errors=None, rows=None):
        self.rpc_results = rpc_results or {}
        self.errors = {name: list(items) for name, items in (errors or {}).items()}
        self.rows = rows or []
        self.calls = []

    def _execute(self, name, result):
        def execute():
            self.calls.append(name)
            pending = self.errors.get(name)
            if pending:
                raise pending.pop(0)
            return SimpleNamespace(data=result)
        return SimpleNamespace(execute=execute)

    def rpc(self, name, _params):
        return self._execute(name, self.rpc_results.get(name))

    def table(self, name):
        query = self._execute(f"table:{name}", self.rows)
        for method in ("select", "eq", "like", "upsert"):
            setattr(query, method, lambda *_a, _q=query, **_k: _q)
        return query


def _finalize(job_id="job-a"):
    return JobQueueService.begin_finalization(
        job_id=job_id, user_id="user-a", video_hash="h", result_json={}, result_srt="",
        result_vtt="", video_duration_seconds=10, gpu_seconds=1.0, final_media_key="processed/user-a/x",
    )


def test_finalization_survives_the_disconnect_that_failed_a_real_job(monkeypatch):
    client = RpcClient(
        rpc_results={"begin_job_finalization": True, "settle_finalizing_job": True},
        errors={"begin_job_finalization": [DISCONNECT], "settle_finalizing_job": [DISCONNECT]},
    )
    monkeypatch.setattr(job_queue_service, "supabase", lambda: client)

    assert _finalize() is True
    assert JobQueueService.settle_finalization("job-a", "user-a") is True
    assert client.calls == ["begin_job_finalization"] * 2 + ["settle_finalizing_job"] * 2


def test_finalization_still_fails_when_the_database_stays_unreachable(monkeypatch):
    client = RpcClient(errors={"begin_job_finalization": [DISCONNECT] * 3})
    monkeypatch.setattr(job_queue_service, "supabase", lambda: client)

    with pytest.raises(httpx.RemoteProtocolError):
        _finalize()


def test_api_job_read_is_not_retried(monkeypatch):
    # The API calls get_job from async routes, where a retry sleep would block the event loop.
    client = RpcClient(errors={"table:jobs": [DISCONNECT]})
    monkeypatch.setattr(job_queue_service, "supabase", lambda: client)

    with pytest.raises(httpx.RemoteProtocolError):
        JobQueueService.get_job("job-a")
    assert client.calls == ["table:jobs"]


def test_worker_retries_its_job_reads():
    worker = (REPO / "backend/services/background_worker.py").read_text(encoding="utf-8")
    cancel_check = worker[worker.index("def _check_cancelled"):worker.index("class HeartbeatThread")]

    assert "with_db_retry(lambda: JobQueueService.get_job(job_id)" in cancel_check
    assert 'with_db_retry(lambda: JobQueueService.get_job(job_id), label="get_job")' in worker


def test_claim_is_not_retried(monkeypatch):
    client = RpcClient(errors={"claim_job": [DISCONNECT]})
    monkeypatch.setattr(job_queue_service, "supabase", lambda: client)

    with pytest.raises(httpx.RemoteProtocolError):
        JobQueueService.mark_processing("job-a")
    assert client.calls == ["claim_job"]


def test_continuation_whose_first_attempt_landed_still_continues(monkeypatch):
    # First attempt requeued the job, then the connection dropped; the repeat sees 'not_processing'.
    client = RpcClient(
        rpc_results={"requeue_job_for_continuation": "not_processing"},
        errors={"requeue_job_for_continuation": [DISCONNECT]},
        rows=[{"id": "job-a", "status": "pending", "stage": "continuing"}],
    )
    monkeypatch.setattr(job_queue_service, "supabase", lambda: client)

    assert JobQueueService.request_continuation("job-a", 1.0, 12) == "continue"


def test_continuation_on_a_cancelled_job_is_not_turned_into_continue(monkeypatch):
    client = RpcClient(
        rpc_results={"requeue_job_for_continuation": "not_processing"},
        errors={"requeue_job_for_continuation": [DISCONNECT]},
        rows=[{"id": "job-a", "status": "cancelled", "stage": "cancelled"}],
    )
    monkeypatch.setattr(job_queue_service, "supabase", lambda: client)

    assert JobQueueService.request_continuation("job-a", 1.0, 12) == "not_processing"


def test_continuation_without_a_retry_takes_not_processing_at_face_value(monkeypatch):
    clean = RpcClient(rpc_results={"requeue_job_for_continuation": "not_processing"})
    monkeypatch.setattr(job_queue_service, "supabase", lambda: clean)
    assert JobQueueService.request_continuation("job-a", 1.0, 12) == "not_processing"
    assert clean.calls == ["requeue_job_for_continuation"]


def test_cache_read_that_fails_once_is_not_treated_as_a_miss(monkeypatch):
    client = RpcClient(rows=[{"data": {"formatted_segments": [1]}}], errors={"table:pipeline_cache": [DISCONNECT]})
    monkeypatch.setattr(pipeline_cache_service, "supabase", lambda: client)

    assert PipelineCacheService.get_cached("user-a", "hash", "transcription") == {"formatted_segments": [1]}


def test_cache_write_is_retried(monkeypatch):
    client = RpcClient(errors={"table:pipeline_cache": [DISCONNECT]})
    monkeypatch.setattr(pipeline_cache_service, "supabase", lambda: client)

    assert PipelineCacheService.save_cache("user-a", "hash", "transcription", {}) is True
    assert client.calls == ["table:pipeline_cache"] * 2


def test_worker_reports_an_exhausted_connection_as_connection_lost():
    worker = (REPO / "backend/services/background_worker.py").read_text(encoding="utf-8")
    handler = worker[worker.index("# Categorize common errors"):]

    assert handler.index("isinstance(e, httpx.TransportError)") < handler.index('"not found" in error_message')
    assert 'error_code = "connection_lost"' in handler
