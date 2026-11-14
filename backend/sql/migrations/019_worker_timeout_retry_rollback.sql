-- Rollback for 019_worker_timeout_retry.sql.
--
-- Order matters:
--   1. Redeploy the previous backend image first. Code from PR #11 calls these
--      functions from the SIGTERM handler and from check-stale.
--   2. Run this file.
--   3. Only then run 018_job_continuations_rollback.sql, if 018 is going too.
--
-- Data: drops jobs.timeout_auto_retries (the "already auto-retried" marker).
-- Jobs that failed with error_code 'worker_timeout' stay failed and can still
-- be retried manually.

BEGIN;

DROP FUNCTION IF EXISTS auto_retry_timed_out_job(UUID, UUID, INTEGER, INTEGER);
DROP FUNCTION IF EXISTS timeout_job_secure(UUID, TEXT);
DROP INDEX IF EXISTS idx_jobs_worker_timeout;
ALTER TABLE jobs DROP COLUMN IF EXISTS timeout_auto_retries;

COMMIT;
