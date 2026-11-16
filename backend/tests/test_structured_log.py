import json
import sys
import threading
from types import SimpleNamespace

import pytest

from services import job_queue_service
from services.job_queue_service import JobQueueService
from utils import structured_log


class _Query:
    def __init__(self, client, table):
        self.client, self.table, self.filters = client, table, {}

    def select(self, _columns):
        return self

    def eq(self, column, value):
        self.filters[column] = value
        return self

    def limit(self, _count):
        return self

    def execute(self):
        if self.client.broken_tables and self.table in self.client.broken_tables:
            raise RuntimeError("supabase down")
        rows = self.client.tables.get(self.table, [])
        return SimpleNamespace(data=[r for r in rows if all(r.get(k) == v for k, v in self.filters.items())])


class _Client:
    def __init__(self, rpc_results, profile=None, broken_tables=()):
        self.rpc_results = rpc_results
        self.broken_tables = set(broken_tables)
        self.tables = {
            "jobs": [{"id": "job-1", "user_id": "user-1"}],
            "user_profiles": [profile or {"id": "user-1", "is_admin": False, "subscription_plan": "pro"}],
        }

    def table(self, name):
        return _Query(self, name)

    def rpc(self, name, _params):
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=self.rpc_results[name]))


def _events(capsys, event="job_failed"):
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    return [line for line in lines if line.get("event") == event]


@pytest.fixture
def client(monkeypatch):
    def install(**kwargs):
        fake = _Client(**kwargs)
        monkeypatch.setattr(job_queue_service, "supabase", lambda: fake)
        return fake
    return install


def test_mark_failed_emits_one_job_failed_line(client, capsys):
    client(rpc_results={"fail_job_secure": True})

    assert JobQueueService.mark_failed("job-1", "boom", "transcription_error")

    [event] = _events(capsys)
    assert {k: event[k] for k in ("event", "job_id", "error_code", "user_tier")} == {
        "event": "job_failed", "job_id": "job-1", "error_code": "transcription_error", "user_tier": "pro",
    }


def test_no_event_when_the_job_was_not_failed(client, capsys):
    client(rpc_results={"fail_job_secure": False, "timeout_job_secure": False})

    JobQueueService.mark_failed("job-1", "boom")
    JobQueueService.mark_worker_timeout("job-1")

    assert _events(capsys) == []


def test_worker_timeout_is_counted(client, capsys):
    client(rpc_results={"timeout_job_secure": True})

    assert JobQueueService.mark_worker_timeout("job-1")

    [event] = _events(capsys)
    assert event["error_code"] == "worker_timeout"


def test_exhausted_continuations_are_counted(client, capsys):
    client(rpc_results={"requeue_job_for_continuation": "exhausted"})

    assert JobQueueService.request_continuation("job-1", 12.0, 12) == "exhausted"

    [event] = _events(capsys)
    assert event["error_code"] == "max_continuations_reached"


def test_continuing_jobs_are_not_counted(client, capsys):
    client(rpc_results={"requeue_job_for_continuation": "continue"})

    JobQueueService.request_continuation("job-1", 12.0, 12)

    assert _events(capsys) == []


def test_admin_jobs_are_tagged_admin(client, capsys):
    client(rpc_results={"fail_job_secure": True},
           profile={"id": "user-1", "is_admin": True, "subscription_plan": "free"})

    JobQueueService.mark_failed("job-1", "boom")

    assert _events(capsys)[0]["user_tier"] == "admin"


def test_a_failed_tier_lookup_still_records_the_failure(client, capsys):
    client(rpc_results={"fail_job_secure": True}, broken_tables={"user_profiles"})

    assert JobQueueService.mark_failed("job-1", "boom", "storage_error")

    [event] = _events(capsys)
    assert event["user_tier"] == "unknown"
    assert event["error_code"] == "storage_error"


def _raise_and_catch():
    try:
        raise ValueError("bad input")
    except ValueError as exc:
        return exc


def test_log_exception_writes_the_whole_trace_as_one_stderr_line(capsys, monkeypatch):
    monkeypatch.setenv("K_SERVICE", "ai-subs-backend")
    monkeypatch.setenv("K_REVISION", "ai-subs-backend-00042")

    structured_log.log_exception(_raise_and_catch(), "Unhandled exception on GET /x", path="/x")

    err = capsys.readouterr().err
    assert err.count("\n") == 1
    entry = json.loads(err)
    assert entry["severity"] == "ERROR"
    assert entry["@type"] == structured_log.REPORTED_ERROR_EVENT_TYPE
    assert entry["serviceContext"] == {"service": "ai-subs-backend", "version": "ai-subs-backend-00042"}
    assert entry["message"].startswith("Unhandled exception on GET /x\nTraceback (most recent call last):")
    assert "ValueError: bad input" in entry["message"]
    assert entry["context"] == {"path": "/x"}


def test_the_worker_marker_is_not_used_as_service_name(monkeypatch):
    monkeypatch.delenv("K_SERVICE", raising=False)
    monkeypatch.setenv("CLOUD_RUN_JOB", "1")
    assert structured_log._service_context()["service"] == "ai-subs-local"
    monkeypatch.setenv("CLOUD_RUN_JOB", "ai-subs-worker")
    assert structured_log._service_context()["service"] == "ai-subs-worker"


def test_excepthooks_report_main_thread_and_thread_crashes(capsys, monkeypatch):
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    structured_log.install_excepthooks("worker")

    exc = _raise_and_catch()
    sys.excepthook(type(exc), exc, exc.__traceback__)
    thread = threading.Thread(target=lambda: 1 / 0, name="heartbeat")
    thread.start()
    thread.join()

    entries = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert entries[0]["message"].startswith("Unhandled exception in worker\n")
    assert entries[1]["message"].startswith("Unhandled exception in worker thread heartbeat\n")
    assert "ZeroDivisionError" in entries[1]["message"]


def test_api_returns_the_default_500_and_reports_the_trace(capsys):
    import asyncio

    import httpx
    from fastapi import FastAPI

    import main

    assert main.app.exception_handlers[Exception] is main.log_unhandled_exception

    # A bare app with the same handler: main.app's middleware needs auth and CSRF setup.
    app = FastAPI()
    app.add_exception_handler(Exception, main.log_unhandled_exception)

    @app.get("/crash")
    async def crash():
        raise RuntimeError("kaboom")

    async def call():
        # Starlette's TestClient needs an older httpx, so go through the ASGI transport.
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            return await http.get("/crash")

    response = asyncio.run(call())

    assert response.status_code == 500
    assert response.text == "Internal Server Error"
    reports = [json.loads(line) for line in capsys.readouterr().err.splitlines() if line.startswith("{")]
    assert any(
        "RuntimeError: kaboom" in r["message"] and r["message"].startswith("Unhandled exception on GET /crash")
        for r in reports
    )
