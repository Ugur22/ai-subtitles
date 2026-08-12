BEGIN;

-- Upload paths are capabilities issued by the backend, not client-provided locators.
CREATE TABLE IF NOT EXISTS upload_intents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
  gcs_path TEXT NOT NULL UNIQUE,
  original_filename TEXT NOT NULL,
  content_type TEXT NOT NULL,
  expected_size_bytes BIGINT NOT NULL CHECK (expected_size_bytes > 0),
  content_sha256 TEXT,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'consumed', 'expired')),
  expires_at TIMESTAMPTZ NOT NULL,
  consumed_at TIMESTAMPTZ,
  job_id UUID REFERENCES jobs(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_upload_intents_owner_status
  ON upload_intents (user_id, status, expires_at);

ALTER TABLE upload_intents ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS upload_intents_select_own ON upload_intents;
CREATE POLICY upload_intents_select_own
  ON upload_intents FOR SELECT TO authenticated
  USING ((SELECT auth.uid()) = user_id);

-- Track outstanding reservations separately from settled usage.
ALTER TABLE user_usage_monthly
  ADD COLUMN IF NOT EXISTS reserved_transcription_seconds INTEGER NOT NULL DEFAULT 0
  CHECK (reserved_transcription_seconds >= 0);

ALTER TABLE jobs
  ADD COLUMN IF NOT EXISTS quota_reserved_seconds INTEGER NOT NULL DEFAULT 0
  CHECK (quota_reserved_seconds >= 0);

ALTER TABLE jobs
  ADD COLUMN IF NOT EXISTS quota_reservation_period DATE;

-- Preserve any reservation created before this column existed by assigning it
-- to the UTC month in which the job was submitted.
UPDATE jobs
SET quota_reservation_period = date_trunc(
  'month', created_at AT TIME ZONE 'UTC'
)::date
WHERE quota_reserved_seconds > 0 AND quota_reservation_period IS NULL;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'jobs'::regclass
      AND conname = 'jobs_quota_reservation_period_required'
  ) THEN
    ALTER TABLE jobs ADD CONSTRAINT jobs_quota_reservation_period_required
      CHECK (quota_reserved_seconds = 0 OR quota_reservation_period IS NOT NULL);
  END IF;
END;
$$;

ALTER TABLE jobs
  ADD COLUMN IF NOT EXISTS upload_intent_id UUID REFERENCES upload_intents(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_jobs_owner_hash_completed
  ON jobs (user_id, video_hash, completed_at DESC)
  WHERE status = 'completed' AND user_id IS NOT NULL AND video_hash IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_jobs_owner_active
  ON jobs (user_id, status)
  WHERE status IN ('pending', 'processing');

-- Replace every historical jobs policy, regardless of its old name. Browser
-- sessions can read only their own jobs; all writes go through the service role.
DROP POLICY IF EXISTS jobs_own ON jobs;
DROP POLICY IF EXISTS jobs_legacy ON jobs;
DROP POLICY IF EXISTS "Users manage own jobs" ON jobs;
DROP POLICY IF EXISTS "Legacy jobs read-only" ON jobs;
DO $$
DECLARE v_policy RECORD;
BEGIN
  FOR v_policy IN
    SELECT policyname FROM pg_policies
    WHERE schemaname = 'public' AND tablename = 'jobs'
  LOOP
    EXECUTE format('DROP POLICY %I ON jobs', v_policy.policyname);
  END LOOP;
END;
$$;
CREATE POLICY jobs_select_own ON jobs
  FOR SELECT TO authenticated
  USING ((SELECT auth.uid()) = user_id);
CREATE POLICY jobs_service_role_all ON jobs
  FOR ALL TO service_role USING (true) WITH CHECK (true);

-- Some environments created this cache out-of-band. Define it here so the
-- migration also works when no pipeline_cache table exists yet.
CREATE TABLE IF NOT EXISTS pipeline_cache (
  user_id UUID NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
  video_hash TEXT NOT NULL,
  stage TEXT NOT NULL,
  data JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, video_hash, stage)
);

