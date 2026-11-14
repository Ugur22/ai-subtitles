BEGIN;

-- A file longer than one GPU execution (Cloud Run caps GPU tasks at 1h) is
-- processed by a chain of executions that share one jobs row. These columns
-- track the chain; the per-chunk results live in pipeline_cache.
ALTER TABLE jobs
  ADD COLUMN IF NOT EXISTS continuation_count INTEGER NOT NULL DEFAULT 0
    CHECK (continuation_count >= 0),
  ADD COLUMN IF NOT EXISTS gpu_seconds_accumulated NUMERIC NOT NULL DEFAULT 0
    CHECK (gpu_seconds_accumulated >= 0);

-- Hand a processing job back to the queue for the next execution. The quota
-- reservation is deliberately left untouched: a continuation is the same job,
-- so it must not be re-reserved, re-counted against concurrency (it stays
-- 'pending', which already counts for the owner), or settled twice.
CREATE OR REPLACE FUNCTION requeue_job_for_continuation(
  p_job_id UUID,
  p_max_continuations INTEGER,
  p_gpu_seconds NUMERIC
) RETURNS TEXT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_job jobs%ROWTYPE;
  v_user_id UUID;
  v_gpu NUMERIC := GREATEST(COALESCE(p_gpu_seconds, 0), 0);
BEGIN
  SELECT user_id INTO v_user_id FROM jobs WHERE id = p_job_id;
  IF NOT FOUND OR v_user_id IS NULL THEN RETURN 'not_processing'; END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended(v_user_id::text, 0));
  SELECT * INTO v_job FROM jobs
  WHERE id = p_job_id AND user_id = v_user_id FOR UPDATE;
  IF NOT FOUND OR v_job.status <> 'processing' THEN RETURN 'not_processing'; END IF;

  IF v_job.continuation_count >= GREATEST(COALESCE(p_max_continuations, 0), 0) THEN
    IF v_job.quota_reserved_seconds > 0 THEN
      IF v_job.quota_reservation_period IS NULL THEN
        RAISE EXCEPTION 'job quota reservation is missing its period';
      END IF;
      UPDATE user_usage_monthly SET
        reserved_transcription_seconds = GREATEST(
          reserved_transcription_seconds - v_job.quota_reserved_seconds, 0
        ), updated_at = now()
      WHERE user_id = v_user_id AND period_start = v_job.quota_reservation_period;
      IF NOT FOUND THEN RAISE EXCEPTION 'job quota ledger row is missing'; END IF;
    END IF;
    UPDATE jobs SET
      status = 'failed', stage = 'failed',
      message = 'This file needed more processing runs than allowed.',
      error_code = 'max_continuations_reached',
      error_message = 'This file needed more processing runs than allowed.',
      quota_reserved_seconds = 0, quota_reservation_period = NULL,
      gpu_seconds_accumulated = gpu_seconds_accumulated + v_gpu,
      failed_at = now(), updated_at = now(), last_seen = now()
    WHERE id = p_job_id AND status = 'processing';
    RETURN 'exhausted';
  END IF;

  UPDATE jobs SET
    status = 'pending', stage = 'continuing',
    message = format('Continuing in a new worker (part %s)', v_job.continuation_count + 2),
    continuation_count = v_job.continuation_count + 1,
    gpu_seconds_accumulated = gpu_seconds_accumulated + v_gpu,
    updated_at = now(), last_seen = now()
  WHERE id = p_job_id AND status = 'processing';
  RETURN 'continue';
END;
$$;

-- Same claim as migration 005, except a continuation keeps the original
-- started_at and its progress instead of restarting from zero.
CREATE OR REPLACE FUNCTION claim_job(p_job_id UUID, p_global_processing_limit INTEGER)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_claimed UUID;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtextextended('jobs:global-processing', 0));
  IF p_global_processing_limit IS NOT NULL
     AND (SELECT count(*) FROM jobs WHERE status = 'processing') >= p_global_processing_limit THEN
    RETURN FALSE;
  END IF;
  UPDATE jobs SET
    status = 'processing', updated_at = now(), last_seen = now(),
    started_at = CASE
      WHEN continuation_count > 0 THEN COALESCE(started_at, now()) ELSE now()
    END,
    progress = CASE WHEN continuation_count > 0 THEN progress ELSE 0 END,
    stage = 'starting',
    message = CASE
      WHEN continuation_count > 0 THEN 'Resuming from checkpoint'
      ELSE 'Job processing started'
    END
  WHERE id = p_job_id AND status = 'pending'
  RETURNING id INTO v_claimed;
  RETURN v_claimed IS NOT NULL;
END;
$$;

-- Same as migration 008, plus: a manual retry starts a fresh continuation
-- chain. Without the reset a job that failed with max_continuations_reached
-- would fail again on its first hand-off.
CREATE OR REPLACE FUNCTION retry_job_secure(
  p_job_id UUID,
  p_user_id UUID,
  p_max_retries INTEGER,
  p_user_concurrent_limit INTEGER
) RETURNS SETOF jobs
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_job jobs%ROWTYPE;
  v_active INTEGER;
  v_cleanup media_delete_outbox%ROWTYPE;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtextextended(p_user_id::text, 0));
  SELECT * INTO v_job FROM jobs
  WHERE id = p_job_id AND user_id = p_user_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'job_not_found';
  END IF;
  IF v_job.status <> 'failed' THEN
    RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'job_not_retryable';
  END IF;
  IF COALESCE(v_job.retry_count, 0) >= p_max_retries
     AND v_job.error_code IS DISTINCT FROM 'finalization_retries_exhausted' THEN
    RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'max_retries_reached';
  END IF;

  IF v_job.final_media_key IS NOT NULL THEN
    SELECT * INTO v_cleanup FROM media_delete_outbox
    WHERE media_key = v_job.final_media_key FOR UPDATE;
    IF FOUND AND v_cleanup.status <> 'completed' THEN
      RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'finalization_cleanup_pending';
    END IF;
    IF FOUND THEN
      DELETE FROM media_delete_outbox WHERE id = v_cleanup.id;
    END IF;
  END IF;

  IF p_user_concurrent_limit IS NOT NULL THEN
    SELECT count(*) INTO v_active FROM jobs
    WHERE user_id = p_user_id
      AND status IN ('pending', 'processing', 'finalizing');
    IF v_active >= p_user_concurrent_limit THEN
      RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'user_concurrent_limit_reached';
    END IF;
  END IF;

  UPDATE jobs SET
    status = 'pending', stage = 'queued', message = 'Job queued for retry',
    error_code = NULL, error_message = NULL, failed_at = NULL,
    result_json = NULL, result_srt = NULL, result_vtt = NULL,
    final_media_key = NULL, finalization_started_at = NULL,
    completed_at = NULL, quota_reserved_seconds = 0,
    quota_reservation_period = NULL,
    continuation_count = 0,
    retry_count = CASE
      WHEN v_job.error_code = 'finalization_retries_exhausted' THEN 0
      ELSE COALESCE(v_job.retry_count, 0) + 1
    END,
    updated_at = now(), last_seen = now()
  WHERE id = p_job_id AND user_id = p_user_id AND status = 'failed'
  RETURNING * INTO v_job;
  IF NOT FOUND THEN
    RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'retry_compare_and_set_failed';
  END IF;
  RETURN NEXT v_job;
END;
$$;

REVOKE ALL ON FUNCTION requeue_job_for_continuation(UUID, INTEGER, NUMERIC)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION requeue_job_for_continuation(UUID, INTEGER, NUMERIC)
  TO service_role;

COMMIT;
