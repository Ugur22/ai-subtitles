BEGIN;

-- Adds a named "index configuration" dimension to transcript_embeddings so
-- multiple chunk-size experiments can be indexed side by side for the same
-- video without overwriting each other. Existing rows (all indexed at the
-- historical hardcoded chunk_size=3) backfill to 'chunk_size_3', and the
-- search RPC defaults to the same value, so callers that don't pass
-- target_index_config (i.e. every production call site today) see
-- byte-identical behavior to before this migration.

ALTER TABLE transcript_embeddings
  ADD COLUMN IF NOT EXISTS index_config TEXT NOT NULL DEFAULT 'chunk_size_3';

DROP INDEX IF EXISTS idx_transcript_embeddings_owner_video_chunk;
CREATE UNIQUE INDEX IF NOT EXISTS idx_transcript_embeddings_owner_video_config_chunk
  ON transcript_embeddings (user_id, video_hash, index_config, chunk_index);

-- Catalog-introspection-safe drop, same technique as 010/012: makes this
-- migration rerunnable regardless of how Postgres renders vector() typmods,
-- and lets us change the function's argument list (CREATE OR REPLACE cannot
-- add a parameter to an existing signature).
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
      AND proc.proname = 'search_transcript_chunks_by_embedding'
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
  FROM transcript_embeddings AS te
  WHERE te.user_id = p_user_id
    AND te.video_hash = target_video_hash
    AND te.index_config = target_index_config
  ORDER BY te.embedding <=> query_embedding
  LIMIT GREATEST(match_count, 0);
END;
$$;

REVOKE ALL ON FUNCTION search_transcript_chunks_by_embedding(UUID, vector, TEXT, INTEGER, TEXT) FROM PUBLIC, authenticated;
GRANT EXECUTE ON FUNCTION search_transcript_chunks_by_embedding(UUID, vector, TEXT, INTEGER, TEXT) TO service_role;

COMMIT;
