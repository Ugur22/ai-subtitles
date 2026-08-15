BEGIN;

CREATE TABLE IF NOT EXISTS media_delete_outbox (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_job_id UUID NOT NULL,
  user_id UUID NOT NULL,
  media_key TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'processing', 'completed')),
  attempt_count INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  claimed_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_media_delete_outbox_pending
  ON media_delete_outbox (status, created_at);

ALTER TABLE media_delete_outbox ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS media_delete_outbox_service_role_all ON media_delete_outbox;
CREATE POLICY media_delete_outbox_service_role_all
  ON media_delete_outbox FOR ALL TO service_role
  USING (true) WITH CHECK (true);

CREATE OR REPLACE FUNCTION guard_claimed_media_key()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  IF NEW.gcs_path IS NULL THEN
    RETURN NEW;
  END IF;
  PERFORM pg_advisory_xact_lock(
    hashtextextended('media-key:' || NEW.gcs_path, 0)
  );
  IF EXISTS (
    SELECT 1 FROM media_delete_outbox WHERE media_key = NEW.gcs_path
  ) THEN
    RAISE EXCEPTION USING
      ERRCODE = '23505',
      MESSAGE = 'media_key_claimed_for_deletion';
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS jobs_guard_claimed_media_key ON jobs;
CREATE TRIGGER jobs_guard_claimed_media_key
BEFORE INSERT OR UPDATE OF gcs_path ON jobs
FOR EACH ROW EXECUTE FUNCTION guard_claimed_media_key();

CREATE OR REPLACE FUNCTION delete_job_permanent_secure(
  p_job_id UUID,
  p_user_id UUID
) RETURNS TABLE(deleted BOOLEAN, outbox_id UUID, media_key TEXT, error_code TEXT)
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
    RETURN QUERY SELECT FALSE, NULL::UUID, NULL::TEXT, 'job_not_found'::TEXT;
    RETURN;
  END IF;

  IF v_job.status NOT IN ('completed', 'failed', 'cancelled') THEN
    RETURN QUERY SELECT
      FALSE, NULL::UUID, v_job.gcs_path, 'job_not_terminal'::TEXT;
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
      ON CONFLICT (media_key) DO NOTHING
      RETURNING id INTO v_outbox_id;
    END IF;
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
  RETURN QUERY SELECT TRUE, v_outbox_id, v_job.gcs_path, NULL::TEXT;
END;
$$;

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
      AND (
        status = 'pending'
        OR (status = 'processing' AND claimed_at < now() - interval '10 minutes')
      )
    ORDER BY created_at
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

CREATE OR REPLACE FUNCTION finish_media_delete(
  p_outbox_id UUID,
  p_error TEXT DEFAULT NULL
) RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  UPDATE media_delete_outbox
  SET status = CASE WHEN p_error IS NULL THEN 'completed' ELSE 'pending' END,
      completed_at = CASE WHEN p_error IS NULL THEN now() ELSE NULL END,
      claimed_at = NULL,
      last_error = left(p_error, 2000),
      updated_at = now()
  WHERE id = p_outbox_id AND status = 'processing';
  RETURN FOUND;
END;
$$;

REVOKE ALL ON TABLE media_delete_outbox FROM PUBLIC, anon, authenticated;
GRANT ALL ON TABLE media_delete_outbox TO service_role;
REVOKE ALL ON FUNCTION guard_claimed_media_key() FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION delete_job_permanent_secure(UUID, UUID) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION claim_media_deletes(INTEGER, UUID) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION finish_media_delete(UUID, TEXT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION delete_job_permanent_secure(UUID, UUID) TO service_role;
GRANT EXECUTE ON FUNCTION claim_media_deletes(INTEGER, UUID) TO service_role;
GRANT EXECUTE ON FUNCTION finish_media_delete(UUID, TEXT) TO service_role;

COMMIT;
