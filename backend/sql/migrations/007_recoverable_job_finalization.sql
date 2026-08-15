BEGIN;

ALTER TABLE jobs
  ADD COLUMN IF NOT EXISTS final_media_key TEXT,
  ADD COLUMN IF NOT EXISTS finalization_started_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_jobs_stale_finalizing
  ON jobs (last_seen)
  WHERE status = 'finalizing';

CREATE OR REPLACE FUNCTION begin_job_finalization(
  p_job_id UUID,
  p_user_id UUID,
  p_video_hash TEXT,
  p_result_json JSONB,
  p_result_srt TEXT,
  p_result_vtt TEXT,
  p_video_duration_seconds INTEGER,
  p_gpu_seconds NUMERIC,
  p_final_media_key TEXT
) RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_job jobs%ROWTYPE;
BEGIN
  IF p_job_id IS NULL OR p_user_id IS NULL
     OR p_final_media_key NOT LIKE ('processed/' || p_user_id::text || '/%')
     OR p_final_media_key ~ '(^|/)\.\.(/|$)'
     OR position(E'\\' in p_final_media_key) > 0 THEN
    RETURN FALSE;
  END IF;

  PERFORM pg_advisory_xact_lock(hashtextextended(p_user_id::text, 0));
  SELECT * INTO v_job FROM jobs
  WHERE id = p_job_id AND user_id = p_user_id FOR UPDATE;
  IF NOT FOUND THEN RETURN FALSE; END IF;
  IF v_job.status = 'finalizing' THEN
    RETURN v_job.final_media_key = p_final_media_key
      AND v_job.video_hash = p_video_hash;
  END IF;
  IF v_job.status <> 'processing' OR v_job.quota_reservation_period IS NULL THEN
    RETURN FALSE;
  END IF;
  IF NOT (
    v_job.gcs_path LIKE ('uploads/' || p_user_id::text || '/%')
    OR v_job.gcs_path = p_final_media_key
  ) THEN
    RETURN FALSE;
  END IF;

  UPDATE jobs SET
    status = 'finalizing', stage = 'finalizing',
    message = 'Finalizing media and transcription results',
    video_hash = p_video_hash, result_json = p_result_json,
    result_srt = p_result_srt, result_vtt = p_result_vtt,
    video_duration_seconds = GREATEST(COALESCE(p_video_duration_seconds, 0), 0),
    gpu_seconds = p_gpu_seconds, final_media_key = p_final_media_key,
    finalization_started_at = now(), updated_at = now(), last_seen = now()
  WHERE id = p_job_id AND user_id = p_user_id AND status = 'processing';
  RETURN FOUND;
END;
$$;

CREATE OR REPLACE FUNCTION settle_finalizing_job(
  p_job_id UUID,
  p_user_id UUID
) RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_job jobs%ROWTYPE;
  v_period DATE;
  v_source_key TEXT;
  v_reference_count INTEGER;
  v_source_exclusive BOOLEAN;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtextextended(p_user_id::text, 0));
  SELECT * INTO v_job FROM jobs
  WHERE id = p_job_id AND user_id = p_user_id FOR UPDATE;
  IF NOT FOUND THEN RETURN FALSE; END IF;
  IF v_job.status = 'completed' THEN RETURN TRUE; END IF;
  IF v_job.status <> 'finalizing'
     OR v_job.quota_reservation_period IS NULL
     OR v_job.final_media_key IS NULL THEN
    RETURN FALSE;
  END IF;

  v_period := v_job.quota_reservation_period;
  v_source_key := v_job.gcs_path;
  PERFORM pg_advisory_xact_lock(
    hashtextextended('media-key:' || v_source_key, 0)
  );
  SELECT count(*), bool_and(id = p_job_id AND user_id = p_user_id)
    INTO v_reference_count, v_source_exclusive
  FROM jobs WHERE gcs_path = v_source_key;

  INSERT INTO user_usage_monthly (user_id, period_start)
  VALUES (p_user_id, v_period) ON CONFLICT (user_id, period_start) DO NOTHING;
  UPDATE user_usage_monthly SET
    transcription_seconds = transcription_seconds
      + GREATEST(COALESCE(v_job.video_duration_seconds, 0), 0),
    reserved_transcription_seconds = GREATEST(
      reserved_transcription_seconds - v_job.quota_reserved_seconds, 0
    ),
    updated_at = now()
  WHERE user_id = p_user_id AND period_start = v_period;

  UPDATE jobs SET
    status = 'completed', progress = 100, stage = 'completed',
    message = 'Transcription completed successfully',
    gcs_path = v_job.final_media_key,
    quota_reserved_seconds = 0, quota_reservation_period = NULL,
    final_media_key = NULL, completed_at = now(), updated_at = now(), last_seen = now()
  WHERE id = p_job_id AND user_id = p_user_id AND status = 'finalizing';
  IF NOT FOUND THEN RETURN FALSE; END IF;

  IF v_source_key IS DISTINCT FROM v_job.final_media_key
     AND v_reference_count = 1 AND v_source_exclusive
     AND v_source_key LIKE ('uploads/' || p_user_id::text || '/%') THEN
    INSERT INTO media_delete_outbox (source_job_id, user_id, media_key)
    VALUES (p_job_id, p_user_id, v_source_key)
    ON CONFLICT (media_key) DO NOTHING;
  END IF;
  RETURN TRUE;
END;
$$;

REVOKE ALL ON FUNCTION begin_job_finalization(
  UUID, UUID, TEXT, JSONB, TEXT, TEXT, INTEGER, NUMERIC, TEXT
) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION settle_finalizing_job(UUID, UUID)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION begin_job_finalization(
  UUID, UUID, TEXT, JSONB, TEXT, TEXT, INTEGER, NUMERIC, TEXT
) TO service_role;
GRANT EXECUTE ON FUNCTION settle_finalizing_job(UUID, UUID) TO service_role;

COMMIT;
