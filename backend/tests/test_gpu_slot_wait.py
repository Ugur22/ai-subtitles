import asyncio
import threading
from types import SimpleNamespace

import pytest

from services import background_worker as worker_module
from services import job_queue_service
from services.job_queue_service import (
    GLOBAL_CONCURRENT_LIMIT,
    MAX_RETRIES,
    WAITING_FOR_GPU_MESSAGE,
    WAITING_FOR_GPU_STAGE,
    JobQueueService,
)

OLD = "2000-01-01T00:00:00"


class Query:
    def __init__(self, store):
        self.store = store
        self.filters = []
        self.update_values = None

    def select(self, _columns):
        return self

    def update(self, values):
        self.update_values = values
        return self

    def eq(self, column, value):
        self.filters.append(lambda job: job.get(column) == value)
        return self

    def is_(self, column, _value):
        self.filters.append(lambda job: job.get(column) is None)
        return self

    def lt(self, column, value):
        self.filters.append(lambda job: (job.get(column) or "") < value)
        return self

    def or_(self, expression):
        assert expression == f"stage.is.null,stage.neq.{WAITING_FOR_GPU_STAGE}"
        self.filters.append(lambda job: job.get("stage") != WAITING_FOR_GPU_STAGE)
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, _count):
        return self

    def execute(self):
        with self.store.lock:
            matched = [job for job in self.store.jobs if all(f(job) for f in self.filters)]
            if self.update_values is not None:
                for job in matched:
                    job.update(self.update_values)
            return SimpleNamespace(data=[dict(job) for job in matched])


class Store:
    def __init__(self, jobs):
        self.jobs = jobs
        self.lock = threading.Lock()

    def table(self, name):
        assert name == "jobs"
        return Query(self)

    def job(self, job_id):
        return next(job for job in self.jobs if job["id"] == job_id)

    def rpc(self, name, params):
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=self._rpc(name, params)))

    def _processing(self):
        return sum(1 for job in self.jobs if job["status"] == "processing")

    def _rpc(self, name, params):
        with self.lock:
            limit = params.get("p_global_processing_limit")
            if name == "claim_stale_finalizing_job":
                return []
            if name == "auto_retry_timed_out_job":
                return False
            if name == "claim_job_with_outcome":
                job = self.job(params["p_job_id"])
                if job["status"] != "pending":
                    return "not_pending"
                resuming = job.get("continuation_count", 0) > 0 and job.get("stage") == "continuing"
                if not resuming and self._processing() >= limit:
                    return "at_capacity"
                job.update(status="processing", stage="starting")
                return "claimed"
            if name == "claim_waiting_for_gpu_job":
                if self._processing() >= limit:
                    return None
                waiting = sorted(
                    (j for j in self.jobs
                     if j["status"] == "pending" and j.get("stage") == WAITING_FOR_GPU_STAGE),
                    key=lambda j: j["created_at"],
                )
                if not waiting:
                    return None
                waiting[0].update(stage="queued", last_seen="2099-01-01T00:00:00")
                return waiting[0]["id"]
            if name == "fail_job_secure":
                self.job(params["p_job_id"]).update(
                    status="failed", error_code=params["p_error_code"]
                )
                return True
        raise AssertionError(f"unexpected rpc {name}")


def _job(job_id, status="pending", stage="queued", **overrides):
    job = {
        "id": job_id, "user_id": "user-a", "status": status, "stage": stage,
        "retry_count": 0, "continuation_count": 0, "created_at": "2026-11-16T10:00:00",
        "last_seen": "2099-01-01T00:00:00",
    }
    job.update(overrides)
    return job


def _busy(count=GLOBAL_CONCURRENT_LIMIT):
    return [_job(f"busy-{i}", status="processing", stage="transcribing") for i in range(count)]


@pytest.fixture
def dispatched(monkeypatch):
    calls = []
    monkeypatch.setattr(
        JobQueueService, "trigger_worker_job", staticmethod(lambda job_id: calls.append(job_id))
    )
    return calls


def _use(monkeypatch, store):
    monkeypatch.setattr(job_queue_service, "supabase", lambda: store)
    return store


def test_continuation_is_claimed_while_every_slot_is_taken(monkeypatch):
    store = _use(monkeypatch, Store(_busy() + [
        _job("job-a", stage="continuing", continuation_count=1),
    ]))

    assert JobQueueService.claim_for_processing("job-a") == "claimed"
    assert store.job("job-a")["status"] == "processing"