-- Legacy intermediate caches were global. Drop them instead of assigning them
-- to an arbitrary tenant, then make all future cache keys tenant-scoped.
ALTER TABLE pipeline_cache ADD COLUMN IF NOT EXISTS user_id UUID;
DELETE FROM pipeline_cache WHERE user_id IS NULL;
ALTER TABLE pipeline_cache ALTER COLUMN user_id SET NOT NULL;
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'pipeline_cache'::regclass
      AND contype = 'f'
      AND conname = 'pipeline_cache_user_id_fkey'
  ) THEN
    ALTER TABLE pipeline_cache
      ADD CONSTRAINT pipeline_cache_user_id_fkey
      FOREIGN KEY (user_id) REFERENCES user_profiles(id) ON DELETE CASCADE;
  END IF;
END;
$$;
ALTER TABLE pipeline_cache
  DROP CONSTRAINT IF EXISTS pipeline_cache_video_hash_stage_key;
DO $$
DECLARE v_constraint RECORD;
BEGIN
  FOR v_constraint IN
    SELECT conname
    FROM pg_constraint
    WHERE conrelid = 'pipeline_cache'::regclass
      AND contype IN ('p', 'u')
      AND pg_get_constraintdef(oid) LIKE '%video_hash%'
      AND pg_get_constraintdef(oid) LIKE '%stage%'
      AND pg_get_constraintdef(oid) NOT LIKE '%user_id%'
  LOOP
    EXECUTE format('ALTER TABLE pipeline_cache DROP CONSTRAINT %I', v_constraint.conname);
  END LOOP;
END;
$$;
CREATE UNIQUE INDEX IF NOT EXISTS idx_pipeline_cache_owner_video_stage
  ON pipeline_cache (user_id, video_hash, stage);

ALTER TABLE pipeline_cache ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS pipeline_cache_select_own ON pipeline_cache;
CREATE POLICY pipeline_cache_select_own ON pipeline_cache
  FOR SELECT TO authenticated
  USING ((SELECT auth.uid()) = user_id);

-- Hash-only visual rows cannot be assigned safely when two users upload the
-- same content. Until those tables gain user_id, remove every client policy and
-- keep them backend/service-role only.
DO $$
DECLARE
  v_table_name TEXT;
  v_policy RECORD;
BEGIN
  FOREACH v_table_name IN ARRAY ARRAY[
    'image_embeddings', 'face_tags', 'image_face_presence',
    'video_face_tags', 'video_face_presence'
  ]
  LOOP
    IF to_regclass('public.' || v_table_name) IS NOT NULL THEN
      EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', v_table_name);
      FOR v_policy IN
        SELECT policyname FROM pg_policies
        WHERE schemaname = 'public' AND tablename = v_table_name
      LOOP
        EXECUTE format('DROP POLICY %I ON %I', v_policy.policyname, v_table_name);
      END LOOP;
      EXECUTE format(
        'CREATE POLICY visual_service_role_only ON %I FOR ALL TO service_role USING (true) WITH CHECK (true)',
        v_table_name
      );
    END IF;
  END LOOP;
END;
$$;

-- One transaction validates the upload capability, serializes quota/concurrency
-- decisions for the owner, and either returns that owner's cache hit or inserts
-- a new job. The service role is the only caller.
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

CREATE OR REPLACE FUNCTION adjust_job_quota_reservation(
  p_job_id UUID,
  p_user_id UUID,
  p_actual_seconds INTEGER,
  p_monthly_limit_seconds INTEGER
) RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_job jobs%ROWTYPE;
  v_period DATE;
  v_usage user_usage_monthly%ROWTYPE;
  v_actual INTEGER := GREATEST(COALESCE(p_actual_seconds, 0), 0);
BEGIN
  PERFORM pg_advisory_xact_lock(hashtextextended(p_user_id::text, 0));
  SELECT * INTO v_job FROM jobs
  WHERE id = p_job_id AND user_id = p_user_id FOR UPDATE;
  IF NOT FOUND OR v_job.status <> 'processing' THEN RETURN FALSE; END IF;

  -- Existing reservations never move across ledger rows. A retry clears the
  -- old period, so its first new reservation starts in the retry month.
  v_period := COALESCE(
    v_job.quota_reservation_period,
    date_trunc('month', now() AT TIME ZONE 'UTC')::date
  );

  INSERT INTO user_usage_monthly (user_id, period_start)
  VALUES (p_user_id, v_period) ON CONFLICT (user_id, period_start) DO NOTHING;
  SELECT * INTO v_usage FROM user_usage_monthly
  WHERE user_id = p_user_id AND period_start = v_period FOR UPDATE;

  IF p_monthly_limit_seconds IS NOT NULL
     AND v_usage.transcription_seconds
       + v_usage.reserved_transcription_seconds - v_job.quota_reserved_seconds + v_actual
       > p_monthly_limit_seconds THEN
    RETURN FALSE;
  END IF;

  UPDATE user_usage_monthly
  SET reserved_transcription_seconds = reserved_transcription_seconds
        - v_job.quota_reserved_seconds + v_actual,
      updated_at = now()
  WHERE user_id = p_user_id AND period_start = v_period;
  UPDATE jobs SET quota_reserved_seconds = v_actual,
                  quota_reservation_period = v_period,
                  video_duration_seconds = v_actual,
                  updated_at = now()
  WHERE id = p_job_id;
  RETURN TRUE;
