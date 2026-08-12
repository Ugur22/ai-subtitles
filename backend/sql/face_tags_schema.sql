-- Face Tags Schema for Supabase
-- Stores face bounding boxes + ArcFace embeddings tagged with speaker names
-- Used to boost scene search results with face matching
-- IMPORTANT: Requires pgvector extension (already enabled for image_embeddings)

-- Face tags table using pgvector
-- ArcFace embeddings are 512 dimensions
CREATE TABLE face_tags (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    video_hash TEXT NOT NULL,
    speaker_name TEXT NOT NULL,
    screenshot_url TEXT NOT NULL,
    bbox_x FLOAT NOT NULL,
    bbox_y FLOAT NOT NULL,
    bbox_w FLOAT NOT NULL,
    bbox_h FLOAT NOT NULL,
    embedding vector(512) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),

    -- Prevent duplicate tags for the same face region
    CONSTRAINT unique_face_tag UNIQUE (video_hash, screenshot_url, bbox_x, bbox_y)
);

-- Indexes for common queries
CREATE INDEX idx_face_tags_video_hash ON face_tags(video_hash);
CREATE INDEX idx_face_tags_speaker ON face_tags(video_hash, speaker_name);

-- HNSW index for fast face similarity search
CREATE INDEX idx_face_tags_hnsw ON face_tags
    USING hnsw (embedding vector_cosine_ops);

-- Row Level Security (RLS)
ALTER TABLE face_tags ENABLE ROW LEVEL SECURITY;

-- 1. Users can read face tags for videos they own
CREATE POLICY "Users read own video face tags" ON face_tags
  FOR SELECT
  USING (
    EXISTS (
      SELECT 1 FROM jobs
      WHERE jobs.video_hash = face_tags.video_hash
      AND jobs.user_id = auth.uid()
    )
  );

-- 2. Legacy: Allow access to face tags for videos without user_id
CREATE POLICY "Legacy video face tags read-only" ON face_tags
  FOR SELECT
  USING (
    auth.uid() IS NOT NULL
    AND EXISTS (
      SELECT 1 FROM jobs
      WHERE jobs.video_hash = face_tags.video_hash
      AND jobs.user_id IS NULL
    )
  );

-- 3. Allow all inserts (backend API is auth-protected, service key bypasses RLS)
CREATE POLICY "Allow insert face tags" ON face_tags
  FOR INSERT WITH CHECK (true);

CREATE POLICY "Allow update face tags" ON face_tags
  FOR UPDATE USING (true);

CREATE POLICY "Allow delete face tags" ON face_tags
  FOR DELETE USING (true);

COMMENT ON TABLE face_tags IS 'ArcFace embeddings for tagged faces in video screenshots, enabling face-based scene search boosting';
