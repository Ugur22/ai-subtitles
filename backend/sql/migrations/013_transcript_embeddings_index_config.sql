BEGIN;

-- New tables preserve the MiniLM data and old API during schema-first deployment and rollback.
CREATE TABLE IF NOT EXISTS transcript_embeddings_v2 (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
  video_hash TEXT NOT NULL,
  embedding_model TEXT NOT NULL,
  index_config TEXT NOT NULL DEFAULT 'chunk_size_3' CHECK (index_config IN ('chunk_size_2', 'chunk_size_3', 'chunk_size_5')),
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

CREATE TABLE IF NOT EXISTS audio_event_embeddings_v2 (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
  video_hash TEXT NOT NULL,
  embedding_model TEXT NOT NULL,
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

CREATE UNIQUE INDEX IF NOT EXISTS idx_transcript_v2_owner_model_config_chunk
  ON transcript_embeddings_v2 (user_id, video_hash, embedding_model, index_config, chunk_index);
CREATE UNIQUE INDEX IF NOT EXISTS idx_audio_v2_owner_model_segment
  ON audio_event_embeddings_v2 (user_id, video_hash, embedding_model, segment_id);
CREATE INDEX IF NOT EXISTS idx_transcript_v2_embedding_hnsw
  ON transcript_embeddings_v2 USING hnsw (embedding vector_cosine_ops)
  WITH (m = 24, ef_construction = 200);
CREATE INDEX IF NOT EXISTS idx_audio_v2_embedding_hnsw
  ON audio_event_embeddings_v2 USING hnsw (embedding vector_cosine_ops)
  WITH (m = 24, ef_construction = 200);

DO $$
DECLARE
  v_table_name TEXT;
  v_policy RECORD;
BEGIN
  FOREACH v_table_name IN ARRAY ARRAY[
    'transcript_embeddings_v2', 'audio_event_embeddings_v2'
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

REVOKE ALL ON transcript_embeddings_v2, audio_event_embeddings_v2 FROM anon, authenticated;
GRANT SELECT ON transcript_embeddings_v2, audio_event_embeddings_v2 TO authenticated;
GRANT ALL ON transcript_embeddings_v2, audio_event_embeddings_v2 TO service_role;

CREATE OR REPLACE FUNCTION replace_transcript_embedding_index(
  p_user_id UUID,
  target_video_hash TEXT,
  p_embedding_model TEXT,
  p_rows JSONB,
  target_index_config TEXT DEFAULT 'chunk_size_3'
)
RETURNS INTEGER
LANGUAGE plpgsql
SET search_path = public
AS $$
DECLARE inserted_count INTEGER;
BEGIN
  IF p_user_id IS NULL OR COALESCE(target_video_hash, '') = '' OR COALESCE(p_embedding_model, '') = ''
     OR jsonb_typeof(p_rows) IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'Owner, video, embedding model and an array of rows are required';
  END IF;
  -- Concurrent rebuilds of the same model/index must publish one complete result at a time.
  PERFORM pg_advisory_xact_lock(hashtextextended(
    p_user_id::text || '|' || target_video_hash || '|' || p_embedding_model || '|transcript' || '|' || target_index_config, 0
  ));
  DELETE FROM transcript_embeddings_v2
  WHERE user_id = p_user_id AND video_hash = target_video_hash
    AND embedding_model = p_embedding_model
    AND index_config = target_index_config;
  INSERT INTO transcript_embeddings_v2 (user_id, video_hash, embedding_model, index_config, chunk_index, start_time, end_time, start_timestamp, end_timestamp, speaker, segment_count, chunk_text, embedding)
    SELECT p_user_id, target_video_hash, p_embedding_model, target_index_config,
      (r->>'chunk_index')::integer, (r->>'start_time')::double precision,
      (r->>'end_time')::double precision, r->>'start_timestamp', r->>'end_timestamp',
      r->>'speaker', (r->>'segment_count')::integer, r->>'chunk_text',
      (r->'embedding')::text::vector
    FROM jsonb_array_elements(p_rows) AS r;
  GET DIAGNOSTICS inserted_count = ROW_COUNT;
  RETURN inserted_count;
END;
$$;

CREATE OR REPLACE FUNCTION search_transcript_chunks_by_embedding_v2(
  p_user_id UUID,
  query_embedding vector(384),
  p_embedding_model TEXT,
  target_video_hash TEXT,
  match_count INTEGER DEFAULT 5,
  target_index_config TEXT DEFAULT 'chunk_size_3'
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
  FROM transcript_embeddings_v2 AS te
  WHERE te.user_id = p_user_id
    AND te.video_hash = target_video_hash
    AND te.embedding_model = p_embedding_model
    AND te.index_config = target_index_config
  ORDER BY te.embedding <=> query_embedding
  LIMIT GREATEST(match_count, 0);
END;
$$;

REVOKE ALL ON FUNCTION replace_transcript_embedding_index(UUID, TEXT, TEXT, JSONB, TEXT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION replace_transcript_embedding_index(UUID, TEXT, TEXT, JSONB, TEXT) TO service_role;
REVOKE ALL ON FUNCTION search_transcript_chunks_by_embedding_v2(UUID, vector, TEXT, TEXT, INTEGER, TEXT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION search_transcript_chunks_by_embedding_v2(UUID, vector, TEXT, TEXT, INTEGER, TEXT) TO service_role;

CREATE OR REPLACE FUNCTION replace_audio_embedding_index(
  p_user_id UUID,
  target_video_hash TEXT,
  p_embedding_model TEXT,
  p_rows JSONB
)
RETURNS INTEGER
LANGUAGE plpgsql
SET search_path = public
AS $$
DECLARE inserted_count INTEGER;
BEGIN
  IF p_user_id IS NULL OR COALESCE(target_video_hash, '') = '' OR COALESCE(p_embedding_model, '') = ''
     OR jsonb_typeof(p_rows) IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'Owner, video, embedding model and an array of rows are required';
  END IF;
  -- Concurrent rebuilds of the same model/index must publish one complete result at a time.
  PERFORM pg_advisory_xact_lock(hashtextextended(
    p_user_id::text || '|' || target_video_hash || '|' || p_embedding_model || '|audio', 0
  ));
  DELETE FROM audio_event_embeddings_v2
  WHERE user_id = p_user_id AND video_hash = target_video_hash
    AND embedding_model = p_embedding_model;
  INSERT INTO audio_event_embeddings_v2 (user_id, video_hash, embedding_model, segment_id, start_time, end_time, speaker, has_speech, primary_event, speech_emotion, description, embedding)
    SELECT p_user_id, target_video_hash, p_embedding_model, r->>'segment_id',
      (r->>'start_time')::double precision, (r->>'end_time')::double precision,
      r->>'speaker', COALESCE((r->>'has_speech')::boolean, false),
      r->>'primary_event', r->>'speech_emotion', r->>'description',
      (r->'embedding')::text::vector
    FROM jsonb_array_elements(p_rows) AS r;
  GET DIAGNOSTICS inserted_count = ROW_COUNT;
  RETURN inserted_count;
END;
$$;

CREATE OR REPLACE FUNCTION search_audio_events_by_embedding_v2(
  p_user_id UUID,
  query_embedding vector(384),
  p_embedding_model TEXT,
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
  FROM audio_event_embeddings_v2 AS ae
  WHERE ae.user_id = p_user_id
    AND ae.video_hash = target_video_hash
    AND ae.embedding_model = p_embedding_model
  ORDER BY ae.embedding <=> query_embedding
  LIMIT GREATEST(match_count, 0);
END;
$$;

REVOKE ALL ON FUNCTION replace_audio_embedding_index(UUID, TEXT, TEXT, JSONB) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION replace_audio_embedding_index(UUID, TEXT, TEXT, JSONB) TO service_role;
REVOKE ALL ON FUNCTION search_audio_events_by_embedding_v2(UUID, vector, TEXT, TEXT, INTEGER) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION search_audio_events_by_embedding_v2(UUID, vector, TEXT, TEXT, INTEGER) TO service_role;

CREATE OR REPLACE FUNCTION cleanup_deleted_job_text_indexes_v2()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM public.jobs
    WHERE user_id = OLD.user_id AND video_hash = OLD.video_hash
  ) THEN
    DELETE FROM public.transcript_embeddings_v2
      WHERE user_id = OLD.user_id AND video_hash = OLD.video_hash;
    DELETE FROM public.audio_event_embeddings_v2
      WHERE user_id = OLD.user_id AND video_hash = OLD.video_hash;
  END IF;
  RETURN OLD;
END;
$$;
REVOKE ALL ON FUNCTION cleanup_deleted_job_text_indexes_v2() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION cleanup_deleted_job_text_indexes_v2() TO service_role;
DROP TRIGGER IF EXISTS cleanup_deleted_job_text_indexes_v2 ON public.jobs;
CREATE TRIGGER cleanup_deleted_job_text_indexes_v2
  AFTER DELETE ON public.jobs FOR EACH ROW
  EXECUTE FUNCTION cleanup_deleted_job_text_indexes_v2();

COMMIT;