END;
$$;

CREATE OR REPLACE FUNCTION settle_completed_job(
  p_job_id UUID,
  p_user_id UUID,
  p_video_hash TEXT,
  p_result_json JSONB,
  p_result_srt TEXT,
  p_result_vtt TEXT,
  p_video_duration_seconds INTEGER,
  p_gpu_seconds NUMERIC,
  p_gcs_path TEXT
) RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_job jobs%ROWTYPE;
  v_period DATE;
  v_seconds INTEGER := GREATEST(COALESCE(p_video_duration_seconds, 0), 0);
BEGIN
  PERFORM pg_advisory_xact_lock(hashtextextended(p_user_id::text, 0));
  SELECT * INTO v_job FROM jobs
  WHERE id = p_job_id AND user_id = p_user_id FOR UPDATE;
  IF NOT FOUND OR v_job.status <> 'processing' THEN RETURN FALSE; END IF;
  IF v_job.quota_reservation_period IS NULL THEN RETURN FALSE; END IF;
  v_period := v_job.quota_reservation_period;

  INSERT INTO user_usage_monthly (user_id, period_start)
  VALUES (p_user_id, v_period) ON CONFLICT (user_id, period_start) DO NOTHING;
  UPDATE user_usage_monthly SET
    transcription_seconds = transcription_seconds + v_seconds,
    reserved_transcription_seconds = GREATEST(
      reserved_transcription_seconds - v_job.quota_reserved_seconds, 0
    ),
    updated_at = now()
  WHERE user_id = p_user_id AND period_start = v_period;

  UPDATE jobs SET
    status = 'completed', progress = 100, stage = 'completed',
    message = 'Transcription completed successfully', video_hash = p_video_hash,
    result_json = p_result_json, result_srt = p_result_srt, result_vtt = p_result_vtt,
    video_duration_seconds = v_seconds, gpu_seconds = p_gpu_seconds,
    gcs_path = COALESCE(p_gcs_path, gcs_path), quota_reserved_seconds = 0,
    quota_reservation_period = NULL,
    completed_at = now(), updated_at = now(), last_seen = now()
  WHERE id = p_job_id;
  RETURN TRUE;
END;
$$;

CREATE OR REPLACE FUNCTION release_job_quota_reservation(p_job_id UUID)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_job jobs%ROWTYPE;
  v_user_id UUID;
  v_period DATE;
BEGIN
  SELECT user_id INTO v_user_id FROM jobs WHERE id = p_job_id;
  IF NOT FOUND OR v_user_id IS NULL THEN RETURN FALSE; END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended(v_user_id::text, 0));
  SELECT * INTO v_job FROM jobs WHERE id = p_job_id AND user_id = v_user_id FOR UPDATE;
  IF NOT FOUND THEN RETURN FALSE; END IF;
  IF v_job.quota_reserved_seconds = 0 THEN
    UPDATE jobs SET quota_reservation_period = NULL WHERE id = p_job_id;
    RETURN TRUE;
  END IF;
  IF v_job.quota_reservation_period IS NULL THEN RETURN FALSE; END IF;
  v_period := v_job.quota_reservation_period;
  UPDATE user_usage_monthly SET
    reserved_transcription_seconds = GREATEST(
      reserved_transcription_seconds - v_job.quota_reserved_seconds, 0
    ), updated_at = now()
  WHERE user_id = v_job.user_id AND period_start = v_period;
  IF NOT FOUND THEN RETURN FALSE; END IF;
  UPDATE jobs SET quota_reserved_seconds = 0, quota_reservation_period = NULL
  WHERE id = p_job_id;
  RETURN TRUE;
END;
$$;

