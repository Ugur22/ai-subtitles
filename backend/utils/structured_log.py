"""One-line JSON logs that Cloud Logging parses into jsonPayload.

Cloud Run turns each stdout/stderr line into its own log entry, so a multi-line
traceback becomes dozens of entries that Error Reporting cannot group. Writing
the whole event as a single JSON line keeps it one entry, which log-based
metrics (job_failed) and Error Reporting (log_exception) both rely on.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import traceback
from typing import Any, Optional, TextIO

# Error Reporting picks up any ERROR entry whose message holds a stack trace;
# this @type makes it also pick up entries it would otherwise not recognise.
REPORTED_ERROR_EVENT_TYPE = (
    "type.googleapis.com/google.devtools.clouderrorreporting.v1beta1.ReportedErrorEvent"
)


def _service_context() -> dict:
    # K_SERVICE is set on Cloud Run Services, CLOUD_RUN_JOB on Job executions;
    # worker_main sets CLOUD_RUN_JOB=1 as a marker when Cloud Run has not.
    job = os.environ.get("CLOUD_RUN_JOB", "")
    service = os.environ.get("K_SERVICE") or (job if job not in ("", "1") else "") or "ai-subs-local"
    version = os.environ.get("K_REVISION") or os.environ.get("CLOUD_RUN_EXECUTION") or ""
    context = {"service": service}
    if version:
        context["version"] = version
    return context


def _write(payload: dict, stream: TextIO) -> None:
    stream.write(json.dumps(payload, default=str) + "\n")
    stream.flush()


def log_event(event: str, severity: str = "INFO", **fields: Any) -> None:
    """Write one structured event to stdout, e.g. log_event("job_failed", job_id=...)."""
    _write({"severity": severity, "event": event, "message": event, **fields}, sys.stdout)


def log_exception(
    exc: BaseException,
    message: Optional[str] = None,
    **context: Any,
) -> None:
    """Write an exception with its full stack trace to stderr as one entry for Error Reporting."""
    trace = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    payload = {
        "severity": "ERROR",
        "@type": REPORTED_ERROR_EVENT_TYPE,
        "serviceContext": _service_context(),
        # Error Reporting parses the stack trace from the message; a prefix line is allowed.
        "message": f"{message}\n{trace}" if message else trace,
    }
    if context:
        payload["context"] = context
    try:
        _write(payload, sys.stderr)
    except Exception:
        # Logging must never mask the original error.
        traceback.print_exception(type(exc), exc, exc.__traceback__)


def install_excepthooks(process: str) -> None:
    """Route uncaught exceptions in the main thread and in threads through log_exception."""

    def _main_hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        log_exception(exc.with_traceback(tb), f"Unhandled exception in {process}")

    def _thread_hook(args: threading.ExceptHookArgs):
        if args.exc_type is SystemExit or args.exc_value is None:
            return
        thread_name = args.thread.name if args.thread else "unknown"
        log_exception(
            args.exc_value.with_traceback(args.exc_traceback),
            f"Unhandled exception in {process} thread {thread_name}",
        )

    sys.excepthook = _main_hook
    threading.excepthook = _thread_hook
