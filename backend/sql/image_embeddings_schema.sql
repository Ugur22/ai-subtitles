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
    user_id UUID NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
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
    CONSTRAINT unique_video_segment UNIQUE (user_id, video_hash, segment_id),
    CONSTRAINT unique_image_owner_id UNIQUE (user_id, id)
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

CREATE POLICY image_embeddings_select_own ON image_embeddings
  FOR SELECT TO authenticated USING ((SELECT auth.uid()) = user_id);

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
    p_user_id UUID,
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
    WHERE ie.user_id = p_user_id AND ie.video_hash = target_video_hash
      AND (speaker_filter IS NULL OR ie.speaker = speaker_filter)
    ORDER BY ie.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;

-- Comment on table
COMMENT ON TABLE image_embeddings IS 'CLIP embeddings for video screenshots, enabling text-to-image search';

REVOKE ALL ON FUNCTION search_images_by_embedding(UUID, vector, TEXT, INTEGER, TEXT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION search_images_by_embedding(UUID, vector, TEXT, INTEGER, TEXT) TO service_role;



ALTER TABLE public.image_embeddings ADD COLUMN IF NOT EXISTS caption TEXT;
ALTER TABLE public.image_embeddings ADD COLUMN IF NOT EXISTS caption_embedding vector(384);
ALTER TABLE public.image_embeddings ADD COLUMN IF NOT EXISTS caption_embedding_model TEXT;

CREATE INDEX IF NOT EXISTS idx_image_embeddings_caption_hnsw ON public.image_embeddings
  USING hnsw (caption_embedding vector_cosine_ops) WITH (m = 16, ef_construction = 100);
CREATE UNIQUE INDEX IF NOT EXISTS idx_image_embeddings_owner_id
  ON public.image_embeddings (user_id, id);

CREATE TABLE IF NOT EXISTS public.image_caption_sentences (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES public.user_profiles(id) ON DELETE CASCADE,
  video_hash TEXT NOT NULL,
  image_embedding_id UUID NOT NULL,
  embedding_model TEXT NOT NULL,
  sentence TEXT NOT NULL,
  embedding vector(384) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT caption_sentence_owner_image_fkey FOREIGN KEY (user_id, image_embedding_id)
    REFERENCES public.image_embeddings(user_id, id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_caption_sentences_owner_video_model
  ON public.image_caption_sentences (user_id, video_hash, embedding_model);
CREATE INDEX IF NOT EXISTS idx_caption_sentences_image ON public.image_caption_sentences (image_embedding_id);

ALTER TABLE public.image_caption_sentences ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS caption_sentences_select_own ON public.image_caption_sentences;
CREATE POLICY caption_sentences_select_own ON public.image_caption_sentences
  FOR SELECT TO authenticated USING ((SELECT auth.uid()) = user_id);
DROP POLICY IF EXISTS caption_sentences_service_all ON public.image_caption_sentences;
CREATE POLICY caption_sentences_service_all ON public.image_caption_sentences
  FOR ALL TO service_role USING (true) WITH CHECK (true);
REVOKE ALL ON public.image_caption_sentences FROM anon, authenticated;
GRANT SELECT ON public.image_caption_sentences TO authenticated;
GRANT ALL ON public.image_caption_sentences TO service_role;

CREATE OR REPLACE FUNCTION public.caption_frames_to_process(
  p_user_id UUID, target_video_hash TEXT, target_embedding_model TEXT,
  batch_limit INTEGER DEFAULT 120, include_existing BOOLEAN DEFAULT false
)
RETURNS TABLE (id UUID, segment_id TEXT, screenshot_url TEXT, caption TEXT)
LANGUAGE sql SET search_path = public AS $$
  SELECT ie.id, ie.segment_id, ie.screenshot_url, ie.caption
  FROM image_embeddings ie
  WHERE ie.user_id = p_user_id AND ie.video_hash = target_video_hash
    AND (include_existing OR ie.caption IS NULL OR ie.caption_embedding IS NULL
         OR ie.caption_embedding_model IS DISTINCT FROM target_embedding_model)
  ORDER BY ie.start_time, ie.id
  LIMIT LEAST(GREATEST(batch_limit, 0), 1000);
$$;

CREATE OR REPLACE FUNCTION public.search_images_by_caption_sentences(
  p_user_id UUID, query_embedding vector(384), target_video_hash TEXT,
  target_embedding_model TEXT, match_count INTEGER DEFAULT 6
)
RETURNS TABLE (
  id UUID, video_hash TEXT, segment_id TEXT, start_time DOUBLE PRECISION,
  end_time DOUBLE PRECISION, speaker TEXT, screenshot_url TEXT, caption TEXT,
  similarity DOUBLE PRECISION
)
LANGUAGE sql SET search_path = public AS $$
  SELECT ie.id, ie.video_hash, ie.segment_id, ie.start_time, ie.end_time,
         ie.speaker, ie.screenshot_url, ie.caption,
         GREATEST(1 - (ie.caption_embedding <=> query_embedding), sentence_score.similarity) AS similarity
  FROM image_embeddings ie
  LEFT JOIN LATERAL (
    SELECT MAX(1 - (ics.embedding <=> query_embedding)) AS similarity
    FROM image_caption_sentences ics
    WHERE ics.user_id = p_user_id AND ics.video_hash = target_video_hash
      AND ics.image_embedding_id = ie.id AND ics.embedding_model = target_embedding_model
  ) sentence_score ON true
  WHERE ie.user_id = p_user_id AND ie.video_hash = target_video_hash
    AND ie.caption_embedding_model = target_embedding_model AND ie.caption_embedding IS NOT NULL
  ORDER BY similarity DESC
  LIMIT LEAST(GREATEST(match_count, 0), 100);
$$;

CREATE OR REPLACE FUNCTION public.store_image_caption(
  p_user_id UUID, target_video_hash TEXT, image_id UUID, caption_text TEXT,
  caption_vector vector(384), target_embedding_model TEXT, sentence_rows JSONB
)
RETURNS BOOLEAN LANGUAGE plpgsql SET search_path = public AS $$
DECLARE sentence_row JSONB;
BEGIN
  PERFORM 1 FROM image_embeddings ie
  WHERE ie.user_id = p_user_id AND ie.video_hash = target_video_hash AND ie.id = image_id
  FOR UPDATE;
  IF NOT FOUND THEN RETURN false; END IF;

  DELETE FROM image_caption_sentences ics
  WHERE ics.user_id = p_user_id AND ics.video_hash = target_video_hash
    AND ics.image_embedding_id = image_id AND ics.embedding_model = target_embedding_model;
  FOR sentence_row IN SELECT value FROM jsonb_array_elements(COALESCE(sentence_rows, '[]'::jsonb))
  LOOP
    INSERT INTO image_caption_sentences
      (user_id, video_hash, image_embedding_id, embedding_model, sentence, embedding)
    VALUES (p_user_id, target_video_hash, image_id, target_embedding_model,
      sentence_row->>'sentence', (sentence_row->'embedding')::text::vector(384));
  END LOOP;
  UPDATE image_embeddings ie SET caption = caption_text, caption_embedding = caption_vector,
    caption_embedding_model = target_embedding_model
  WHERE ie.user_id = p_user_id AND ie.video_hash = target_video_hash AND ie.id = image_id;
  RETURN true;
END;
$$;

CREATE OR REPLACE FUNCTION public.videos_missing_captions(
  target_embedding_model TEXT, batch_limit INTEGER DEFAULT 3
)
RETURNS TABLE (user_id UUID, video_hash TEXT)
LANGUAGE sql SET search_path = public AS $$
  SELECT DISTINCT ie.user_id, ie.video_hash
  FROM image_embeddings ie
  WHERE ie.caption IS NULL OR ie.caption_embedding IS NULL
    OR ie.caption_embedding_model IS DISTINCT FROM target_embedding_model
  ORDER BY ie.user_id, ie.video_hash
  LIMIT LEAST(GREATEST(batch_limit, 0), 10);
$$;

REVOKE ALL ON FUNCTION public.caption_frames_to_process(UUID, TEXT, TEXT, INTEGER, BOOLEAN) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.search_images_by_caption_sentences(UUID, vector, TEXT, TEXT, INTEGER) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.videos_missing_captions(TEXT, INTEGER) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.store_image_caption(UUID, TEXT, UUID, TEXT, vector, TEXT, JSONB) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.caption_frames_to_process(UUID, TEXT, TEXT, INTEGER, BOOLEAN) TO service_role;
GRANT EXECUTE ON FUNCTION public.search_images_by_caption_sentences(UUID, vector, TEXT, TEXT, INTEGER) TO service_role;
GRANT EXECUTE ON FUNCTION public.videos_missing_captions(TEXT, INTEGER) TO service_role;
GRANT EXECUTE ON FUNCTION public.store_image_caption(UUID, TEXT, UUID, TEXT, vector, TEXT, JSONB) TO service_role;
