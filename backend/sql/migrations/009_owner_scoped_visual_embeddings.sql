BEGIN;

CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE image_embeddings ADD COLUMN IF NOT EXISTS user_id UUID;
ALTER TABLE image_face_presence ADD COLUMN IF NOT EXISTS user_id UUID;
ALTER TABLE face_tags ADD COLUMN IF NOT EXISTS user_id UUID;

-- A hash is safe to backfill only when every historical job row belongs to the
-- same non-null owner. Shared and legacy-null hashes are intentionally dropped
-- so the owner can create a fresh index without inheriting another tenant's data.
WITH unique_hash_owners AS (
  SELECT video_hash, MIN(user_id::text)::uuid AS user_id
  FROM jobs
  WHERE video_hash IS NOT NULL
  GROUP BY video_hash
  HAVING COUNT(DISTINCT user_id) = 1
     AND COUNT(*) FILTER (WHERE user_id IS NULL) = 0
)
UPDATE image_embeddings AS ie
SET user_id = owners.user_id
FROM unique_hash_owners AS owners
WHERE ie.user_id IS NULL AND ie.video_hash = owners.video_hash;

DELETE FROM image_embeddings WHERE user_id IS NULL;

UPDATE image_face_presence AS ifp
SET user_id = ie.user_id
FROM image_embeddings AS ie
WHERE ifp.user_id IS NULL AND ifp.image_embedding_id = ie.id;

DELETE FROM image_face_presence WHERE user_id IS NULL;

WITH unique_hash_owners AS (
  SELECT video_hash, MIN(user_id::text)::uuid AS user_id
  FROM jobs
  WHERE video_hash IS NOT NULL
  GROUP BY video_hash
  HAVING COUNT(DISTINCT user_id) = 1
     AND COUNT(*) FILTER (WHERE user_id IS NULL) = 0
)
UPDATE face_tags AS ft
SET user_id = owners.user_id
FROM unique_hash_owners AS owners
WHERE ft.user_id IS NULL AND ft.video_hash = owners.video_hash;

DELETE FROM face_tags WHERE user_id IS NULL;

ALTER TABLE image_embeddings ALTER COLUMN user_id SET NOT NULL;
ALTER TABLE image_face_presence ALTER COLUMN user_id SET NOT NULL;
ALTER TABLE face_tags ALTER COLUMN user_id SET NOT NULL;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'image_embeddings'::regclass
      AND conname = 'image_embeddings_user_id_fkey'
  ) THEN
    ALTER TABLE image_embeddings
      ADD CONSTRAINT image_embeddings_user_id_fkey
      FOREIGN KEY (user_id) REFERENCES user_profiles(id) ON DELETE CASCADE;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'image_face_presence'::regclass
      AND conname = 'image_face_presence_user_id_fkey'
  ) THEN
    ALTER TABLE image_face_presence
      ADD CONSTRAINT image_face_presence_user_id_fkey
      FOREIGN KEY (user_id) REFERENCES user_profiles(id) ON DELETE CASCADE;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'face_tags'::regclass
      AND conname = 'face_tags_user_id_fkey'
  ) THEN
    ALTER TABLE face_tags
      ADD CONSTRAINT face_tags_user_id_fkey
      FOREIGN KEY (user_id) REFERENCES user_profiles(id) ON DELETE CASCADE;
  END IF;
END;
$$;

DO $$
DECLARE v_constraint RECORD;
BEGIN
  FOR v_constraint IN
    SELECT conrelid::regclass AS table_name, conname
    FROM pg_constraint
    WHERE conrelid IN ('image_embeddings'::regclass, 'face_tags'::regclass)
      AND contype IN ('p', 'u')
      AND pg_get_constraintdef(oid) LIKE '%video_hash%'
      AND pg_get_constraintdef(oid) NOT LIKE '%user_id%'
  LOOP
    EXECUTE format(
      'ALTER TABLE %s DROP CONSTRAINT %I',
      v_constraint.table_name,
      v_constraint.conname
    );
  END LOOP;
END;
$$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_image_embeddings_owner_video_segment
  ON image_embeddings (user_id, video_hash, segment_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_image_embeddings_owner_id
  ON image_embeddings (user_id, id);
CREATE INDEX IF NOT EXISTS idx_image_embeddings_owner_video
  ON image_embeddings (user_id, video_hash);
CREATE INDEX IF NOT EXISTS idx_image_face_presence_owner_video
  ON image_face_presence (user_id, video_hash);
CREATE UNIQUE INDEX IF NOT EXISTS idx_face_tags_owner_screenshot_bbox
  ON face_tags (user_id, video_hash, screenshot_url, bbox_x, bbox_y);
CREATE INDEX IF NOT EXISTS idx_face_tags_owner_video_speaker
  ON face_tags (user_id, video_hash, speaker_name);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'image_face_presence'::regclass
      AND conname = 'image_face_presence_owner_image_fkey'
  ) THEN
    ALTER TABLE image_face_presence
      ADD CONSTRAINT image_face_presence_owner_image_fkey
      FOREIGN KEY (user_id, image_embedding_id)
      REFERENCES image_embeddings(user_id, id) ON DELETE CASCADE;
  END IF;
END;
$$;

DO $$
DECLARE
  v_table_name TEXT;
  v_policy RECORD;
