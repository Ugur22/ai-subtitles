---
paths:
  - "backend/worker_main.py"
  - "backend/services/job_queue_service.py"
  - "backend/services/job_dispatcher.py"
  - "backend/services/background_worker.py"
  - "backend/services/transcription_checkpoint.py"
  - "backend/services/pipeline_cache_service.py"
  - "backend/services/db_retry.py"
  - "backend/routers/jobs.py"
  - "backend/speaker_diarization.py"
  - "backend/tests/test_gpu_slot_wait.py"
  - "backend/tests/test_worker_timeout.py"
  - "backend/tests/test_transcription_checkpoint.py"
  - "backend/tests/test_job*.py"
  - "backend/tests/invariants/**"
---

# Worker and job rules

The job queue, the dispatcher, the worker and the GPU slot are Sensitive (`tools/harness/risk.py`): `advisor` on the plan first. How long jobs flow: "Long files" in `docs/ARCHITECTURE.md`; operations and settings: "Long jobs, continuations and timeouts" in `docs/GCP_OPERATIONS.md`.

## Flow
- The CPU Service creates the job and dispatches a Cloud Run Job execution (`job_dispatcher.py`); `worker_main.py` runs the pipeline (`background_worker.py`). Exit 0 means success, a clean hand-over to a continuation, or no free GPU slot; exit 1 means failure or cancellation.
- Claims, parking, continuations and cancellation are SQL functions (`claim_job_with_outcome`, `park_job_if_no_gpu_slot`, `requeue_job_for_continuation`, `cancel_job_secure`) that decide the status change in one transaction; changing one is a migration (`.claude/rules/database-and-migrations.md`).

## Retries and idempotency
- Each worker step is safe to run twice (retries, redelivery, a repeated RPC after a dropped connection, as `request_continuation` handles). No status transition is skipped or left half-written.
- The worker's Supabase reads go through `with_db_retry` (`db_retry.py`), so a dropped connection does not read as a cache miss or a missing job.

## Checkpoints, continuations and cache keys
- Long files are checkpointed per 5-minute chunk in `pipeline_cache` and continued in a new execution of the same job (`transcription_checkpoint.py`, migration 018). A continuation goes back to `pending` (stage `continuing`), keeps its quota reservation and is capped by `MAX_JOB_CONTINUATIONS`.
- A cache stage key includes a hash of every setting that changes its output (model, language, chunk length, decoding settings; for diarization `_diarization_param_key`). When you add such a setting, add it to the key, so stale results are never reused (`test_diarization_cache_key.py`).

## Cancellation, heartbeats and stale jobs
- Call `_check_cancelled(job_id)` between pipeline stages; `JobCancelled` and `ContinuationRequested` are not failures.
- The heartbeat thread (`HeartbeatThread`) runs outside the event loop for the whole pipeline and is stopped in `finally`.
- `check_and_recover_stale_jobs` recovers one stuck job per call (stale `finalizing` or `processing`, the one automatic `worker_timeout` retry, `waiting_for_gpu`, stranded `pending`) and re-dispatches it. A worker crash leaves the job `processing` on purpose so this can retry it.

## GPU slot and GPU memory
- A slot taken with `holds_gpu_slot` must be released on every exit path, errors and cancellation included. The release is the `jobs_release_gpu_slot_hold` trigger (migration 022) when the status leaves `pending`; never bypass it with a direct column write.
- Free GPU models after use the way `translation_service.py` does (`del`, `gc.collect()`, `torch.cuda.empty_cache()`), and keep torch imports inside functions (`.claude/rules/backend.md`).

## Tests
- `backend/tests/invariants/` holds protected worker-lifecycle and ownership tests: add new files, never change or remove existing ones.
- `*_postgres.py` tests need `TEST_DATABASE_URL` and are skipped by `make check`; say so when a change depends on them.
