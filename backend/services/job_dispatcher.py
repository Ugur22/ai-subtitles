"""Runtime-selected background job dispatch boundary."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional, Protocol

from config import settings


class JobDispatchError(RuntimeError):
    pass


class JobDispatcher(Protocol):
    def dispatch(self, job_id: str) -> None: ...


class CloudRunJobDispatcher:
    def __init__(self) -> None:
        if not settings.WORKER_JOB_PROJECT.strip():
            raise JobDispatchError("WORKER_JOB_PROJECT is required")
        if not settings.WORKER_JOB_REGION.strip():
            raise JobDispatchError("WORKER_JOB_REGION is required")
        if not settings.WORKER_JOB_NAME.strip():
            raise JobDispatchError("WORKER_JOB_NAME is required")

    def dispatch(self, job_id: str) -> None:
        try:
            from google.cloud import run_v2
        except ImportError as exc:
            raise JobDispatchError("google-cloud-run is required in production") from exc

        resource = (
            f"projects/{settings.WORKER_JOB_PROJECT}"
            f"/locations/{settings.WORKER_JOB_REGION}"
            f"/jobs/{settings.WORKER_JOB_NAME}"
        )
        overrides = run_v2.RunJobRequest.Overrides(
            container_overrides=[
                run_v2.RunJobRequest.Overrides.ContainerOverride(
                    args=["-m", "worker_main", job_id]
                )
            ]
        )
        try:
            run_v2.JobsClient().run_job(
                request=run_v2.RunJobRequest(name=resource, overrides=overrides)
            )
        except Exception as exc:
            raise JobDispatchError(f"Cloud Run rejected worker dispatch for {job_id}") from exc


class LocalDetachedJobDispatcher:
    def __init__(self, worker_directory: Optional[Path] = None) -> None:
        self.worker_directory = worker_directory or Path(__file__).resolve().parents[1]

    def dispatch(self, job_id: str) -> None:
        env = os.environ.copy()
        env["LOCAL_MODE"] = "true"
        env.pop("CLOUD_RUN_JOB", None)

        # Log to LOCAL_DATA_DIR/logs/worker-<job_id>.log instead of DEVNULL —
        # this is the only way to see worker output in local dev, since the
        # subprocess is detached from the API process.
        logs_dir = os.path.join(os.path.abspath(settings.LOCAL_DATA_DIR), "logs")
        os.makedirs(logs_dir, exist_ok=True)
        log_path = os.path.join(logs_dir, f"worker-{job_id}.log")

        try:
            log_file = open(log_path, "w")
            process = subprocess.Popen(
                [sys.executable, "-m", "worker_main", job_id],
                cwd=str(self.worker_directory),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                close_fds=True,
                start_new_session=True,
            )
            print(f"[JobDispatcher] LOCAL_MODE worker started for {job_id}, log: {log_path}")
            _schedule_reap(process)
        except OSError as exc:
            raise JobDispatchError(f"Could not start local worker for {job_id}") from exc


def _schedule_reap(process: subprocess.Popen) -> None:
    """Reap a detached child without blocking the request process."""
    waiter = threading.Thread(
        target=process.wait,
        name=f"local-worker-reaper-{process.pid}",
        daemon=True,
    )
    waiter.start()


_dispatcher: Optional[JobDispatcher] = None


def get_job_dispatcher() -> JobDispatcher:
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = (
            LocalDetachedJobDispatcher() if settings.LOCAL_MODE else CloudRunJobDispatcher()
        )
    return _dispatcher


def reset_job_dispatcher_for_tests() -> None:
    global _dispatcher
    _dispatcher = None
