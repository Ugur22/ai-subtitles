BEGIN;

-- Requires migrations 018 and 021.
-- Rollback: 022_gpu_slot_hold_rollback.sql

-- Set only by a continuation hand-over. The trigger below clears it whenever
-- the job leaves 'pending', so a later retry of a failed job never inherits it.
ALTER TABLE jobs
  ADD COLUMN IF NOT EXISTS holds_gpu_slot BOOLEAN NOT NULL DEFAULT false;

UPDATE jobs SET holds_gpu_slot = true
WHERE status = 'pending' AND stage = 'continuing' AND continuation_count > 0;

CREATE OR REPLACE FUNCTION jobs_release_gpu_slot_hold()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = public
AS $$
BEGIN
  NEW.holds_gpu_slot := false;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS jobs_release_gpu_slot_hold ON jobs;
CREATE TRIGGER jobs_release_gpu_slot_hold
  BEFORE UPDATE ON jobs
  FOR EACH ROW
  WHEN (NEW.holds_gpu_slot AND NEW.status IS DISTINCT FROM 'pending')
  EXECUTE FUNCTION jobs_release_gpu_slot_hold();

-- Called before dispatching a worker and from the claim, so a job that finds
-- every slot taken is parked in the same transaction that decided so.
CREATE OR REPLACE FUNCTION park_job_if_no_gpu_slot(
  p_job_id UUID,
  p_global_processing_limit INTEGER
) RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  IF p_global_processing_limit IS NULL THEN RETURN FALSE; END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended('jobs:global-processing', 0));
  UPDATE jobs SET
    stage = 'waiting_for_gpu', message = 'Waiting for a free GPU slot',
    updated_at = now(), last_seen = now()
  WHERE id = p_job_id AND status = 'pending' AND NOT holds_gpu_slot
    AND (SELECT count(*) FROM jobs WHERE status = 'processing') >= p_global_processing_limit;
  RETURN FOUND;
END;
$$;

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
    holds_gpu_slot = true,
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

  IF park_job_if_no_gpu_slot(p_job_id, p_global_processing_limit) THEN
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

REVOKE ALL ON FUNCTION park_job_if_no_gpu_slot(UUID, INTEGER)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION park_job_if_no_gpu_slot(UUID, INTEGER) TO service_role;

COMMIT;
