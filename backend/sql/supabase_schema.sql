-- AI-Subs Background Job Processing Schema for Supabase
-- Version: 2.0
-- Run this in Supabase SQL Editor to set up the required tables

-- Main transcription jobs table
CREATE TABLE transcription_jobs (
    job_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    access_token UUID NOT NULL DEFAULT gen_random_uuid(),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'completed', 'failed', 'cancelled')),
    filename TEXT NOT NULL,
    file_size_bytes BIGINT,
    video_hash TEXT,
    gcs_path TEXT,
    progress INTEGER DEFAULT 0 CHECK (progress >= 0 AND progress <= 100),
    progress_stage TEXT,
    progress_message TEXT,
    error_message TEXT,
    error_code TEXT,
    result_json JSONB,
    result_srt TEXT,
    result_vtt TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    last_seen TIMESTAMP WITH TIME ZONE,
    retry_count INTEGER DEFAULT 0,

    -- Processing parameters
    num_speakers INTEGER,
    min_speakers INTEGER,
    max_speakers INTEGER,
    language TEXT,
    force_language BOOLEAN DEFAULT FALSE
);

-- Enable real-time for transcription_jobs
ALTER PUBLICATION supabase_realtime ADD TABLE transcription_jobs;

-- Indexes for common queries
CREATE INDEX idx_jobs_status ON transcription_jobs(status);
CREATE INDEX idx_jobs_created ON transcription_jobs(created_at DESC);
CREATE INDEX idx_jobs_hash ON transcription_jobs(video_hash);
CREATE INDEX idx_jobs_access_token ON transcription_jobs(access_token);
CREATE INDEX idx_jobs_stale ON transcription_jobs(status, last_seen)
    WHERE status = 'processing';

-- Historical duration tracking for time estimates
CREATE TABLE job_duration_stats (
    id SERIAL PRIMARY KEY,
    file_size_bucket TEXT NOT NULL UNIQUE,  -- '0-100MB', '100-500MB', '500MB+'
    avg_duration_seconds INTEGER NOT NULL,
    sample_count INTEGER DEFAULT 1,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Insert default buckets
INSERT INTO job_duration_stats (file_size_bucket, avg_duration_seconds, sample_count) VALUES
    ('0-100MB', 180, 0),      -- 3 minutes default
    ('100-500MB', 600, 0),    -- 10 minutes default
    ('500MB+', 1800, 0);      -- 30 minutes default

-- Row Level Security (RLS) policies
-- Note: For this app, we use token-based access instead of Supabase Auth
-- The backend service uses the service role key to bypass RLS

-- Enable RLS but allow service role full access
ALTER TABLE transcription_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE job_duration_stats ENABLE ROW LEVEL SECURITY;

-- Policy for service role (backend) - full access
CREATE POLICY "Service role has full access to jobs" ON transcription_jobs
    FOR ALL
    USING (true)
    WITH CHECK (true);

CREATE POLICY "Service role has full access to stats" ON job_duration_stats
    FOR ALL
    USING (true)
    WITH CHECK (true);

-- Function to update duration stats after job completion
CREATE OR REPLACE FUNCTION update_duration_stats()
RETURNS TRIGGER AS $$
DECLARE
    bucket TEXT;
    duration_secs INTEGER;
BEGIN
    -- Only update on completion
    IF NEW.status = 'completed' AND OLD.status = 'processing' THEN
        -- Determine bucket
        IF NEW.file_size_bytes < 104857600 THEN  -- 100MB
            bucket := '0-100MB';
        ELSIF NEW.file_size_bytes < 524288000 THEN  -- 500MB
            bucket := '100-500MB';
        ELSE
            bucket := '500MB+';
        END IF;

        -- Calculate duration
        duration_secs := EXTRACT(EPOCH FROM (NEW.completed_at - NEW.started_at))::INTEGER;

        -- Update running average
        UPDATE job_duration_stats
        SET
            avg_duration_seconds = (avg_duration_seconds * sample_count + duration_secs) / (sample_count + 1),
            sample_count = sample_count + 1,
            updated_at = NOW()
        WHERE file_size_bucket = bucket;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to update stats on job completion
CREATE TRIGGER trigger_update_duration_stats
    AFTER UPDATE ON transcription_jobs
    FOR EACH ROW
    EXECUTE FUNCTION update_duration_stats();

-- Function to clean up old jobs (called by Cloud Scheduler)
CREATE OR REPLACE FUNCTION cleanup_old_jobs(retention_days INTEGER DEFAULT 7)
RETURNS TABLE(deleted_count INTEGER, gcs_paths TEXT[]) AS $$
DECLARE
    cutoff TIMESTAMP WITH TIME ZONE;
    paths TEXT[];
    count INTEGER;
BEGIN
    cutoff := NOW() - (retention_days || ' days')::INTERVAL;

    -- Get GCS paths before deletion
    SELECT ARRAY_AGG(gcs_path) INTO paths
    FROM transcription_jobs
    WHERE created_at < cutoff AND gcs_path IS NOT NULL;

    -- Delete old jobs
    DELETE FROM transcription_jobs
    WHERE created_at < cutoff;

    GET DIAGNOSTICS count = ROW_COUNT;

    RETURN QUERY SELECT count, COALESCE(paths, ARRAY[]::TEXT[]);
END;
$$ LANGUAGE plpgsql;

-- Comment on tables
COMMENT ON TABLE transcription_jobs IS 'Background transcription job queue with status tracking';
COMMENT ON TABLE job_duration_stats IS 'Historical job duration statistics for time estimates';
