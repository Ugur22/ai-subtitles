-- AI-Subs Image Embeddings Schema for Supabase
-- Version: 1.0
-- Run this in Supabase SQL Editor to set up pgvector for image search
-- IMPORTANT: Enable pgvector extension first in Supabase dashboard

-- Enable pgvector extension (must be done first)
CREATE EXTENSION IF NOT EXISTS vector;

-- Drop existing table if it exists
DROP TABLE IF EXISTS image_embeddings CASCADE;

-- Image embeddings table using pgvector
-- CLIP embeddings are 512 dimensions
CREATE TABLE image_embeddings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    video_hash TEXT NOT NULL,
    segment_id TEXT NOT NULL,
    start_time FLOAT NOT NULL,
    end_time FLOAT NOT NULL,
    speaker TEXT,
    screenshot_url TEXT NOT NULL,
    embedding vector(512) NOT NULL,
    caption TEXT,
    caption_embedding vector(384),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Unique constraint to prevent duplicates
    CONSTRAINT unique_video_segment UNIQUE (video_hash, segment_id)
);

-- Indexes for common queries
CREATE INDEX idx_image_embeddings_video_hash ON image_embeddings(video_hash);
CREATE INDEX idx_image_embeddings_segment_id ON image_embeddings(segment_id);
CREATE INDEX idx_image_embeddings_speaker ON image_embeddings(speaker);

-- IVFFlat index for fast similarity search (requires some data to build)
-- Run this after inserting initial data:
-- CREATE INDEX idx_image_embeddings_vector ON image_embeddings
--     USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- HNSW index for very fast similarity search (can be created on empty table)
-- m=24 and ef_construction=200 improve recall for large sets of similar images
CREATE INDEX idx_image_embeddings_hnsw ON image_embeddings
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 24, ef_construction = 200);

-- Row Level Security (RLS)
ALTER TABLE image_embeddings ENABLE ROW LEVEL SECURITY;

-- 1. Users can only search embeddings for videos they own
CREATE POLICY "Users search own video embeddings" ON image_embeddings
  FOR SELECT
  USING (
    EXISTS (
      SELECT 1 FROM jobs
      WHERE jobs.video_hash = image_embeddings.video_hash
      AND jobs.user_id = auth.uid()
    )
  );

-- 2. Legacy: Allow access to embeddings for videos without user_id
CREATE POLICY "Legacy video embeddings read-only" ON image_embeddings
  FOR SELECT
  USING (
    auth.uid() IS NOT NULL
    AND EXISTS (
      SELECT 1 FROM jobs
      WHERE jobs.video_hash = image_embeddings.video_hash
      AND jobs.user_id IS NULL
    )
  );

-- 3. Only service role can write embeddings
CREATE POLICY "Service role write access" ON image_embeddings
  FOR INSERT
  TO service_role
  WITH CHECK (true);

-- 4. Only service role can update embeddings
CREATE POLICY "Service role update access" ON image_embeddings
  FOR UPDATE
  TO service_role
  USING (true);

-- 5. Only service role can delete embeddings
CREATE POLICY "Service role delete access" ON image_embeddings
  FOR DELETE
  TO service_role
  USING (true);

-- Function to search images by text embedding
CREATE OR REPLACE FUNCTION search_images_by_embedding(
    query_embedding vector(512),
    target_video_hash TEXT,
    match_count INT DEFAULT 5,
    speaker_filter TEXT DEFAULT NULL
)
RETURNS TABLE (
    id UUID,
    video_hash TEXT,
    segment_id TEXT,
    start_time FLOAT,
    end_time FLOAT,
    speaker TEXT,
    screenshot_url TEXT,
    similarity FLOAT
)
LANGUAGE plpgsql
SET search_path = public
AS $$
BEGIN
    -- Increase HNSW search scope for better recall on large/similar image sets
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
    FROM image_embeddings ie
    WHERE ie.video_hash = target_video_hash
      AND (speaker_filter IS NULL OR ie.speaker = speaker_filter)
    ORDER BY ie.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;

