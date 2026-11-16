-- Rollback for 021_gpu_slot_wait.sql.
--
-- Order matters:
--   1. Redeploy the previous backend image first. The new code calls
--      claim_job_with_outcome and claim_waiting_for_gpu_job.
--   2. Run this file.
--
-- claim_job is restored to its migration 018 definition. Jobs parked as
-- 'waiting_for_gpu' go back to 'queued'; the old check-stale recovers them as
-- stuck pending jobs (that path does count a retry).

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

UPDATE jobs SET stage = 'queued', message = 'Job queued', updated_at = now()
WHERE status = 'pending' AND stage = 'waiting_for_gpu';

DROP FUNCTION IF EXISTS claim_waiting_for_gpu_job(INTEGER);
DROP FUNCTION IF EXISTS claim_job_with_outcome(UUID, INTEGER);
DROP INDEX IF EXISTS idx_jobs_waiting_for_gpu;

COMMIT;
