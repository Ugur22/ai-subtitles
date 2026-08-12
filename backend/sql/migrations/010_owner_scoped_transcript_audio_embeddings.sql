BEGIN;

CREATE EXTENSION IF NOT EXISTS vector;

-- Greenfield tables: nothing in ChromaDB is queryable at the row level, so
-- there is no data to backfill (unlike 009's image_embeddings/face_tags
-- backfill). Owner scoping is present from the first row onward.

CREATE TABLE IF NOT EXISTS transcript_embeddings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
  video_hash TEXT NOT NULL,
  chunk_index INTEGER NOT NULL,
  start_time DOUBLE PRECISION NOT NULL,
  end_time DOUBLE PRECISION NOT NULL,
  start_timestamp TEXT NOT NULL,
  end_timestamp TEXT NOT NULL,
  speaker TEXT,
  segment_count INTEGER NOT NULL DEFAULT 1,
  chunk_text TEXT NOT NULL,
  embedding vector(384) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS audio_event_embeddings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
  video_hash TEXT NOT NULL,
  segment_id TEXT NOT NULL,
  start_time DOUBLE PRECISION NOT NULL,
  end_time DOUBLE PRECISION NOT NULL,
  speaker TEXT,
  has_speech BOOLEAN NOT NULL DEFAULT FALSE,
  primary_event TEXT,
  speech_emotion TEXT,
  description TEXT NOT NULL,
  embedding vector(384) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_transcript_embeddings_owner_video_chunk
  ON transcript_embeddings (user_id, video_hash, chunk_index);
CREATE INDEX IF NOT EXISTS idx_transcript_embeddings_owner_video
  ON transcript_embeddings (user_id, video_hash);
CREATE INDEX IF NOT EXISTS idx_transcript_embeddings_hnsw
  ON transcript_embeddings USING hnsw (embedding vector_cosine_ops)
  WITH (m = 24, ef_construction = 200);

CREATE UNIQUE INDEX IF NOT EXISTS idx_audio_event_embeddings_owner_video_segment
  ON audio_event_embeddings (user_id, video_hash, segment_id);
CREATE INDEX IF NOT EXISTS idx_audio_event_embeddings_owner_video
  ON audio_event_embeddings (user_id, video_hash);
CREATE INDEX IF NOT EXISTS idx_audio_event_embeddings_hnsw
  ON audio_event_embeddings USING hnsw (embedding vector_cosine_ops)
  WITH (m = 24, ef_construction = 200);

DO $$
DECLARE
  v_table_name TEXT;
  v_policy RECORD;
BEGIN
  FOREACH v_table_name IN ARRAY ARRAY[
    'transcript_embeddings', 'audio_event_embeddings'
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

-- Catalog-introspection-safe drop, same technique as 009: makes this
-- migration rerunnable regardless of how Postgres renders vector() typmods.
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
        'search_transcript_chunks_by_embedding',
        'search_audio_events_by_embedding'
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

CREATE OR REPLACE FUNCTION search_transcript_chunks_by_embedding(
  p_user_id UUID,
  query_embedding vector(384),
  target_video_hash TEXT,
  match_count INTEGER DEFAULT 5
)
RETURNS TABLE (
  id UUID,
  video_hash TEXT,
  chunk_index INTEGER,
  start_time DOUBLE PRECISION,
  end_time DOUBLE PRECISION,
  start_timestamp TEXT,
  end_timestamp TEXT,
  speaker TEXT,
  segment_count INTEGER,
  chunk_text TEXT,
  similarity DOUBLE PRECISION
)
LANGUAGE plpgsql
SET search_path = public
AS $$
BEGIN
  SET LOCAL hnsw.ef_search = 200;
  RETURN QUERY
  SELECT
    te.id,
    te.video_hash,
    te.chunk_index,
    te.start_time,
    te.end_time,
    te.start_timestamp,
    te.end_timestamp,
    te.speaker,
    te.segment_count,
    te.chunk_text,
    1 - (te.embedding <=> query_embedding) AS similarity
  FROM transcript_embeddings AS te
  WHERE te.user_id = p_user_id
    AND te.video_hash = target_video_hash
  ORDER BY te.embedding <=> query_embedding
  LIMIT GREATEST(match_count, 0);
END;
$$;

CREATE OR REPLACE FUNCTION search_audio_events_by_embedding(
  p_user_id UUID,
  query_embedding vector(384),
  target_video_hash TEXT,
  match_count INTEGER DEFAULT 5
)
RETURNS TABLE (
  id UUID,
  video_hash TEXT,
  segment_id TEXT,
  start_time DOUBLE PRECISION,
  end_time DOUBLE PRECISION,
  speaker TEXT,
  has_speech BOOLEAN,
  primary_event TEXT,
  speech_emotion TEXT,
  description TEXT,
  similarity DOUBLE PRECISION
)
LANGUAGE plpgsql
SET search_path = public
AS $$
BEGIN
  SET LOCAL hnsw.ef_search = 200;
  RETURN QUERY
  SELECT
    ae.id,
    ae.video_hash,
    ae.segment_id,
    ae.start_time,
    ae.end_time,
    ae.speaker,
    ae.has_speech,
    ae.primary_event,
    ae.speech_emotion,
    ae.description,
    1 - (ae.embedding <=> query_embedding) AS similarity
  FROM audio_event_embeddings AS ae
  WHERE ae.user_id = p_user_id
    AND ae.video_hash = target_video_hash
  ORDER BY ae.embedding <=> query_embedding
  LIMIT GREATEST(match_count, 0);
END;
$$;

REVOKE ALL ON FUNCTION search_transcript_chunks_by_embedding(UUID, vector, TEXT, INTEGER) FROM PUBLIC, authenticated;
REVOKE ALL ON FUNCTION search_audio_events_by_embedding(UUID, vector, TEXT, INTEGER) FROM PUBLIC, authenticated;
GRANT EXECUTE ON FUNCTION search_transcript_chunks_by_embedding(UUID, vector, TEXT, INTEGER) TO service_role;
GRANT EXECUTE ON FUNCTION search_audio_events_by_embedding(UUID, vector, TEXT, INTEGER) TO service_role;

COMMIT;
