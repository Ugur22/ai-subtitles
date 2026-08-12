BEGIN;

ALTER TABLE media_delete_outbox
  ADD COLUMN IF NOT EXISTS available_at TIMESTAMPTZ NOT NULL DEFAULT now();

CREATE INDEX IF NOT EXISTS idx_media_delete_outbox_available
  ON media_delete_outbox (status, available_at, created_at);

CREATE OR REPLACE FUNCTION claim_media_deletes(
  p_limit INTEGER DEFAULT 10,
  p_outbox_id UUID DEFAULT NULL
) RETURNS SETOF media_delete_outbox
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  RETURN QUERY
  WITH candidates AS (
    SELECT id
    FROM media_delete_outbox
    WHERE (p_outbox_id IS NULL OR id = p_outbox_id)
      AND available_at <= now()
      AND (
        status = 'pending'
        OR (status = 'processing' AND claimed_at < now() - interval '10 minutes')
      )
    ORDER BY available_at, created_at
    FOR UPDATE SKIP LOCKED
    LIMIT LEAST(GREATEST(COALESCE(p_limit, 10), 1), 100)
  )
  UPDATE media_delete_outbox AS outbox
  SET status = 'processing', claimed_at = now(),
      attempt_count = outbox.attempt_count + 1, updated_at = now()
  FROM candidates
  WHERE outbox.id = candidates.id
  RETURNING outbox.*;
END;
$$;

CREATE OR REPLACE FUNCTION claim_stale_finalizing_job(
  p_cutoff TIMESTAMPTZ,
  p_max_retries INTEGER
) RETURNS TABLE(job_id UUID, action TEXT, retry_count INTEGER)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_candidate RECORD;
  v_job jobs%ROWTYPE;
  v_destination_references INTEGER := 0;
  v_retry_count INTEGER;
BEGIN
  SELECT id, user_id INTO v_candidate
  FROM jobs
  WHERE status = 'finalizing' AND last_seen < p_cutoff
  ORDER BY last_seen
  LIMIT 1;
  IF NOT FOUND THEN RETURN; END IF;

  PERFORM pg_advisory_xact_lock(hashtextextended(v_candidate.user_id::text, 0));
  SELECT * INTO v_job FROM jobs
  WHERE id = v_candidate.id AND user_id = v_candidate.user_id
    AND status = 'finalizing' AND last_seen < p_cutoff
  FOR UPDATE;
  IF NOT FOUND THEN RETURN; END IF;

  IF COALESCE(v_job.retry_count, 0) >= GREATEST(COALESCE(p_max_retries, 0), 0) THEN
    IF v_job.final_media_key IS NOT NULL
       AND v_job.final_media_key LIKE ('processed/' || v_job.user_id::text || '/%') THEN
      PERFORM pg_advisory_xact_lock(
        hashtextextended('media-key:' || v_job.final_media_key, 0)
      );
      SELECT count(*) INTO v_destination_references
      FROM jobs WHERE gcs_path = v_job.final_media_key;
      IF v_destination_references = 0 THEN
        INSERT INTO media_delete_outbox (
          source_job_id, user_id, media_key, available_at
        ) VALUES (
          v_job.id, v_job.user_id, v_job.final_media_key,
          now() + interval '10 minutes'
        ) ON CONFLICT (media_key) DO NOTHING;
      END IF;
    END IF;

    IF COALESCE(v_job.quota_reserved_seconds, 0) > 0 THEN
      IF v_job.quota_reservation_period IS NULL THEN
        RAISE EXCEPTION 'job quota reservation is missing its period';
      END IF;
      UPDATE user_usage_monthly SET
        reserved_transcription_seconds = GREATEST(
          reserved_transcription_seconds - v_job.quota_reserved_seconds, 0
        ), updated_at = now()
      WHERE user_id = v_job.user_id
        AND period_start = v_job.quota_reservation_period;
      IF NOT FOUND THEN RAISE EXCEPTION 'job quota ledger row is missing'; END IF;
    END IF;

    UPDATE jobs SET
      status = 'failed', stage = 'failed',
      message = 'Media finalization could not be recovered. Retry manually.',
      error_code = 'finalization_retries_exhausted',
      error_message = 'Media finalization retries exhausted',
      quota_reserved_seconds = 0, quota_reservation_period = NULL,
      failed_at = now(), updated_at = now(), last_seen = now()
    WHERE id = v_job.id AND status = 'finalizing';
    RETURN QUERY SELECT v_job.id, 'failed'::TEXT, COALESCE(v_job.retry_count, 0);
    RETURN;
  END IF;

  UPDATE jobs SET
    retry_count = COALESCE(jobs.retry_count, 0) + 1,
    message = 'Recovering interrupted media finalization',
    updated_at = now(), last_seen = now()
  WHERE id = v_job.id AND status = 'finalizing'
  RETURNING jobs.retry_count INTO v_retry_count;
  IF NOT FOUND THEN RETURN; END IF;
  RETURN QUERY SELECT v_job.id, 'redispatch'::TEXT, v_retry_count;
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

REVOKE ALL ON FUNCTION claim_stale_finalizing_job(TIMESTAMPTZ, INTEGER)
  FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION retry_job_secure(UUID, UUID, INTEGER, INTEGER)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION claim_stale_finalizing_job(TIMESTAMPTZ, INTEGER)
  TO service_role;
GRANT EXECUTE ON FUNCTION retry_job_secure(UUID, UUID, INTEGER, INTEGER)
  TO service_role;

COMMIT;
