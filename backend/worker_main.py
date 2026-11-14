"""
Cloud Run Job entrypoint for the transcription pipeline.

This is invoked as `python -m worker_main <job_id>` by a Cloud Run Job
execution. It runs the pipeline that used to live behind FastAPI's
`BackgroundTasks`, but standalone — no HTTP server, no scale-to-zero risk.

Exit code 0 = success or a clean hand-over to a continuation execution,
1 = failure or cancellation.
"""
import asyncio
import os
import signal
import sys
import time

# The task timeout counts from container start, so the budget clock starts
# before the heavy imports and model loading below.
_PROCESS_STARTED_AT = time.monotonic()

from dotenv import load_dotenv

load_dotenv()

# Mark the execution environment without conflating local detached workers with
# Cloud Run Jobs.
if os.environ.get("LOCAL_MODE", "false").lower() == "true":
    os.environ.setdefault("LOCAL_DETACHED_WORKER", "1")
else:
    os.environ.setdefault("CLOUD_RUN_JOB", "1")

from config import settings

settings.validate_runtime()

from services.background_worker import background_worker, JobCancelled
from services.job_queue_service import JobQueueService
from services.media_storage import get_media_storage
from services.transcription_checkpoint import TimeBudget, resolve_budget_seconds


def _on_sigterm(job_id: str) -> None:
    """Cloud Run sends SIGTERM when the task timeout is reached, ~10s before SIGKILL.

    That is a failure, not a cancellation: the job becomes failed/worker_timeout
    so check-stale can retry it once from the chunk cache. mark_worker_timeout
    only touches a job that is still 'processing', so a job the user cancelled
    stays 'cancelled' and a job already handed to a continuation stays 'pending'.
    Either way the pipeline's next cancel check sees the status change and stops.
    """
    print(f"[worker_main] Received SIGTERM; treating job {job_id} as a worker timeout")
    if not JobQueueService.mark_worker_timeout(job_id):
        print(f"[worker_main] Job {job_id} was not processing; left as is")


def _on_sigint(job_id: str) -> None:
    """Ctrl-C on a local worker is a deliberate stop, so it stays a cancellation."""
    print(f"[worker_main] Received SIGINT; marking job {job_id} cancelled")
    try:
        JobQueueService.cancel_job(job_id)
    except Exception as e:
        print(f"[worker_main] cancel_job failed during SIGINT handling: {e}")


def _install_signal_handlers(job_id: str) -> None:
    signal.signal(signal.SIGTERM, lambda signum, frame: _on_sigterm(job_id))
    signal.signal(signal.SIGINT, lambda signum, frame: _on_sigint(job_id))


def _check_gpu(job_id: str) -> bool:
    """Log GPU/Whisper setup; fail fast if CUDA was requested but isn't usable instead of silently running on CPU."""
    import torch
    from dependencies import resolve_whisper_compute_type

    cuda_ok = torch.cuda.is_available()
    gpu_name = torch.cuda.get_device_name(0) if cuda_ok else "n/a"
    print(
        f"[worker_main] cuda_available={cuda_ok} gpu={gpu_name} torch_cuda={torch.version.cuda} "
        f"whisper_model={settings.FASTWHISPER_MODEL} device={settings.FASTWHISPER_DEVICE} "
        f"compute_type={resolve_whisper_compute_type()}"
    )

    if settings.FASTWHISPER_DEVICE == "cuda" and not cuda_ok:
        message = "FASTWHISPER_DEVICE=cuda but CUDA is not available in this worker (check GPU allocation and CUDA/cuDNN libraries)"
        print(f"[worker_main] ERROR: {message}", file=sys.stderr)
        JobQueueService.mark_failed(job_id, message, "gpu_unavailable")
        return False
    return True


async def _run(job_id: str) -> int:
    try:
        await asyncio.to_thread(
            JobQueueService.drain_media_deletions_best_effort,
            storage=get_media_storage(),
            limit=10,
        )
        budget_seconds = resolve_budget_seconds(
            settings.WORKER_TIME_BUDGET_SECONDS, settings.CLOUD_RUN_TASK_TIMEOUT
        )
        print(f"[worker_main] time budget for this execution: {budget_seconds}s")
        ok = await background_worker.process_job(
            job_id, time_budget=TimeBudget(budget_seconds, started_at=_PROCESS_STARTED_AT)
        )
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
    if not _check_gpu(job_id):
        return 1
    _install_signal_handlers(job_id)
    return asyncio.run(_run(job_id))


if __name__ == "__main__":
    sys.exit(main())