CREATE OR REPLACE FUNCTION fail_job_secure(
  p_job_id UUID,
  p_error_message TEXT,
  p_error_code TEXT
) RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_job jobs%ROWTYPE;
  v_user_id UUID;
  v_period DATE;
BEGIN
  SELECT user_id INTO v_user_id FROM jobs WHERE id = p_job_id;
  IF NOT FOUND OR v_user_id IS NULL THEN RETURN FALSE; END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended(v_user_id::text, 0));
  SELECT * INTO v_job FROM jobs
  WHERE id = p_job_id AND user_id = v_user_id FOR UPDATE;
  IF NOT FOUND OR v_job.status NOT IN ('pending', 'processing') THEN RETURN FALSE; END IF;
  IF v_job.quota_reserved_seconds > 0 AND v_job.quota_reservation_period IS NULL THEN
    RETURN FALSE;
  END IF;
  v_period := v_job.quota_reservation_period;
  IF v_job.quota_reserved_seconds > 0 THEN
    UPDATE user_usage_monthly SET
      reserved_transcription_seconds = GREATEST(
        reserved_transcription_seconds - v_job.quota_reserved_seconds, 0
      ), updated_at = now()
    WHERE user_id = v_user_id AND period_start = v_period;
    IF NOT FOUND THEN RETURN FALSE; END IF;
  END IF;
  UPDATE jobs SET
    status = 'failed', stage = 'failed', message = p_error_message,
    error_code = p_error_code, error_message = p_error_message,
    quota_reserved_seconds = 0, quota_reservation_period = NULL,
    failed_at = now(), updated_at = now(), last_seen = now()
  WHERE id = p_job_id AND status IN ('pending', 'processing');
  RETURN FOUND;
END;
$$;

CREATE OR REPLACE FUNCTION cancel_job_secure(p_job_id UUID, p_user_id UUID)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_job jobs%ROWTYPE;
  v_period DATE;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtextextended(p_user_id::text, 0));
  SELECT * INTO v_job FROM jobs
  WHERE id = p_job_id AND user_id = p_user_id FOR UPDATE;
  IF NOT FOUND OR v_job.status NOT IN ('pending', 'processing') THEN RETURN FALSE; END IF;
  IF v_job.quota_reserved_seconds > 0 AND v_job.quota_reservation_period IS NULL THEN
    RETURN FALSE;
  END IF;
  v_period := v_job.quota_reservation_period;
  IF v_job.quota_reserved_seconds > 0 THEN
    UPDATE user_usage_monthly SET
      reserved_transcription_seconds = GREATEST(
        reserved_transcription_seconds - v_job.quota_reserved_seconds, 0
      ), updated_at = now()
    WHERE user_id = p_user_id AND period_start = v_period;
    IF NOT FOUND THEN RETURN FALSE; END IF;
  END IF;
  UPDATE jobs SET
    status = 'cancelled', stage = 'cancelled', message = 'Job cancelled by user',
    quota_reserved_seconds = 0, quota_reservation_period = NULL,
    cancelled_at = now(), updated_at = now(), last_seen = now()
  WHERE id = p_job_id AND user_id = p_user_id
    AND status IN ('pending', 'processing');
  RETURN FOUND;
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
  IF COALESCE(v_job.retry_count, 0) >= p_max_retries THEN
    RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'max_retries_reached';
  END IF;

  IF p_user_concurrent_limit IS NOT NULL THEN
    SELECT count(*) INTO v_active FROM jobs
    WHERE user_id = p_user_id AND status IN ('pending', 'processing');
    IF v_active >= p_user_concurrent_limit THEN
      RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'user_concurrent_limit_reached';
    END IF;
  END IF;

  UPDATE jobs SET
    status = 'pending', stage = 'queued', message = 'Job queued for retry',
    error_code = NULL, error_message = NULL, failed_at = NULL,
    quota_reserved_seconds = 0, quota_reservation_period = NULL,
    retry_count = COALESCE(retry_count, 0) + 1,
    updated_at = now(), last_seen = now()
  WHERE id = p_job_id AND user_id = p_user_id AND status = 'failed'
    AND COALESCE(retry_count, 0) < p_max_retries
  RETURNING * INTO v_job;
  IF NOT FOUND THEN
    RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'retry_compare_and_set_failed';
  END IF;
  RETURN NEXT v_job;
END;
$$;

