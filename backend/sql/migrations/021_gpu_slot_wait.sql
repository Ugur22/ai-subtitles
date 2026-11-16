BEGIN;

-- Requires migration 018 (continuation_count).
-- Rollback: 021_gpu_slot_wait_rollback.sql
--
-- 1. A continuation is not blocked by the global processing limit. It held a
--    slot until requeue_job_for_continuation released it a moment ago, so a
--    new job that took the slot in between pushes the count over the limit
--    only until one of them finishes.
-- 2. The claim reports why it refused, so a worker that finds no free slot can
--    park the job as 'waiting_for_gpu' instead of being treated as a failed
--    start that costs a retry.

CREATE INDEX IF NOT EXISTS idx_jobs_waiting_for_gpu
  ON jobs (created_at)
  WHERE status = 'pending' AND stage = 'waiting_for_gpu';

-- Returns 'claimed', 'at_capacity' (only the global limit refused it) or
-- 'not_pending'. The pending check comes first so a cancelled or finished job
-- is never reported as waiting for a slot.
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

-- Kept for callers that only need yes/no (the image deployed before this
-- migration); grants from migration 005 carry over.
CREATE OR REPLACE FUNCTION claim_job(p_job_id UUID, p_global_processing_limit INTEGER)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  RETURN claim_job_with_outcome(p_job_id, p_global_processing_limit) = 'claimed';
END;
$$;

-- Picks the oldest job parked as 'waiting_for_gpu' once a slot is free and
-- moves it back to 'queued' for dispatch. retry_count is untouched: waiting
-- for a slot is not a failed start. The global lock serialises concurrent
-- check-stale runs and the stage predicate is the compare-and-set, so a job is
-- handed out once. If the dispatched worker never starts, the job is an
-- ordinary stuck 'queued' pending job and goes through the retry path.
CREATE OR REPLACE FUNCTION claim_waiting_for_gpu_job(p_global_processing_limit INTEGER)
RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_job_id UUID;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtextextended('jobs:global-processing', 0));
  IF p_global_processing_limit IS NOT NULL
     AND (SELECT count(*) FROM jobs WHERE status = 'processing') >= p_global_processing_limit THEN
    RETURN NULL;
  END IF;

  UPDATE jobs SET
    stage = 'queued', message = 'Starting on a free GPU slot',
    updated_at = now(), last_seen = now()
  WHERE id = (
    SELECT id FROM jobs
    WHERE status = 'pending' AND stage = 'waiting_for_gpu'
    ORDER BY created_at, id
    LIMIT 1
    FOR UPDATE SKIP LOCKED
  ) AND status = 'pending' AND stage = 'waiting_for_gpu'
  RETURNING id INTO v_job_id;
  RETURN v_job_id;
END;
$$;

REVOKE ALL ON FUNCTION claim_job_with_outcome(UUID, INTEGER)
  FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION claim_waiting_for_gpu_job(INTEGER)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION claim_job_with_outcome(UUID, INTEGER) TO service_role;
GRANT EXECUTE ON FUNCTION claim_waiting_for_gpu_job(INTEGER) TO service_role;

COMMIT;
