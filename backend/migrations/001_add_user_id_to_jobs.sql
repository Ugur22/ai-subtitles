-- Migration: Add user_id column to jobs table for ownership tracking
-- Run this in Supabase SQL Editor (https://supabase.com/dashboard/project/ngfcjdxfhppnzpocgktw/sql)
--
-- This migration adds user ownership to jobs, allowing:
-- - Users to see only their own jobs in the job list
-- - Job access via ownership OR token (for shared links)
-- - Proper multi-tenant job isolation

-- Step 1: Add user_id column (nullable to support existing jobs)
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth.users(id);

-- Step 2: Create index for efficient user-based queries
CREATE INDEX IF NOT EXISTS idx_jobs_user_id ON jobs(user_id);

-- Step 3: Verify the migration
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'jobs' AND column_name = 'user_id'
    ) THEN
        RAISE NOTICE 'Migration successful: user_id column added to jobs table';
    ELSE
        RAISE EXCEPTION 'Migration failed: user_id column not found';
    END IF;
END $$;

-- Step 4: Show column info for verification
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'jobs' AND column_name = 'user_id';
