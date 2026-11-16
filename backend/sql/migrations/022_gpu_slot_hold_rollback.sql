-- Rollback for 022_gpu_slot_hold.sql.
--
-- Order matters:
--   1. Redeploy the previous backend image first. The new code calls
--      park_job_if_no_gpu_slot before every dispatch.
--   2. Run this file.
--
-- requeue_job_for_continuation is restored to migration 018 and
-- claim_job_with_outcome to migration 021, which key the slot bypass on
-- stage = 'continuing' again.

BEGIN;

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

CREATE OR REPLACE FUNCTION claim_job_with_outcome(
  p_job_id UUID,
  p_global_processing_limit INTEGER
) RETURNS TEXT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_job jobs%ROWTYPE;
  v_claimed UUID;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtextextended('jobs:global-processing', 0));
  SELECT * INTO v_job FROM jobs WHERE id = p_job_id;
  IF NOT FOUND OR v_job.status <> 'pending' THEN RETURN 'not_pending'; END IF;

  IF p_global_processing_limit IS NOT NULL
     AND NOT (v_job.continuation_count > 0 AND v_job.stage = 'continuing')
     AND (SELECT count(*) FROM jobs WHERE status = 'processing') >= p_global_processing_limit THEN
    RETURN 'at_capacity';
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
  IF v_claimed IS NULL THEN RETURN 'not_pending'; END IF;
  RETURN 'claimed';
END;
$$;

DROP FUNCTION IF EXISTS park_job_if_no_gpu_slot(UUID, INTEGER);
DROP TRIGGER IF EXISTS jobs_release_gpu_slot_hold ON jobs;
DROP FUNCTION IF EXISTS jobs_release_gpu_slot_hold();
ALTER TABLE jobs DROP COLUMN IF EXISTS holds_gpu_slot;

COMMIT;
