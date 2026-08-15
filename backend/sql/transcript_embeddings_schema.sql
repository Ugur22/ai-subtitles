-- AI-Subs Transcript Embeddings Schema for Supabase
-- Run this in Supabase SQL Editor to set up pgvector for transcript search
-- IMPORTANT: Enable pgvector extension first in Supabase dashboard
--
-- This file documents the table as it exists after migrations/010_owner_scoped_transcript_audio_embeddings.sql
-- has been applied. Run the migration, not this file, against an existing project.

CREATE EXTENSION IF NOT EXISTS vector;

-- sentence-transformers all-MiniLM-L6-v2 embeddings are 384 dimensions
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
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT unique_owner_video_chunk UNIQUE (user_id, video_hash, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_transcript_embeddings_owner_video
  ON transcript_embeddings (user_id, video_hash);

-- HNSW index for fast similarity search (can be created on an empty table)
-- m=24 and ef_construction=200 improve recall for large sets of similar chunks
CREATE INDEX IF NOT EXISTS idx_transcript_embeddings_hnsw ON transcript_embeddings
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 24, ef_construction = 200);

ALTER TABLE transcript_embeddings ENABLE ROW LEVEL SECURITY;

CREATE POLICY transcript_embeddings_select_own ON transcript_embeddings
  FOR SELECT TO authenticated
  USING ((SELECT auth.uid()) = user_id);

CREATE POLICY transcript_embeddings_service_role_all ON transcript_embeddings
  FOR ALL TO service_role
  USING (true) WITH CHECK (true);

-- Function to search transcript chunks by embedding; see migrations/010 for
-- the canonical, rerun-safe definition (this mirrors it for fresh setups).
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
    FROM transcript_embeddings te
    WHERE te.user_id = p_user_id
      AND te.video_hash = target_video_hash
    ORDER BY te.embedding <=> query_embedding
    LIMIT GREATEST(match_count, 0);
END;
$$;

REVOKE ALL ON FUNCTION search_transcript_chunks_by_embedding(UUID, vector, TEXT, INTEGER) FROM PUBLIC, authenticated;
GRANT EXECUTE ON FUNCTION search_transcript_chunks_by_embedding(UUID, vector, TEXT, INTEGER) TO service_role;

COMMENT ON TABLE transcript_embeddings IS 'MiniLM embeddings for transcript chunks, enabling semantic transcript search';
