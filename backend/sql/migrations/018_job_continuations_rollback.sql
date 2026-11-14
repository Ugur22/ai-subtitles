-- Rollback for 018_job_continuations.sql.
--
-- Order matters:
--   1. Redeploy the previous backend image first. Code from PR #11 calls
--      requeue_job_for_continuation and reads jobs.gpu_seconds_accumulated.
--   2. Run 019_worker_timeout_retry_rollback.sql (019 depends on 018).
--   3. Run this file.
--
-- claim_job and retry_job_secure are restored to the definitions in
-- migrations 005 and 008. If production ran different definitions before 018
-- was applied, restore those instead of the ones below.
--
-- Data: drops jobs.continuation_count and jobs.gpu_seconds_accumulated. A job
-- that is mid-chain ('pending' with stage 'continuing') is still claimed and
-- processed by the restored claim_job; it resumes from the pipeline_cache
-- checkpoints, which this rollback does not touch.

BEGIN;

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
    status = 'processing', started_at = now(), updated_at = now(), last_seen = now(),
    progress = 0, stage = 'starting', message = 'Job processing started'
  WHERE id = p_job_id AND status = 'pending'
  RETURNING id INTO v_claimed;
  RETURN v_claimed IS NOT NULL;
END;
$$;

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

REVOKE ALL ON FUNCTION retry_job_secure(UUID, UUID, INTEGER, INTEGER)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION retry_job_secure(UUID, UUID, INTEGER, INTEGER)
  TO service_role;

DROP FUNCTION IF EXISTS requeue_job_for_continuation(UUID, INTEGER, NUMERIC);

ALTER TABLE jobs
  DROP COLUMN IF EXISTS continuation_count,
  DROP COLUMN IF EXISTS gpu_seconds_accumulated;

COMMIT;
