BEGIN;

-- Requires migration 018 (continuation_count).
ALTER TABLE jobs
  ADD COLUMN IF NOT EXISTS timeout_auto_retries INTEGER NOT NULL DEFAULT 0
    CHECK (timeout_auto_retries >= 0);

CREATE INDEX IF NOT EXISTS idx_jobs_worker_timeout
  ON jobs (failed_at)
  WHERE status = 'failed' AND error_code = 'worker_timeout';

-- Called from the worker's SIGTERM handler. Only a job that is still
-- 'processing' becomes a timeout: a job the user cancelled stays 'cancelled',
-- a job already handed over to a continuation stays 'pending', and a
-- 'finalizing' job is left to claim_stale_finalizing_job.
CREATE OR REPLACE FUNCTION timeout_job_secure(p_job_id UUID, p_error_message TEXT)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_job jobs%ROWTYPE;
  v_user_id UUID;
BEGIN
  SELECT user_id INTO v_user_id FROM jobs WHERE id = p_job_id;
  IF NOT FOUND OR v_user_id IS NULL THEN RETURN FALSE; END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended(v_user_id::text, 0));
  SELECT * INTO v_job FROM jobs
  WHERE id = p_job_id AND user_id = v_user_id FOR UPDATE;
  IF NOT FOUND OR v_job.status <> 'processing' THEN RETURN FALSE; END IF;
  IF v_job.quota_reserved_seconds > 0 AND v_job.quota_reservation_period IS NULL THEN
    RETURN FALSE;
  END IF;
  IF v_job.quota_reserved_seconds > 0 THEN
    UPDATE user_usage_monthly SET
      reserved_transcription_seconds = GREATEST(
        reserved_transcription_seconds - v_job.quota_reserved_seconds, 0
      ), updated_at = now()
    WHERE user_id = v_user_id AND period_start = v_job.quota_reservation_period;
    IF NOT FOUND THEN RETURN FALSE; END IF;
  END IF;
  UPDATE jobs SET
    status = 'failed', stage = 'failed', message = p_error_message,
    error_code = 'worker_timeout', error_message = p_error_message,
    quota_reserved_seconds = 0, quota_reservation_period = NULL,
    failed_at = now(), updated_at = now(), last_seen = now()
  WHERE id = p_job_id AND status = 'processing';
  RETURN FOUND;
END;
$$;

-- One automatic retry per job after a worker timeout. The row lock plus the
-- status/error_code/counter predicate make this a compare-and-set: of any
-- number of concurrent check-stale runs, exactly one gets TRUE and dispatches.
-- continuation_count is kept, so the retry counts against the same chain.
CREATE OR REPLACE FUNCTION auto_retry_timed_out_job(
  p_job_id UUID,
  p_user_id UUID,
  p_max_retries INTEGER,
  p_user_concurrent_limit INTEGER
) RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_job jobs%ROWTYPE;
  v_active INTEGER;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtextextended(p_user_id::text, 0));
  SELECT * INTO v_job FROM jobs
  WHERE id = p_job_id AND user_id = p_user_id FOR UPDATE;
  IF NOT FOUND
     OR v_job.status <> 'failed'
     OR v_job.error_code IS DISTINCT FROM 'worker_timeout'
     OR v_job.timeout_auto_retries >= 1
     OR COALESCE(v_job.retry_count, 0) >= p_max_retries THEN
    RETURN FALSE;
  END IF;

  IF p_user_concurrent_limit IS NOT NULL THEN
    SELECT count(*) INTO v_active FROM jobs
    WHERE user_id = p_user_id
      AND status IN ('pending', 'processing', 'finalizing');
    -- Not consumed: the next check-stale run tries again once a slot is free.
    IF v_active >= p_user_concurrent_limit THEN RETURN FALSE; END IF;
  END IF;

  UPDATE jobs SET
    status = 'pending', stage = 'queued',
    message = 'Retrying automatically after a worker timeout',
    error_code = NULL, error_message = NULL, failed_at = NULL,
    quota_reserved_seconds = 0, quota_reservation_period = NULL,
    retry_count = COALESCE(v_job.retry_count, 0) + 1,
    timeout_auto_retries = v_job.timeout_auto_retries + 1,
    updated_at = now(), last_seen = now()
  WHERE id = p_job_id AND user_id = p_user_id
    AND status = 'failed' AND error_code = 'worker_timeout'
    AND timeout_auto_retries < 1;
  RETURN FOUND;
END;
$$;

REVOKE ALL ON FUNCTION timeout_job_secure(UUID, TEXT)
  FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION auto_retry_timed_out_job(UUID, UUID, INTEGER, INTEGER)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION timeout_job_secure(UUID, TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION auto_retry_timed_out_job(UUID, UUID, INTEGER, INTEGER)
  TO service_role;

COMMIT;
