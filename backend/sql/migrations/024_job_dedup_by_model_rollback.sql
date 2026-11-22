-- Rollback for 024_job_dedup_by_model.sql: restores create_job_secure from 005,
-- which dedups on (user_id, video_hash) only. The previous backend image works
-- with either version, so the order of redeploy and rollback doesn't matter.

BEGIN;

CREATE OR REPLACE FUNCTION create_job_secure(
  p_job_id UUID,
  p_access_token UUID,
  p_user_id UUID,
  p_filename TEXT,
  p_gcs_path TEXT,
  p_file_size_bytes BIGINT,
  p_video_hash TEXT,
  p_duration_seconds INTEGER,
  p_params JSONB,
  p_estimated_duration_seconds INTEGER,
  p_monthly_limit_seconds INTEGER,
  p_user_concurrent_limit INTEGER,
  p_global_processing_limit INTEGER
) RETURNS SETOF jobs
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_intent upload_intents%ROWTYPE;
  v_existing jobs%ROWTYPE;
  v_period DATE := date_trunc('month', now() AT TIME ZONE 'UTC')::date;
  v_usage user_usage_monthly%ROWTYPE;
  v_reservation INTEGER := GREATEST(COALESCE(p_duration_seconds, 0), 0);
  v_active INTEGER;
BEGIN
  IF p_user_id IS NULL OR p_video_hash !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION USING ERRCODE = '22023', MESSAGE = 'invalid job identity';
  END IF;

  PERFORM pg_advisory_xact_lock(hashtextextended(p_user_id::text, 0));

  SELECT * INTO v_intent
  FROM upload_intents
  WHERE user_id = p_user_id
    AND gcs_path = p_gcs_path
  FOR UPDATE;

  IF NOT FOUND OR v_intent.status <> 'pending' OR v_intent.expires_at <= now() THEN
    RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'invalid_or_expired_upload_intent';
  END IF;
  IF v_intent.expected_size_bytes <> p_file_size_bytes
     OR v_intent.original_filename <> p_filename
     OR p_gcs_path NOT LIKE ('uploads/' || p_user_id::text || '/%') THEN
    RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'upload_intent_mismatch';
  END IF;

  SELECT * INTO v_existing
  FROM jobs
  WHERE user_id = p_user_id
    AND video_hash = p_video_hash
    AND status = 'completed'
  ORDER BY completed_at DESC NULLS LAST
  LIMIT 1;

  IF FOUND THEN
    UPDATE upload_intents
    SET status = 'consumed', consumed_at = now(), job_id = v_existing.id,
        content_sha256 = p_video_hash
    WHERE id = v_intent.id;
    RETURN NEXT v_existing;
    RETURN;
  END IF;

  IF p_global_processing_limit IS NOT NULL THEN
    PERFORM pg_advisory_xact_lock(hashtextextended('jobs:global-processing', 0));
    SELECT count(*) INTO v_active FROM jobs WHERE status = 'processing';
    IF v_active >= p_global_processing_limit THEN
      RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'global_processing_limit_reached';
    END IF;
  END IF;

  IF p_user_concurrent_limit IS NOT NULL THEN
    SELECT count(*) INTO v_active
    FROM jobs WHERE user_id = p_user_id AND status IN ('pending', 'processing');
    IF v_active >= p_user_concurrent_limit THEN
      RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'user_concurrent_limit_reached';
    END IF;
  END IF;

  INSERT INTO user_usage_monthly (user_id, period_start)
  VALUES (p_user_id, v_period)
  ON CONFLICT (user_id, period_start) DO NOTHING;
  SELECT * INTO v_usage FROM user_usage_monthly
  WHERE user_id = p_user_id AND period_start = v_period FOR UPDATE;

  IF p_monthly_limit_seconds IS NOT NULL
     AND v_usage.transcription_seconds + v_usage.reserved_transcription_seconds + v_reservation
         > p_monthly_limit_seconds THEN
    RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'monthly_quota_exceeded';
  END IF;

  UPDATE user_usage_monthly
  SET reserved_transcription_seconds = reserved_transcription_seconds + v_reservation,
      updated_at = now()
  WHERE user_id = p_user_id AND period_start = v_period;

  INSERT INTO jobs (
    id, access_token, user_id, filename, gcs_path, file_size_bytes, video_hash,
    status, progress, stage, message, estimated_duration_seconds,
    video_duration_seconds, quota_reserved_seconds, quota_reservation_period,
    upload_intent_id,
    retry_count, params, created_at, updated_at, last_seen
  ) VALUES (
    p_job_id, p_access_token, p_user_id, p_filename, p_gcs_path,
    p_file_size_bytes, p_video_hash, 'pending', 0, 'queued',
    'Job created and queued', p_estimated_duration_seconds,
    p_duration_seconds, v_reservation, v_period, v_intent.id,
    0, COALESCE(p_params, '{}'::jsonb), now(), now(), now()
  ) RETURNING * INTO v_existing;

  UPDATE upload_intents
  SET status = 'consumed', consumed_at = now(), job_id = p_job_id,
      content_sha256 = p_video_hash
  WHERE id = v_intent.id;

  RETURN NEXT v_existing;
END;
$$;

REVOKE ALL ON FUNCTION create_job_secure(UUID, UUID, UUID, TEXT, TEXT, BIGINT, TEXT, INTEGER, JSONB, INTEGER, INTEGER, INTEGER, INTEGER) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION create_job_secure(UUID, UUID, UUID, TEXT, TEXT, BIGINT, TEXT, INTEGER, JSONB, INTEGER, INTEGER, INTEGER, INTEGER) TO service_role;

DELETE FROM public.schema_migrations WHERE version = '024';

COMMIT;
