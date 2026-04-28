"""
Cloud Run Job entrypoint for the transcription pipeline.

This is invoked as `python -m worker_main <job_id>` by a Cloud Run Job
execution. It runs the pipeline that used to live behind FastAPI's
`BackgroundTasks`, but standalone — no HTTP server, no scale-to-zero risk.

Exit code 0 = success, 1 = failure or cancellation.
"""
import asyncio
import os
import signal
import sys

from dotenv import load_dotenv

load_dotenv()

# Mark this process so heartbeat self-pings and similar Service-only behaviors skip themselves.
os.environ.setdefault("CLOUD_RUN_JOB", "1")

from services.background_worker import background_worker, JobCancelled
from services.job_queue_service import JobQueueService


def _install_sigterm_handler(job_id: str) -> None:
    """Mark the job 'cancelled' on Cloud Run SIGTERM so the cancel-poll loop in process_job notices on the next stage boundary and the row doesn't end up stuck in 'processing'."""

    def _handler(signum, frame):
        print(f"[worker_main] Received signal {signum}; marking job {job_id} cancelled")
        try:
            JobQueueService.cancel_job(job_id)
        except Exception as e:
            print(f"[worker_main] cancel_job failed during SIGTERM handling: {e}")

    signal.signal(signal.SIGTERM, _handler)
    signal.signal(signal.SIGINT, _handler)


async def _run(job_id: str) -> int:
    try:
        ok = await background_worker.process_job(job_id)
        return 0 if ok else 1
    except JobCancelled as e:
        print(f"[worker_main] {e}")
        return 1


def main() -> int:
    if len(sys.argv) < 2:
        print("[worker_main] usage: python -m worker_main <job_id>", file=sys.stderr)
        return 2

    job_id = sys.argv[1].strip()
    if not job_id:
        print("[worker_main] empty job_id", file=sys.stderr)
        return 2

    print(f"[worker_main] starting job {job_id}")
    _install_sigterm_handler(job_id)
    return asyncio.run(_run(job_id))


if __name__ == "__main__":
    sys.exit(main())
