import importlib
import signal
import sys
import threading
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from services import job_queue_service
from services.job_queue_service import JobQueueService, MAX_RETRIES

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent


class Query:
    def __init__(self, client, table):
        self.client = client
        self.table = table
        self.filters = {}
        self.update_values = None

    def select(self, _columns):
        return self

    def update(self, values):
        self.update_values = values
        return self

    def eq(self, column, value):
        self.filters[column] = value
        return self

    def is_(self, column, _value):
        self.filters[column] = None
        return self

    def lt(self, column, value):
        self.filters[f"{column}<"] = value
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, _count):
        return self

    def single(self):
        return self

    def execute(self):
        return SimpleNamespace(data=self.client.run(self))


class Client:
    """Minimal jobs/user_profiles store whose RPCs behave like the SQL compare-and-sets."""

    def __init__(self, jobs):
        self.jobs = jobs
        self.rpc_calls = []
        self.lock = threading.Lock()

    def table(self, name):
        return Query(self, name)

    def run(self, query):
        if query.table == "user_profiles":
            return [{"id": query.filters["id"], "is_admin": False, "subscription_plan": "free"}]
        matched = [job for job in self.jobs if self._matches(job, query.filters)]
        if query.update_values is not None:
            for job in matched:
                job.update(query.update_values)
        return [dict(job) for job in matched]

    @staticmethod
    def _matches(job, filters):
        for column, value in filters.items():
            if column.endswith("<"):
                if not (job.get(column[:-1]) or 0) < value:
                    return False
            elif job.get(column) != value:
                return False
        return True

    def rpc(self, name, params):
        self.rpc_calls.append((name, params))
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=self._rpc(name, params)))

    def _rpc(self, name, params):
        if name == "claim_stale_finalizing_job":
            return []
        job = next((j for j in self.jobs if j["id"] == params["p_job_id"]), None)
        if name == "timeout_job_secure":
            if not job or job["status"] != "processing":
                return False
            job.update(status="failed", error_code="worker_timeout",
                       error_message=params["p_error_message"])
            return True
        if name == "auto_retry_timed_out_job":
            with self.lock:
                eligible = (
                    job and job["status"] == "failed"
                    and job["error_code"] == "worker_timeout"
                    and job["timeout_auto_retries"] < 1
                    and job["retry_count"] < params["p_max_retries"]
                )
                if not eligible:
                    return False
                active = sum(
                    1 for other in self.jobs
                    if other["user_id"] == job["user_id"]
                    and other["status"] in ("pending", "processing", "finalizing")
                )
                if active >= params["p_user_concurrent_limit"]:
                    return False
                job.update(status="pending", error_code=None,
                           retry_count=job["retry_count"] + 1,
                           timeout_auto_retries=job["timeout_auto_retries"] + 1)
                return True
        if name == "fail_job_secure":
            job.update(status="failed", error_code=params["p_error_code"])
            return True
        raise AssertionError(f"unexpected rpc {name}")


def _job(**overrides):
    job = {
        "id": "job-a", "user_id": "user-a", "status": "failed",
        "error_code": "worker_timeout", "retry_count": 0, "timeout_auto_retries": 0,
        "failed_at": "2026-11-14T10:00:00", "last_seen": "2026-11-14T10:00:00",
    }
    job.update(overrides)
    return job


@pytest.fixture
def dispatched(monkeypatch):
    calls = []
    monkeypatch.setattr(
        JobQueueService, "trigger_worker_job", staticmethod(lambda job_id: calls.append(job_id))
    )
    return calls


def _use(monkeypatch, client):
    monkeypatch.setattr(job_queue_service, "supabase", lambda: client)
    return client


def test_timeout_marks_processing_job_failed_with_worker_timeout(monkeypatch):
    client = _use(monkeypatch, Client([_job(status="processing", error_code=None)]))

    assert JobQueueService.mark_worker_timeout("job-a") is True

    assert client.jobs[0]["status"] == "failed"
    assert client.jobs[0]["error_code"] == "worker_timeout"
    assert [name for name, _ in client.rpc_calls] == ["timeout_job_secure"]


@pytest.mark.parametrize("status", ["cancelled", "pending", "finalizing", "completed"])
def test_timeout_leaves_cancelled_and_handed_over_jobs_alone(monkeypatch, status):
    client = _use(monkeypatch, Client([_job(status=status, error_code=None)]))

    assert JobQueueService.mark_worker_timeout("job-a") is False

    assert client.jobs[0]["status"] == status
    assert client.jobs[0]["error_code"] is None


def test_check_stale_retries_a_timed_out_job_exactly_once(monkeypatch, dispatched):
    client = _use(monkeypatch, Client([_job()]))

    assert JobQueueService.check_and_recover_stale_jobs() == "job-a"
    assert dispatched == ["job-a"]
    assert client.jobs[0]["status"] == "pending"
    assert (client.jobs[0]["retry_count"], client.jobs[0]["timeout_auto_retries"]) == (1, 1)

    # The retried run times out again: it is left for a manual retry from the UI.
    client.jobs[0].update(status="failed", error_code="worker_timeout")
    assert JobQueueService.check_and_recover_stale_jobs() is None
    assert dispatched == ["job-a"]
    assert client.jobs[0]["status"] == "failed"