def test_new_job_at_capacity_waits_without_spending_a_retry(monkeypatch):
    store = _use(monkeypatch, Store(_busy() + [_job("job-a", retry_count=1, last_seen=OLD)]))

    class NoHeartbeat:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("a job that was not claimed must not start a heartbeat")

    monkeypatch.setattr(worker_module, "HeartbeatThread", NoHeartbeat)
    monkeypatch.setattr(worker_module, "get_media_storage", lambda: object())
    monkeypatch.setattr(
        JobQueueService, "drain_media_deletions_best_effort",
        staticmethod(lambda **_kwargs: None),
    )
    monkeypatch.setattr(JobQueueService, "get_job", staticmethod(lambda job_id: dict(store.job(job_id))))

    ok = asyncio.run(worker_module.BackgroundWorker().process_job("job-a"))

    assert ok is True
    job = store.job("job-a")
    assert (job["status"], job["stage"], job["message"]) == (
        "pending", WAITING_FOR_GPU_STAGE, WAITING_FOR_GPU_MESSAGE,
    )
    assert job["retry_count"] == 1
    assert job["last_seen"] > OLD


def test_claim_maps_unknown_results_to_not_pending(monkeypatch):
    store = _use(monkeypatch, Store([_job("job-a", status="completed")]))
    assert JobQueueService.claim_for_processing("job-a") == "not_pending"
    monkeypatch.setattr(store, "_rpc", lambda *_args: True)
    assert JobQueueService.claim_for_processing("job-a") == "not_pending"


def test_check_stale_dispatches_a_waiting_job_once_a_slot_frees_up(monkeypatch, dispatched):
    store = _use(monkeypatch, Store(_busy() + [
        _job("job-b", stage=WAITING_FOR_GPU_STAGE, last_seen=OLD, retry_count=2),
        _job("job-a", stage=WAITING_FOR_GPU_STAGE, last_seen=OLD, retry_count=2,
             created_at="2026-11-16T09:00:00"),
    ]))

    assert JobQueueService.check_and_recover_stale_jobs() is None
    assert dispatched == []
    assert store.job("job-a")["retry_count"] == 2

    store.job("busy-0")["status"] = "completed"
    assert JobQueueService.check_and_recover_stale_jobs() == "job-a"
    assert dispatched == ["job-a"]
    assert (store.job("job-a")["stage"], store.job("job-a")["retry_count"]) == ("queued", 2)
    assert store.job("job-b")["stage"] == WAITING_FOR_GPU_STAGE


def test_concurrent_check_stale_runs_dispatch_a_waiting_job_once(monkeypatch, dispatched):
    _use(monkeypatch, Store(_busy(GLOBAL_CONCURRENT_LIMIT - 1) + [
        _job("job-a", stage=WAITING_FOR_GPU_STAGE),
    ]))
    barrier = threading.Barrier(4)
    results = []

    def run():
        barrier.wait()
        results.append(JobQueueService.check_and_recover_stale_jobs())

    threads = [threading.Thread(target=run) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert dispatched == ["job-a"]
    assert sorted(results, key=str) == [None, None, None, "job-a"]


def test_dispatched_job_that_never_started_still_uses_the_retry_path(monkeypatch, dispatched):
    store = _use(monkeypatch, Store([_job("job-a", stage="queued", last_seen=OLD, retry_count=1)]))

    assert JobQueueService.check_and_recover_stale_jobs() == "job-a"
    assert dispatched == ["job-a"]
    assert (store.job("job-a")["status"], store.job("job-a")["retry_count"]) == ("pending", 2)

    store.job("job-a").update(last_seen=OLD, retry_count=MAX_RETRIES)
    assert JobQueueService.check_and_recover_stale_jobs() == "job-a"
    assert dispatched == ["job-a"]
    assert (store.job("job-a")["status"], store.job("job-a")["error_code"]) == (
        "failed", "startup_error",
    )


def test_stuck_continuation_keeps_its_stage_so_it_keeps_its_slot(monkeypatch, dispatched):
    store = _use(monkeypatch, Store([
        _job("job-a", stage="continuing", continuation_count=2, last_seen=OLD),
    ]))

    assert JobQueueService.check_and_recover_stale_jobs() == "job-a"
    assert (store.job("job-a")["stage"], store.job("job-a")["retry_count"]) == ("continuing", 1)