CREATE OR REPLACE FUNCTION increment_monthly_usage(
  p_user_id UUID,
  p_transcription_seconds INTEGER DEFAULT 0,
  p_llm_tokens INTEGER DEFAULT 0,
  p_chat_messages INTEGER DEFAULT 0
) RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  INSERT INTO user_usage_monthly (
    user_id, period_start, transcription_seconds, llm_tokens, chat_messages
  ) VALUES (
    p_user_id, date_trunc('month', now() AT TIME ZONE 'UTC')::date,
    GREATEST(p_transcription_seconds, 0), GREATEST(p_llm_tokens, 0),
    GREATEST(p_chat_messages, 0)
  ) ON CONFLICT (user_id, period_start) DO UPDATE SET
    transcription_seconds = user_usage_monthly.transcription_seconds
      + EXCLUDED.transcription_seconds,
    llm_tokens = user_usage_monthly.llm_tokens + EXCLUDED.llm_tokens,
    chat_messages = user_usage_monthly.chat_messages + EXCLUDED.chat_messages,
    updated_at = now();
END;
$$;

CREATE OR REPLACE FUNCTION consume_rate_limit(
  p_user_id UUID,
  p_limit_type TEXT,
  p_limit INTEGER,
  p_window_start TIMESTAMPTZ
) RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE v_count INTEGER;
BEGIN
  INSERT INTO rate_limits (user_id, limit_type, count, window_start)
  VALUES (p_user_id, p_limit_type, 1, p_window_start)
  ON CONFLICT (user_id, limit_type) DO UPDATE SET
    count = CASE
      WHEN rate_limits.window_start < EXCLUDED.window_start THEN 1
      ELSE rate_limits.count + 1
    END,
    window_start = CASE
      WHEN rate_limits.window_start < EXCLUDED.window_start
        THEN EXCLUDED.window_start ELSE rate_limits.window_start
    END,
    updated_at = now()
  WHERE rate_limits.window_start < EXCLUDED.window_start
     OR rate_limits.count < p_limit
  RETURNING count INTO v_count;
  RETURN v_count IS NOT NULL AND v_count <= p_limit;
END;
$$;

REVOKE ALL ON FUNCTION create_job_secure(UUID, UUID, UUID, TEXT, TEXT, BIGINT, TEXT, INTEGER, JSONB, INTEGER, INTEGER, INTEGER, INTEGER) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION claim_job(UUID, INTEGER) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION adjust_job_quota_reservation(UUID, UUID, INTEGER, INTEGER) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION settle_completed_job(UUID, UUID, TEXT, JSONB, TEXT, TEXT, INTEGER, NUMERIC, TEXT) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION release_job_quota_reservation(UUID) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION fail_job_secure(UUID, TEXT, TEXT) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION cancel_job_secure(UUID, UUID) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION retry_job_secure(UUID, UUID, INTEGER, INTEGER) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION increment_monthly_usage(UUID, INTEGER, INTEGER, INTEGER) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION consume_rate_limit(UUID, TEXT, INTEGER, TIMESTAMPTZ) FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION create_job_secure(UUID, UUID, UUID, TEXT, TEXT, BIGINT, TEXT, INTEGER, JSONB, INTEGER, INTEGER, INTEGER, INTEGER) TO service_role;
GRANT EXECUTE ON FUNCTION claim_job(UUID, INTEGER) TO service_role;
GRANT EXECUTE ON FUNCTION adjust_job_quota_reservation(UUID, UUID, INTEGER, INTEGER) TO service_role;
GRANT EXECUTE ON FUNCTION settle_completed_job(UUID, UUID, TEXT, JSONB, TEXT, TEXT, INTEGER, NUMERIC, TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION release_job_quota_reservation(UUID) TO service_role;
GRANT EXECUTE ON FUNCTION fail_job_secure(UUID, TEXT, TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION cancel_job_secure(UUID, UUID) TO service_role;
GRANT EXECUTE ON FUNCTION retry_job_secure(UUID, UUID, INTEGER, INTEGER) TO service_role;
GRANT EXECUTE ON FUNCTION increment_monthly_usage(UUID, INTEGER, INTEGER, INTEGER) TO service_role;
GRANT EXECUTE ON FUNCTION consume_rate_limit(UUID, TEXT, INTEGER, TIMESTAMPTZ) TO service_role;

COMMIT;