def test_concurrent_check_stale_runs_dispatch_once(monkeypatch, dispatched):
    _use(monkeypatch, Client([_job()]))
    barrier = threading.Barrier(4)
    results = []

    def run():
        barrier.wait()
        results.append(JobQueueService.auto_retry_worker_timeout())

    threads = [threading.Thread(target=run) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert dispatched == ["job-a"]
    assert sorted(results, key=str) == [None, None, None, "job-a"]


def test_timeout_retry_respects_max_retries_and_user_concurrency(monkeypatch, dispatched):
    _use(monkeypatch, Client([_job(retry_count=MAX_RETRIES)]))
    assert JobQueueService.auto_retry_worker_timeout() is None

    # Free plan allows one active job; the owner already has one running.
    client = _use(monkeypatch, Client([
        _job(), _job(id="job-b", status="processing", error_code=None),
    ]))
    assert JobQueueService.auto_retry_worker_timeout() is None
    assert client.jobs[0]["timeout_auto_retries"] == 0     # not consumed, tried again later
    assert dispatched == []


def test_other_failures_and_user_cancellations_are_not_auto_retried(monkeypatch, dispatched):
    _use(monkeypatch, Client([
        _job(error_code="transcription_error"),
        _job(id="job-b", status="cancelled", error_code=None),
    ]))

    assert JobQueueService.check_and_recover_stale_jobs() is None
    assert dispatched == []


def test_timeout_retry_dispatch_failure_marks_job_failed(monkeypatch):
    client = _use(monkeypatch, Client([_job()]))
    monkeypatch.setattr(
        JobQueueService, "trigger_worker_job",
        staticmethod(lambda _job_id: (_ for _ in ()).throw(RuntimeError("dispatch down"))),
    )

    assert JobQueueService.auto_retry_worker_timeout() == "job-a"
    assert client.jobs[0]["error_code"] == "dispatch_error"
    assert client.jobs[0]["timeout_auto_retries"] == 1


def test_stale_processing_recovery_does_not_dispatch_when_the_row_changed(monkeypatch, dispatched):
    stale = _job(status="processing", error_code=None, last_seen="2000-01-01T00:00:00")
    client = _use(monkeypatch, Client([stale]))
    original_run = client.run

    def run(query):
        rows = original_run(query) if query.update_values is None else None
        if query.update_values is None and query.table == "jobs" and query.filters.get("status") == "processing":
            # Another check-stale run recovers the job between this run's read and write.
            client.jobs[0]["retry_count"] = 1
            return rows
        return rows if rows is not None else original_run(query)

    monkeypatch.setattr(client, "run", run)
    monkeypatch.setattr(Client, "_matches", staticmethod(
        lambda job, filters: all(
            (job.get(column[:-1]) or "") < value if column.endswith("<") else job.get(column) == value
            for column, value in filters.items()
        )
    ))

    assert JobQueueService.check_and_recover_stale_jobs() is None
    assert dispatched == []


@pytest.fixture
def worker_main(monkeypatch):
    """Import worker_main with its heavy pipeline import stubbed out."""
    stub = ModuleType("services.background_worker")
    stub.background_worker = object()
    stub.JobCancelled = type("JobCancelled", (Exception,), {})
    monkeypatch.setitem(sys.modules, "services.background_worker", stub)
    monkeypatch.setenv("LOCAL_MODE", "true")
    monkeypatch.setenv("SUPABASE_URL", "https://example-project.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-key")
    from config import settings
    monkeypatch.setattr(type(settings), "validate_runtime", lambda self: None)
    sys.modules.pop("worker_main", None)
    module = importlib.import_module("worker_main")
    yield module
    sys.modules.pop("worker_main", None)


def test_sigterm_is_a_timeout_and_sigint_is_a_cancel(worker_main, monkeypatch):
    calls = []
    monkeypatch.setattr(
        worker_main.JobQueueService, "mark_worker_timeout",
        staticmethod(lambda job_id: calls.append(("timeout", job_id)) or True),
    )
    monkeypatch.setattr(
        worker_main.JobQueueService, "cancel_job",
        staticmethod(lambda job_id: calls.append(("cancel", job_id)) or True),
    )
    previous = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        worker_main._install_signal_handlers("job-a")
        signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        assert calls == [("timeout", "job-a")]
        signal.getsignal(signal.SIGINT)(signal.SIGINT, None)
        assert calls == [("timeout", "job-a"), ("cancel", "job-a")]
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def test_timeout_migration_contract():
    migration = (BACKEND / "sql/migrations/019_worker_timeout_retry.sql").read_text(encoding="utf-8")
    timeout = migration[migration.index("FUNCTION timeout_job_secure"):]
    timeout = timeout[:timeout.index("CREATE OR REPLACE FUNCTION auto_retry_timed_out_job")]
    retry = migration[migration.index("FUNCTION auto_retry_timed_out_job"):]

    assert "v_job.status <> 'processing'" in timeout
    assert "error_code = 'worker_timeout'" in timeout
    assert "'cancelled'" not in timeout and "'pending'" not in timeout
    assert "FOR UPDATE" in retry
    assert "v_job.timeout_auto_retries >= 1" in retry
    assert "COALESCE(v_job.retry_count, 0) >= p_max_retries" in retry
    assert "AND timeout_auto_retries < 1" in retry
    assert "continuation_count" not in retry
    assert "TO service_role" in migration


def test_frontend_explains_worker_timeout():
    card = (REPO / "frontend/src/components/features/jobs/JobCard.tsx").read_text(encoding="utf-8")
    assert "worker_timeout:" in card
    assert "max_continuations_reached:" in card
    assert "FAILURE_MESSAGES[job.error_code]" in card
