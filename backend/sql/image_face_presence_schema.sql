-- AI-Subs Face Presence Index Schema
-- One row per detected face in an indexed screenshot.
-- Powers character-specific scene search by replacing query-time face detection
-- with a vector similarity lookup, and replaces speaker-voice temporal overlap
-- with on-screen face presence overlap.
--
-- Apply via Supabase SQL Editor. Safe to re-apply (idempotent).

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS image_face_presence (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    image_embedding_id UUID NOT NULL REFERENCES image_embeddings(id) ON DELETE CASCADE,
    video_hash TEXT NOT NULL,
    start_time FLOAT NOT NULL,
    end_time FLOAT NOT NULL,
    face_embedding vector(512) NOT NULL,
    bbox JSONB,
    det_score FLOAT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ifp_video_hash ON image_face_presence(video_hash);
CREATE INDEX IF NOT EXISTS idx_ifp_image_id ON image_face_presence(image_embedding_id);

-- HNSW for cosine similarity over ArcFace embeddings
CREATE INDEX IF NOT EXISTS idx_ifp_hnsw ON image_face_presence
    USING hnsw (face_embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 100);

ALTER TABLE image_face_presence ENABLE ROW LEVEL SECURITY;

-- Mirror image_embeddings RLS: own-video read, service-role write.
DROP POLICY IF EXISTS "Users read own video face presence" ON image_face_presence;
CREATE POLICY "Users read own video face presence" ON image_face_presence
    FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM jobs
            WHERE jobs.video_hash = image_face_presence.video_hash
            AND jobs.user_id = auth.uid()
        )
    );

DROP POLICY IF EXISTS "Legacy face presence read-only" ON image_face_presence;
CREATE POLICY "Legacy face presence read-only" ON image_face_presence
    FOR SELECT
    USING (
        auth.uid() IS NOT NULL
        AND EXISTS (
            SELECT 1 FROM jobs
            WHERE jobs.video_hash = image_face_presence.video_hash
            AND jobs.user_id IS NULL
        )
    );

DROP POLICY IF EXISTS "Service role face presence write" ON image_face_presence;
CREATE POLICY "Service role face presence write" ON image_face_presence
    FOR INSERT
    TO service_role
    WITH CHECK (true);

DROP POLICY IF EXISTS "Service role face presence update" ON image_face_presence;
CREATE POLICY "Service role face presence update" ON image_face_presence
    FOR UPDATE
    TO service_role
    USING (true);

DROP POLICY IF EXISTS "Service role face presence delete" ON image_face_presence;
CREATE POLICY "Service role face presence delete" ON image_face_presence
    FOR DELETE
    TO service_role
    USING (true);

-- Match a speaker's reference face embedding against every face detected in
-- the video. Returns one row per matching face above the similarity threshold,
-- sorted by similarity descending. Callers use the result to build both:
--   1. A face-presence timeline: list of (start_time, end_time) ranges
--   2. A per-image score lookup keyed by image_embedding_id
CREATE OR REPLACE FUNCTION match_faces_by_embedding(
    target_video_hash TEXT,
    query_embedding vector(512),
    similarity_threshold FLOAT DEFAULT 0.5,
    match_limit INT DEFAULT 500
)
RETURNS TABLE (
    image_embedding_id UUID,
    start_time FLOAT,
    end_time FLOAT,
    similarity FLOAT
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
    FROM image_face_presence ifp
    WHERE ifp.video_hash = target_video_hash
      AND 1 - (ifp.face_embedding <=> query_embedding) >= similarity_threshold
    ORDER BY ifp.face_embedding <=> query_embedding
    LIMIT match_limit;
END;
$$;

COMMENT ON TABLE image_face_presence IS 'InsightFace embeddings for faces detected in indexed screenshots. One row per face.';
COMMENT ON FUNCTION match_faces_by_embedding IS 'Find detected faces matching a reference embedding above a similarity threshold.';

CREATE OR REPLACE FUNCTION videos_missing_face_presence(batch_limit INT DEFAULT 10)
RETURNS TABLE (
    video_hash TEXT
)
LANGUAGE sql
SET search_path = public
AS $$
    SELECT DISTINCT ie.video_hash
    FROM image_embeddings ie
    WHERE NOT EXISTS (
        SELECT 1
        FROM image_face_presence ifp
        WHERE ifp.video_hash = ie.video_hash
    )
    ORDER BY ie.video_hash
    LIMIT batch_limit;
$$;

COMMENT ON FUNCTION videos_missing_face_presence IS 'List videos with image embeddings but no indexed face-presence rows.';
