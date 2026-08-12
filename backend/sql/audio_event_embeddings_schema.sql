-- AI-Subs Audio Event Embeddings Schema for Supabase
-- Run this in Supabase SQL Editor to set up pgvector for audio-event search
-- IMPORTANT: Enable pgvector extension first in Supabase dashboard
--
-- This file documents the table as it exists after migrations/010_owner_scoped_transcript_audio_embeddings.sql
-- has been applied. Run the migration, not this file, against an existing project.

CREATE EXTENSION IF NOT EXISTS vector;

-- sentence-transformers all-MiniLM-L6-v2 embeddings are 384 dimensions
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
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT unique_owner_video_segment UNIQUE (user_id, video_hash, segment_id)
);

CREATE INDEX IF NOT EXISTS idx_audio_event_embeddings_owner_video
  ON audio_event_embeddings (user_id, video_hash);

-- HNSW index for fast similarity search (can be created on an empty table)
-- m=24 and ef_construction=200 improve recall for large sets of similar events
CREATE INDEX IF NOT EXISTS idx_audio_event_embeddings_hnsw ON audio_event_embeddings
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 24, ef_construction = 200);

ALTER TABLE audio_event_embeddings ENABLE ROW LEVEL SECURITY;

CREATE POLICY audio_event_embeddings_select_own ON audio_event_embeddings
  FOR SELECT TO authenticated
  USING ((SELECT auth.uid()) = user_id);

CREATE POLICY audio_event_embeddings_service_role_all ON audio_event_embeddings
  FOR ALL TO service_role
  USING (true) WITH CHECK (true);

-- Function to search audio events by embedding; see migrations/010 for the
-- canonical, rerun-safe definition (this mirrors it for fresh setups).
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
    FROM audio_event_embeddings ae
    WHERE ae.user_id = p_user_id
      AND ae.video_hash = target_video_hash
    ORDER BY ae.embedding <=> query_embedding
    LIMIT GREATEST(match_count, 0);
END;
$$;

REVOKE ALL ON FUNCTION search_audio_events_by_embedding(UUID, vector, TEXT, INTEGER) FROM PUBLIC, authenticated;
GRANT EXECUTE ON FUNCTION search_audio_events_by_embedding(UUID, vector, TEXT, INTEGER) TO service_role;

COMMENT ON TABLE audio_event_embeddings IS 'MiniLM embeddings for audio-event descriptions, enabling semantic audio search';
