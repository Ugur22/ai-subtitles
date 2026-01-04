-- AI-Subs Background Job Processing Schema for Supabase
-- Version: 3.0
-- Run this in Supabase SQL Editor to set up the required tables
-- This schema matches the backend job_queue_service.py exactly

-- Drop existing tables if they exist
DROP TABLE IF EXISTS jobs CASCADE;
DROP TABLE IF EXISTS job_duration_stats CASCADE;

-- Main jobs table
CREATE TABLE jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    access_token UUID NOT NULL DEFAULT gen_random_uuid(),
    status TEXT NOT NULL DEFAULT 'pending',
    filename TEXT NOT NULL,
    gcs_path TEXT,
    file_size_bytes BIGINT,
    video_hash TEXT,
    progress INTEGER DEFAULT 0,
    stage TEXT,
    message TEXT,
    estimated_duration_seconds INTEGER,
    retry_count INTEGER DEFAULT 0,
    params JSONB,
    error_code TEXT,
    error_message TEXT,
    result_json JSONB,
    result_srt TEXT,
    result_vtt TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    failed_at TIMESTAMP WITH TIME ZONE,
    cancelled_at TIMESTAMP WITH TIME ZONE,
    last_seen TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Enable real-time for jobs
ALTER PUBLICATION supabase_realtime ADD TABLE jobs;

-- Indexes for common queries
CREATE INDEX idx_jobs_status ON jobs(status);
CREATE INDEX idx_jobs_created ON jobs(created_at DESC);
CREATE INDEX idx_jobs_access_token ON jobs(access_token);
CREATE INDEX idx_jobs_video_hash ON jobs(video_hash);
CREATE INDEX idx_jobs_last_seen ON jobs(last_seen);

-- Row Level Security (RLS)
-- Using service role key bypasses RLS, but we enable it for safety
ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Full access" ON jobs FOR ALL USING (true) WITH CHECK (true);

-- Comment on table
COMMENT ON TABLE jobs IS 'Background transcription job queue with status tracking';