BEGIN
  FOREACH v_table_name IN ARRAY ARRAY[
    'image_embeddings', 'image_face_presence', 'face_tags'
  ]
  LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', v_table_name);
    FOR v_policy IN
      SELECT policyname FROM pg_policies
      WHERE schemaname = 'public' AND tablename = v_table_name
    LOOP
      EXECUTE format('DROP POLICY %I ON %I', v_policy.policyname, v_table_name);
    END LOOP;
    EXECUTE format(
      'CREATE POLICY %I ON %I FOR SELECT TO authenticated USING ((SELECT auth.uid()) = user_id)',
      v_table_name || '_select_own',
      v_table_name
    );
    EXECUTE format(
      'CREATE POLICY %I ON %I FOR ALL TO service_role USING (true) WITH CHECK (true)',
      v_table_name || '_service_role_all',
      v_table_name
    );
  END LOOP;
END;
$$;

-- Remove every historical visual-RPC overload before recreating the canonical
-- owner-scoped signatures. Catalog identity arguments avoid relying on how the
-- vector extension renders typmods such as vector(512), and make reruns safe.
DO $$
DECLARE v_function RECORD;
BEGIN
  FOR v_function IN
    SELECT
      namespace.nspname AS schema_name,
      proc.proname AS function_name,
      pg_get_function_identity_arguments(proc.oid) AS identity_arguments
    FROM pg_proc AS proc
    JOIN pg_namespace AS namespace ON namespace.oid = proc.pronamespace
    WHERE namespace.nspname = 'public'
      AND proc.proname IN (
        'search_faces_by_embedding',
        'search_images_by_embedding',
        'match_faces_by_embedding',
        'videos_missing_face_presence'
      )
  LOOP
    EXECUTE format(
      'REVOKE ALL ON FUNCTION %I.%I(%s) FROM PUBLIC, authenticated',
      v_function.schema_name,
      v_function.function_name,
      v_function.identity_arguments
    );
    EXECUTE format(
      'DROP FUNCTION %I.%I(%s)',
      v_function.schema_name,
      v_function.function_name,
      v_function.identity_arguments
    );
  END LOOP;
END;
$$;

CREATE OR REPLACE FUNCTION search_images_by_embedding(
  p_user_id UUID,
  query_embedding vector(512),
  target_video_hash TEXT,
  match_count INTEGER DEFAULT 5,
  speaker_filter TEXT DEFAULT NULL
)
RETURNS TABLE (
  id UUID,
  video_hash TEXT,
  segment_id TEXT,
  start_time DOUBLE PRECISION,
  end_time DOUBLE PRECISION,
  speaker TEXT,
  screenshot_url TEXT,
  similarity DOUBLE PRECISION
)
LANGUAGE plpgsql
SET search_path = public
AS $$
BEGIN
  SET LOCAL hnsw.ef_search = 200;
  RETURN QUERY
  SELECT
    ie.id,
    ie.video_hash,
    ie.segment_id,
    ie.start_time,
    ie.end_time,
    ie.speaker,
    ie.screenshot_url,
    1 - (ie.embedding <=> query_embedding) AS similarity
  FROM image_embeddings AS ie
  WHERE ie.user_id = p_user_id
    AND ie.video_hash = target_video_hash
    AND (speaker_filter IS NULL OR ie.speaker = speaker_filter)
  ORDER BY ie.embedding <=> query_embedding
  LIMIT GREATEST(match_count, 0);
END;
$$;

CREATE OR REPLACE FUNCTION match_faces_by_embedding(
  p_user_id UUID,
  target_video_hash TEXT,
  query_embedding vector(512),
  similarity_threshold DOUBLE PRECISION DEFAULT 0.5,
  match_limit INTEGER DEFAULT 500
)
RETURNS TABLE (
  image_embedding_id UUID,
  start_time DOUBLE PRECISION,
  end_time DOUBLE PRECISION,
  similarity DOUBLE PRECISION
)
LANGUAGE plpgsql
SET search_path = public
AS $$
BEGIN
  SET LOCAL hnsw.ef_search = 200;
  RETURN QUERY
  SELECT
    ifp.image_embedding_id,
    ifp.start_time,
    ifp.end_time,
    1 - (ifp.face_embedding <=> query_embedding) AS similarity
  FROM image_face_presence AS ifp
  WHERE ifp.user_id = p_user_id
    AND ifp.video_hash = target_video_hash
    AND 1 - (ifp.face_embedding <=> query_embedding) >= similarity_threshold
  ORDER BY ifp.face_embedding <=> query_embedding
  LIMIT GREATEST(match_limit, 0);
END;
$$;

CREATE OR REPLACE FUNCTION videos_missing_face_presence(batch_limit INTEGER DEFAULT 10)
RETURNS TABLE (user_id UUID, video_hash TEXT)
LANGUAGE sql
SET search_path = public
AS $$
  SELECT DISTINCT ie.user_id, ie.video_hash
  FROM image_embeddings AS ie
  WHERE NOT EXISTS (
    SELECT 1
    FROM image_face_presence AS ifp
    WHERE ifp.user_id = ie.user_id
      AND ifp.video_hash = ie.video_hash
  )
  ORDER BY ie.user_id, ie.video_hash
  LIMIT GREATEST(batch_limit, 0);
$$;

REVOKE ALL ON FUNCTION search_images_by_embedding(UUID, vector, TEXT, INTEGER, TEXT) FROM PUBLIC, authenticated;
REVOKE ALL ON FUNCTION match_faces_by_embedding(UUID, TEXT, vector, DOUBLE PRECISION, INTEGER) FROM PUBLIC, authenticated;
REVOKE ALL ON FUNCTION videos_missing_face_presence(INTEGER) FROM PUBLIC, authenticated;
GRANT EXECUTE ON FUNCTION search_images_by_embedding(UUID, vector, TEXT, INTEGER, TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION match_faces_by_embedding(UUID, TEXT, vector, DOUBLE PRECISION, INTEGER) TO service_role;
GRANT EXECUTE ON FUNCTION videos_missing_face_presence(INTEGER) TO service_role;

COMMIT;
