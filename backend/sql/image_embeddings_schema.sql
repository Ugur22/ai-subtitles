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
CREATE INDEX idx_image_embeddings_hnsw ON image_embeddings
    USING hnsw (embedding vector_cosine_ops);

-- Row Level Security (RLS)
ALTER TABLE image_embeddings ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Full access" ON image_embeddings FOR ALL USING (true) WITH CHECK (true);

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
AS $$
BEGIN
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

-- Comment on table
COMMENT ON TABLE image_embeddings IS 'CLIP embeddings for video screenshots, enabling text-to-image search';
