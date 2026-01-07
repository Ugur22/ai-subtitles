-- ============================================================================
-- AI-Subs Authentication System Migration
-- ============================================================================
-- This migration creates tables for the new authentication system.
-- Run this SQL in your Supabase SQL editor.
--
-- IMPORTANT: Backup your database before running this migration!
-- ============================================================================

-- ============================================================================
-- Step 1: Create encryption key in Supabase Vault
-- ============================================================================
-- Run this FIRST to create the encryption key for API keys.
-- The key will be generated randomly and stored securely in Vault.

SELECT vault.create_secret(
  encode(gen_random_bytes(32), 'hex'),
  'api_key_encryption'
);

-- ============================================================================
-- Step 2: Create new tables
-- ============================================================================

-- User profiles (extends Supabase auth.users)
CREATE TABLE IF NOT EXISTS user_profiles (
  id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  email TEXT NOT NULL,
  display_name TEXT,
  default_llm_provider TEXT DEFAULT 'groq',
  email_verified BOOLEAN DEFAULT FALSE,
  is_admin BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create index on email for faster lookups
CREATE INDEX IF NOT EXISTS idx_user_profiles_email ON user_profiles(email);

-- User API keys (encrypted with AES-256-GCM)
CREATE TABLE IF NOT EXISTS user_api_keys (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
  provider TEXT NOT NULL, -- 'groq', 'xai', 'openai', 'anthropic'
  encrypted_key TEXT NOT NULL,
  key_suffix TEXT NOT NULL, -- Last 4 chars for display
  is_valid BOOLEAN DEFAULT NULL, -- NULL=pending, TRUE=valid, FALSE=invalid
  validation_error TEXT,
  validated_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(user_id, provider)
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_user_api_keys_user_id ON user_api_keys(user_id);
CREATE INDEX IF NOT EXISTS idx_user_api_keys_provider ON user_api_keys(provider);

-- Invite codes (UUID format, single-use)
CREATE TABLE IF NOT EXISTS invite_codes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  code UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
  created_by UUID REFERENCES user_profiles(id),
  used_by UUID REFERENCES user_profiles(id),
  used_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_invite_codes_code ON invite_codes(code);
CREATE INDEX IF NOT EXISTS idx_invite_codes_used_by ON invite_codes(used_by);

-- Usage tracking
CREATE TABLE IF NOT EXISTS usage_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
  action TEXT NOT NULL, -- 'login', 'upload', 'chat_message'
  metadata JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create indexes for common queries
CREATE INDEX IF NOT EXISTS idx_usage_logs_user_id ON usage_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_usage_logs_action ON usage_logs(action);
CREATE INDEX IF NOT EXISTS idx_usage_logs_created_at ON usage_logs(created_at DESC);

-- Rate limiting (daily upload quotas)
CREATE TABLE IF NOT EXISTS rate_limits (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
  limit_type TEXT NOT NULL, -- 'upload_daily'
  count INTEGER DEFAULT 0,
  window_start TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(user_id, limit_type)
);

-- Create index
CREATE INDEX IF NOT EXISTS idx_rate_limits_user_id ON rate_limits(user_id);

-- Email verification codes (6-digit, expires in 15 min)
CREATE TABLE IF NOT EXISTS email_verifications (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  code TEXT NOT NULL, -- 6-digit code
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create index
CREATE INDEX IF NOT EXISTS idx_email_verifications_user_id ON email_verifications(user_id);

-- Password reset codes (6-digit, expires in 15 min)
CREATE TABLE IF NOT EXISTS password_resets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT NOT NULL,
  code TEXT NOT NULL, -- 6-digit code
  expires_at TIMESTAMPTZ NOT NULL,
  used BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create index
CREATE INDEX IF NOT EXISTS idx_password_resets_email ON password_resets(email);

-- ============================================================================
-- Step 3: Modify existing jobs table
-- ============================================================================
-- Add user_id column to jobs table if it doesn't exist.
-- This links jobs to users for access control.

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'jobs' AND column_name = 'user_id'
  ) THEN
    ALTER TABLE jobs ADD COLUMN user_id UUID REFERENCES user_profiles(id);
    CREATE INDEX idx_jobs_user_id ON jobs(user_id);
  END IF;
END$$;

-- ============================================================================
-- Step 4: Enable Row Level Security (RLS)
-- ============================================================================

-- Enable RLS on all user tables
ALTER TABLE user_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_api_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE usage_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE rate_limits ENABLE ROW LEVEL SECURITY;

-- user_profiles: users see only their own profile
DROP POLICY IF EXISTS user_profiles_own ON user_profiles;
CREATE POLICY user_profiles_own ON user_profiles
  FOR ALL USING (auth.uid() = id);

-- user_api_keys: users see only their own keys
DROP POLICY IF EXISTS user_api_keys_own ON user_api_keys;
CREATE POLICY user_api_keys_own ON user_api_keys
  FOR ALL USING (auth.uid() = user_id);

-- usage_logs: users see only their own logs
DROP POLICY IF EXISTS usage_logs_own ON usage_logs;
CREATE POLICY usage_logs_own ON usage_logs
  FOR ALL USING (auth.uid() = user_id);

-- rate_limits: users see only their own limits
DROP POLICY IF EXISTS rate_limits_own ON rate_limits;
CREATE POLICY rate_limits_own ON rate_limits
  FOR ALL USING (auth.uid() = user_id);

-- jobs: users see only their own jobs (if user_id is set)
DROP POLICY IF EXISTS jobs_own ON jobs;
CREATE POLICY jobs_own ON jobs
  FOR ALL USING (auth.uid() = user_id OR user_id IS NULL);

-- ============================================================================
-- Step 5: Create initial admin user and invite codes
-- ============================================================================
-- IMPORTANT: Replace the email and run these commands manually after the migration.

-- Example: Create admin user (do this after user registers normally)
-- UPDATE user_profiles SET is_admin = TRUE WHERE email = 'your-email@example.com';

-- Example: Create initial invite codes
-- INSERT INTO invite_codes (code) VALUES (gen_random_uuid());
-- INSERT INTO invite_codes (code) VALUES (gen_random_uuid());
-- INSERT INTO invite_codes (code) VALUES (gen_random_uuid());

-- ============================================================================
-- Step 6: Create helpful functions
-- ============================================================================

-- Function to cleanup expired verification codes (run periodically)
CREATE OR REPLACE FUNCTION cleanup_expired_codes()
RETURNS INTEGER AS $$
DECLARE
  deleted_count INTEGER;
BEGIN
  -- Delete expired email verifications
  DELETE FROM email_verifications WHERE expires_at < NOW();
  GET DIAGNOSTICS deleted_count = ROW_COUNT;

  -- Delete expired password resets
  DELETE FROM password_resets WHERE expires_at < NOW();

  RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- Function to get user's API key for a provider (used by backend)
CREATE OR REPLACE FUNCTION get_user_api_key(p_user_id UUID, p_provider TEXT)
RETURNS TABLE (encrypted_key TEXT, is_valid BOOLEAN) AS $$
BEGIN
  RETURN QUERY
  SELECT uak.encrypted_key, uak.is_valid
  FROM user_api_keys uak
  WHERE uak.user_id = p_user_id AND uak.provider = p_provider;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- ============================================================================
-- Migration Complete!
-- ============================================================================
--
-- Next steps:
-- 1. Create initial invite codes
-- 2. Promote first user to admin
-- 3. Test registration flow
-- 4. Configure frontend with new auth endpoints
--
-- ============================================================================