-- HNSW index for caption similarity search
CREATE INDEX idx_image_embeddings_caption_hnsw ON image_embeddings
    USING hnsw (caption_embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 100);

-- Function to search images by caption text embedding (all-MiniLM, 384-dim)
CREATE OR REPLACE FUNCTION search_images_by_caption_embedding(
    query_embedding vector(384),
    target_video_hash TEXT,
    match_count INT DEFAULT 5
)
RETURNS TABLE (
    id UUID,
    video_hash TEXT,
    segment_id TEXT,
    start_time FLOAT,
    end_time FLOAT,
    speaker TEXT,
    screenshot_url TEXT,
    caption TEXT,
    similarity FLOAT
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
        ie.caption,
        1 - (ie.caption_embedding <=> query_embedding) AS similarity
    FROM image_embeddings ie
    WHERE ie.video_hash = target_video_hash
      AND ie.caption_embedding IS NOT NULL
    ORDER BY ie.caption_embedding <=> query_embedding
    LIMIT match_count;
END;
$$;

-- Discovery RPC for the caption backfill endpoint
CREATE OR REPLACE FUNCTION videos_missing_captions(batch_limit INT DEFAULT 10)
RETURNS TABLE (video_hash TEXT)
LANGUAGE sql
SET search_path = public
AS $$
    SELECT DISTINCT ie.video_hash
    FROM image_embeddings ie
    WHERE ie.caption IS NULL
    ORDER BY ie.video_hash
    LIMIT batch_limit;
$$;

-- Per-sentence caption index (see migrations/005): retrieval scores the query
-- against each caption sentence and takes the per-image max, because
-- full-caption embeddings dilute the action with scene details.
CREATE TABLE IF NOT EXISTS image_caption_sentences (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    image_embedding_id UUID NOT NULL REFERENCES image_embeddings(id) ON DELETE CASCADE,
    video_hash TEXT NOT NULL,
    sentence TEXT NOT NULL,
    embedding vector(384) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ics_video_hash ON image_caption_sentences(video_hash);
CREATE INDEX IF NOT EXISTS idx_ics_image_id ON image_caption_sentences(image_embedding_id);

ALTER TABLE image_caption_sentences ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role all access ics" ON image_caption_sentences
  FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE POLICY "Users read own caption sentences" ON image_caption_sentences
  FOR SELECT USING (
    EXISTS (
      SELECT 1 FROM jobs
      WHERE jobs.video_hash = image_caption_sentences.video_hash
      AND jobs.user_id = auth.uid()
    )
  );

CREATE OR REPLACE FUNCTION search_images_by_caption_sentences(
    query_embedding vector(384),
    target_video_hash TEXT,
    match_count INT DEFAULT 5
)
RETURNS TABLE (
    id UUID, video_hash TEXT, segment_id TEXT, start_time FLOAT, end_time FLOAT,
    speaker TEXT, screenshot_url TEXT, caption TEXT, similarity FLOAT
)
LANGUAGE sql
SET search_path = public
AS $$
    SELECT ie.id, ie.video_hash, ie.segment_id, ie.start_time, ie.end_time,
           ie.speaker, ie.screenshot_url, ie.caption, s.max_sim AS similarity
    FROM (
        SELECT ics.image_embedding_id,
               MAX(1 - (ics.embedding <=> query_embedding)) AS max_sim
        FROM image_caption_sentences ics
        WHERE ics.video_hash = target_video_hash
        GROUP BY ics.image_embedding_id
        ORDER BY max_sim DESC
        LIMIT match_count
    ) s
    JOIN image_embeddings ie ON ie.id = s.image_embedding_id
    ORDER BY s.max_sim DESC;
$$;

-- Comment on table
COMMENT ON TABLE image_embeddings IS 'CLIP embeddings for video screenshots, enabling text-to-image search';
