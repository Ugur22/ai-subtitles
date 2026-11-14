-- Deleting a job also deletes everything derived from its video: the pipeline
-- cache, search embeddings, face tags and the owner's screenshot folder.
-- Without this a re-upload of the same file silently reuses the old results,
-- and "delete" leaves the full transcript behind.
--
-- Derived data is keyed by (user_id, video_hash), so it is only removed when the
-- user has no other job for the same file. The screenshot folder is queued in
-- media_delete_outbox as a prefix (media_key ends with '/').
--
-- Base: the live definition on 2026-11-15 (006 with ON CONFLICT ON CONSTRAINT).
-- The return type gains screenshots_outbox_id, so the function is dropped first.
-- Rollback: 020_delete_job_derived_data_rollback.sql
BEGIN;

DROP FUNCTION IF EXISTS delete_job_permanent_secure(UUID, UUID);

CREATE FUNCTION delete_job_permanent_secure(
  p_job_id UUID,
  p_user_id UUID
) RETURNS TABLE(
  deleted BOOLEAN,
  outbox_id UUID,
  media_key TEXT,
  error_code TEXT,
  screenshots_outbox_id UUID
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_job jobs%ROWTYPE;
  v_reference_count INTEGER := 0;
  v_all_target BOOLEAN := FALSE;
  v_owner_scoped BOOLEAN := FALSE;
  v_outbox_id UUID;
  v_screenshots_outbox_id UUID;
BEGIN
  IF p_job_id IS NULL OR p_user_id IS NULL THEN
    RAISE EXCEPTION USING ERRCODE = '22023', MESSAGE = 'invalid deletion identity';
  END IF;

  PERFORM pg_advisory_xact_lock(hashtextextended(p_user_id::text, 0));
  SELECT * INTO v_job
  FROM jobs
  WHERE id = p_job_id AND user_id = p_user_id
  FOR UPDATE;
  IF NOT FOUND THEN
    RETURN QUERY SELECT FALSE, NULL::UUID, NULL::TEXT, 'job_not_found'::TEXT, NULL::UUID;
    RETURN;
  END IF;

  IF v_job.status NOT IN ('completed', 'failed', 'cancelled') THEN
    RETURN QUERY SELECT
      FALSE, NULL::UUID, v_job.gcs_path, 'job_not_terminal'::TEXT, NULL::UUID;
    RETURN;
  END IF;

  IF v_job.gcs_path IS NOT NULL THEN
    PERFORM pg_advisory_xact_lock(
      hashtextextended('media-key:' || v_job.gcs_path, 0)
    );
    SELECT count(*), bool_and(id = p_job_id AND user_id = p_user_id)
      INTO v_reference_count, v_all_target
    FROM jobs
    WHERE gcs_path = v_job.gcs_path;

    v_owner_scoped := (
      v_job.gcs_path LIKE ('uploads/' || p_user_id::text || '/%')
      OR v_job.gcs_path LIKE ('processed/' || p_user_id::text || '/%')
    ) AND v_job.gcs_path !~ '(^|/)\.\.(/|$)'
      AND position(E'\\' in v_job.gcs_path) = 0;

    IF v_reference_count = 1 AND v_all_target AND v_owner_scoped THEN
      INSERT INTO media_delete_outbox (source_job_id, user_id, media_key)
      VALUES (p_job_id, p_user_id, v_job.gcs_path)
      ON CONFLICT ON CONSTRAINT media_delete_outbox_media_key_key DO NOTHING
      RETURNING id INTO v_outbox_id;
    END IF;
  END IF;

  -- The hash check keeps the screenshot prefix a single path segment.
  IF v_job.video_hash ~ '^[A-Za-z0-9]+$' AND NOT EXISTS (
    SELECT 1 FROM jobs
    WHERE user_id = p_user_id
      AND video_hash = v_job.video_hash
      AND id <> p_job_id
  ) THEN
    DELETE FROM pipeline_cache
      WHERE user_id = p_user_id AND video_hash = v_job.video_hash;
    DELETE FROM transcript_embeddings
      WHERE user_id = p_user_id AND video_hash = v_job.video_hash;
    DELETE FROM transcript_embeddings_v2
      WHERE user_id = p_user_id AND video_hash = v_job.video_hash;
    DELETE FROM audio_event_embeddings
      WHERE user_id = p_user_id AND video_hash = v_job.video_hash;
    DELETE FROM audio_event_embeddings_v2
      WHERE user_id = p_user_id AND video_hash = v_job.video_hash;
    -- Cascades to image_caption_sentences and image_face_presence.
    DELETE FROM image_embeddings
      WHERE user_id = p_user_id AND video_hash = v_job.video_hash;
    DELETE FROM face_tags
      WHERE user_id = p_user_id AND video_hash = v_job.video_hash;

    -- A completed row for this prefix is from an earlier delete of the same
    -- file; reopen it so the new screenshots are removed too.
    INSERT INTO media_delete_outbox (source_job_id, user_id, media_key)
    VALUES (
      p_job_id,
      p_user_id,
      'screenshots/' || p_user_id::text || '/' || v_job.video_hash || '/'
    )
    ON CONFLICT ON CONSTRAINT media_delete_outbox_media_key_key DO UPDATE
      SET status = 'pending',
          source_job_id = EXCLUDED.source_job_id,
          attempt_count = 0,
          last_error = NULL,
          claimed_at = NULL,
          completed_at = NULL,
          available_at = now(),
          updated_at = now()
      WHERE media_delete_outbox.status = 'completed'
    RETURNING id INTO v_screenshots_outbox_id;
  END IF;

  IF COALESCE(v_job.quota_reserved_seconds, 0) > 0 THEN
    IF v_job.quota_reservation_period IS NULL THEN
      RAISE EXCEPTION 'job quota reservation is missing its period';
    END IF;
    UPDATE user_usage_monthly
    SET reserved_transcription_seconds = GREATEST(
          reserved_transcription_seconds - v_job.quota_reserved_seconds, 0
        ),
        updated_at = now()
    WHERE user_id = p_user_id
      AND period_start = v_job.quota_reservation_period;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'job quota ledger row is missing';
    END IF;
  END IF;

  DELETE FROM jobs WHERE id = p_job_id AND user_id = p_user_id;
  RETURN QUERY SELECT TRUE, v_outbox_id, v_job.gcs_path, NULL::TEXT, v_screenshots_outbox_id;
END;
$$;

REVOKE ALL ON FUNCTION delete_job_permanent_secure(UUID, UUID) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION delete_job_permanent_secure(UUID, UUID) TO service_role;

COMMIT;
