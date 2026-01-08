-- ========================================
-- AI-Subs Authentication & API Key Management Schema
-- ========================================
--
-- This schema implements a complete user authentication system with:
-- - User profiles extending Supabase auth.users
-- - Encrypted API key storage (AES-256-GCM)
-- - Invite code system (UUID, single-use)
-- - Usage tracking and rate limiting
-- - Email verification and password reset
-- - Row Level Security (RLS) policies
--
-- Run this in Supabase SQL Editor
-- ========================================

-- ========================================
-- STEP 1: Create Encryption Key in Vault
-- ========================================
-- This must be run FIRST before any encrypted data is stored
-- The key is used for AES-256-GCM encryption of user API keys

SELECT vault.create_secret(
  'api_key_encryption',
  encode(gen_random_bytes(32), 'hex'),
  'AES-256 encryption key for user API keys'
);

-- Create a wrapper function to read vault secrets via RPC
-- (Supabase RPC can only call functions in the public schema)
CREATE OR REPLACE FUNCTION get_vault_secret(secret_name_input TEXT)
RETURNS TABLE(secret TEXT) AS $$
BEGIN
  RETURN QUERY
  SELECT decrypted_secret::TEXT
  FROM vault.decrypted_secrets
  WHERE name = secret_name_input
  LIMIT 1;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

GRANT EXECUTE ON FUNCTION get_vault_secret(TEXT) TO service_role;

-- ========================================
-- STEP 2: Create Tables
-- ========================================

-- User profiles (extends Supabase auth.users)
-- This table stores additional user information beyond what auth.users provides
CREATE TABLE IF NOT EXISTS user_profiles (
  id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  email TEXT NOT NULL UNIQUE,
  display_name TEXT,
  default_llm_provider TEXT DEFAULT 'groq' CHECK (default_llm_provider IN ('groq', 'xai', 'openai', 'anthropic')),
  email_verified BOOLEAN DEFAULT FALSE,
  is_admin BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE user_profiles IS 'Extended user profile information linked to Supabase auth.users';
COMMENT ON COLUMN user_profiles.email_verified IS 'User must verify email before accessing the application';
COMMENT ON COLUMN user_profiles.default_llm_provider IS 'Default LLM provider for chat (groq, xai, openai, anthropic)';
COMMENT ON COLUMN user_profiles.is_admin IS 'Admin users can access admin dashboard and manage invites';

-- User API keys (encrypted)
-- Stores encrypted API keys for LLM providers
CREATE TABLE IF NOT EXISTS user_api_keys (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
  provider TEXT NOT NULL CHECK (provider IN ('groq', 'xai', 'openai', 'anthropic')),
  encrypted_key TEXT NOT NULL, -- AES-256-GCM encrypted, hex-encoded (nonce + ciphertext)
  key_suffix TEXT NOT NULL CHECK (length(key_suffix) = 4), -- Last 4 chars for display (e.g., "abc123")
  is_valid BOOLEAN DEFAULT NULL, -- NULL=pending validation, TRUE=valid, FALSE=invalid
  validation_error TEXT,
  validated_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(user_id, provider) -- One key per provider per user
);

COMMENT ON TABLE user_api_keys IS 'Encrypted user API keys for LLM providers (Groq, xAI, OpenAI, Anthropic)';
COMMENT ON COLUMN user_api_keys.encrypted_key IS 'AES-256-GCM encrypted key (hex format: nonce[12 bytes] + ciphertext)';
COMMENT ON COLUMN user_api_keys.key_suffix IS 'Last 4 characters of key for UI display';
COMMENT ON COLUMN user_api_keys.is_valid IS 'NULL=pending validation, TRUE=valid, FALSE=invalid';

-- Invite codes
-- UUID-based invite codes for user registration
CREATE TABLE IF NOT EXISTS invite_codes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  code UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
  created_by UUID REFERENCES user_profiles(id) ON DELETE SET NULL,
  used_by UUID REFERENCES user_profiles(id) ON DELETE SET NULL,
  used_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK ((used_by IS NULL AND used_at IS NULL) OR (used_by IS NOT NULL AND used_at IS NOT NULL))
);

COMMENT ON TABLE invite_codes IS 'Single-use invite codes for user registration';
COMMENT ON COLUMN invite_codes.code IS 'UUID invite code shown to user';
COMMENT ON COLUMN invite_codes.created_by IS 'Admin user who created this invite';
COMMENT ON COLUMN invite_codes.used_by IS 'User who used this invite (NULL if unused)';

-- Usage tracking
-- Logs user actions for analytics and monitoring
CREATE TABLE IF NOT EXISTS usage_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
  action TEXT NOT NULL CHECK (action IN ('login', 'upload', 'chat_message')),
  metadata JSONB, -- Additional action-specific data (e.g., file size, provider)
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE usage_logs IS 'Tracks user actions (logins, uploads, chat messages) for analytics';
COMMENT ON COLUMN usage_logs.action IS 'Action type: login, upload, chat_message';
COMMENT ON COLUMN usage_logs.metadata IS 'JSON metadata (e.g., {file_size: 1024, provider: "groq"})';

-- Rate limiting
-- Tracks rate limit counters per user per limit type
CREATE TABLE IF NOT EXISTS rate_limits (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
  limit_type TEXT NOT NULL CHECK (limit_type IN ('upload_daily')),
  count INTEGER NOT NULL DEFAULT 0 CHECK (count >= 0),
  window_start TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(user_id, limit_type)
);

COMMENT ON TABLE rate_limits IS 'Rate limit counters for user actions (e.g., 50 uploads/day)';
COMMENT ON COLUMN rate_limits.limit_type IS 'Type of rate limit: upload_daily';
COMMENT ON COLUMN rate_limits.count IS 'Current count in the window';
COMMENT ON COLUMN rate_limits.window_start IS 'Start of the current rate limit window';

-- Email verification codes
-- 6-digit codes sent via email for account verification
CREATE TABLE IF NOT EXISTS email_verifications (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  code TEXT NOT NULL CHECK (code ~ '^[0-9]{6}$'), -- 6-digit numeric code
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (expires_at > created_at)
);

COMMENT ON TABLE email_verifications IS '6-digit email verification codes (expires after 15 minutes)';
COMMENT ON COLUMN email_verifications.code IS '6-digit numeric code';
COMMENT ON COLUMN email_verifications.expires_at IS 'Code expires 15 minutes after creation';

-- Password reset codes
-- 6-digit codes sent via email for password reset
CREATE TABLE IF NOT EXISTS password_resets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT NOT NULL,
  code TEXT NOT NULL CHECK (code ~ '^[0-9]{6}$'), -- 6-digit numeric code
  expires_at TIMESTAMPTZ NOT NULL,
  used BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (expires_at > created_at)
);

COMMENT ON TABLE password_resets IS '6-digit password reset codes (expires after 15 minutes)';
COMMENT ON COLUMN password_resets.email IS 'Email address for reset request';
COMMENT ON COLUMN password_resets.code IS '6-digit numeric code';
COMMENT ON COLUMN password_resets.expires_at IS 'Code expires 15 minutes after creation';
COMMENT ON COLUMN password_resets.used IS 'True if code has been used for password reset';

-- ========================================
-- STEP 3: Modify Existing Tables
-- ========================================

-- Add user_id to jobs table (if jobs table exists)
-- This links jobs to the user who created them
DO $$
BEGIN
  IF EXISTS (
    SELECT FROM information_schema.tables
    WHERE table_schema = 'public'
    AND table_name = 'jobs'
  ) THEN
    -- Add user_id column if it doesn't exist
    IF NOT EXISTS (
      SELECT FROM information_schema.columns
      WHERE table_schema = 'public'
      AND table_name = 'jobs'
      AND column_name = 'user_id'
    ) THEN
      ALTER TABLE jobs ADD COLUMN user_id UUID REFERENCES user_profiles(id) ON DELETE SET NULL;
      COMMENT ON COLUMN jobs.user_id IS 'User who created this job (NULL for existing jobs before auth system)';
    END IF;
  END IF;
END $$;

-- ========================================
-- STEP 4: Create Indexes for Performance
-- ========================================

-- User profiles indexes
CREATE INDEX IF NOT EXISTS idx_user_profiles_email ON user_profiles(email);
CREATE INDEX IF NOT EXISTS idx_user_profiles_is_admin ON user_profiles(is_admin) WHERE is_admin = TRUE;
CREATE INDEX IF NOT EXISTS idx_user_profiles_created_at ON user_profiles(created_at);

-- User API keys indexes
CREATE INDEX IF NOT EXISTS idx_user_api_keys_user_id ON user_api_keys(user_id);
CREATE INDEX IF NOT EXISTS idx_user_api_keys_provider ON user_api_keys(provider);
CREATE INDEX IF NOT EXISTS idx_user_api_keys_is_valid ON user_api_keys(is_valid) WHERE is_valid IS NOT NULL;

-- Invite codes indexes
CREATE INDEX IF NOT EXISTS idx_invite_codes_code ON invite_codes(code);
CREATE INDEX IF NOT EXISTS idx_invite_codes_used_by ON invite_codes(used_by) WHERE used_by IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_invite_codes_created_by ON invite_codes(created_by);

-- Usage logs indexes
CREATE INDEX IF NOT EXISTS idx_usage_logs_user_id ON usage_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_usage_logs_action ON usage_logs(action);
CREATE INDEX IF NOT EXISTS idx_usage_logs_created_at ON usage_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_usage_logs_user_action ON usage_logs(user_id, action);

-- Rate limits indexes
CREATE INDEX IF NOT EXISTS idx_rate_limits_user_id ON rate_limits(user_id);
CREATE INDEX IF NOT EXISTS idx_rate_limits_limit_type ON rate_limits(limit_type);

-- Email verification indexes
CREATE INDEX IF NOT EXISTS idx_email_verifications_user_id ON email_verifications(user_id);
CREATE INDEX IF NOT EXISTS idx_email_verifications_code ON email_verifications(code);
CREATE INDEX IF NOT EXISTS idx_email_verifications_expires_at ON email_verifications(expires_at);

-- Password reset indexes
CREATE INDEX IF NOT EXISTS idx_password_resets_email ON password_resets(email);
CREATE INDEX IF NOT EXISTS idx_password_resets_code ON password_resets(code);
CREATE INDEX IF NOT EXISTS idx_password_resets_expires_at ON password_resets(expires_at);

-- Jobs indexes (if table exists)
DO $$
BEGIN
  IF EXISTS (
    SELECT FROM information_schema.tables
    WHERE table_schema = 'public'
    AND table_name = 'jobs'
  ) THEN
    CREATE INDEX IF NOT EXISTS idx_jobs_user_id ON jobs(user_id);
  END IF;
END $$;

-- ========================================
-- STEP 5: Row Level Security (RLS) Policies
-- ========================================

-- Enable RLS on all tables
ALTER TABLE user_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_api_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE invite_codes ENABLE ROW LEVEL SECURITY;
ALTER TABLE usage_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE rate_limits ENABLE ROW LEVEL SECURITY;
ALTER TABLE email_verifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE password_resets ENABLE ROW LEVEL SECURITY;

-- User profiles: users can only see and modify their own profile
CREATE POLICY user_profiles_own ON user_profiles
  FOR ALL
  USING (auth.uid() = id)
  WITH CHECK (auth.uid() = id);

-- Admin policy: admins can see all profiles
CREATE POLICY user_profiles_admin_read ON user_profiles
  FOR SELECT
  USING (
    EXISTS (
      SELECT 1 FROM user_profiles
      WHERE id = auth.uid() AND is_admin = TRUE
    )
  );

-- User API keys: users can only see and modify their own keys
CREATE POLICY user_api_keys_own ON user_api_keys
  FOR ALL
  USING (auth.uid() = user_id)
  WITH CHECK (auth.uid() = user_id);

-- Invite codes: anyone can read unused codes (for registration)
CREATE POLICY invite_codes_read_unused ON invite_codes
  FOR SELECT
  USING (used_by IS NULL);

-- Invite codes: admins can do everything
CREATE POLICY invite_codes_admin ON invite_codes
  FOR ALL
  USING (
    EXISTS (
      SELECT 1 FROM user_profiles
      WHERE id = auth.uid() AND is_admin = TRUE
    )
  )
  WITH CHECK (
    EXISTS (
      SELECT 1 FROM user_profiles
      WHERE id = auth.uid() AND is_admin = TRUE
    )
  );

-- Usage logs: users can read their own logs
CREATE POLICY usage_logs_own_read ON usage_logs
  FOR SELECT
  USING (auth.uid() = user_id);

-- Usage logs: backend service can insert logs
CREATE POLICY usage_logs_insert ON usage_logs
  FOR INSERT
  WITH CHECK (TRUE); -- Allow inserts from service role

-- Usage logs: admins can read all logs
CREATE POLICY usage_logs_admin_read ON usage_logs
  FOR SELECT
  USING (
    EXISTS (
      SELECT 1 FROM user_profiles
      WHERE id = auth.uid() AND is_admin = TRUE
    )
  );

-- Rate limits: users can read their own limits
CREATE POLICY rate_limits_own_read ON rate_limits
  FOR SELECT
  USING (auth.uid() = user_id);

-- Rate limits: backend service can manage limits
CREATE POLICY rate_limits_service ON rate_limits
  FOR ALL
  USING (TRUE)
  WITH CHECK (TRUE); -- Allow service role to manage rate limits

-- Email verifications: users can read their own codes
CREATE POLICY email_verifications_own ON email_verifications
  FOR SELECT
  USING (auth.uid() = user_id);

-- Email verifications: backend service can insert/delete codes
CREATE POLICY email_verifications_service ON email_verifications
  FOR ALL
  USING (TRUE)
  WITH CHECK (TRUE); -- Allow service role to manage verification codes

-- Password resets: backend service manages all operations
CREATE POLICY password_resets_service ON password_resets
  FOR ALL
  USING (TRUE)
  WITH CHECK (TRUE); -- Allow service role to manage reset codes

-- Jobs table RLS (if it exists)
DO $$
BEGIN
  IF EXISTS (
    SELECT FROM information_schema.tables
    WHERE table_schema = 'public'
    AND table_name = 'jobs'
  ) THEN
    -- Enable RLS on jobs
    ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;

    -- Drop existing policy if it exists
    DROP POLICY IF EXISTS jobs_own ON jobs;

    -- Users can only see their own jobs
    CREATE POLICY jobs_own ON jobs
      FOR ALL
      USING (auth.uid() = user_id)
      WITH CHECK (auth.uid() = user_id);

    -- Allow jobs without user_id (existing jobs before auth system)
    CREATE POLICY jobs_legacy ON jobs
      FOR SELECT
      USING (user_id IS NULL);
  END IF;
END $$;

-- ========================================
-- STEP 6: Updated_at Trigger Function
-- ========================================

-- Function to automatically update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply trigger to tables with updated_at column
CREATE TRIGGER update_user_profiles_updated_at
  BEFORE UPDATE ON user_profiles
  FOR EACH ROW
  EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_user_api_keys_updated_at
  BEFORE UPDATE ON user_api_keys
  FOR EACH ROW
  EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_rate_limits_updated_at
  BEFORE UPDATE ON rate_limits
  FOR EACH ROW
  EXECUTE FUNCTION update_updated_at_column();

-- ========================================
-- STEP 7: Helper Functions
-- ========================================

-- Function to clean up expired verification codes
CREATE OR REPLACE FUNCTION cleanup_expired_codes()
RETURNS void AS $$
BEGIN
  DELETE FROM email_verifications WHERE expires_at < NOW();
  DELETE FROM password_resets WHERE expires_at < NOW() OR used = TRUE;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

COMMENT ON FUNCTION cleanup_expired_codes IS 'Removes expired email verification and password reset codes';

-- Function to check if invite code is valid
CREATE OR REPLACE FUNCTION is_invite_code_valid(code_input UUID)
RETURNS BOOLEAN AS $$
BEGIN
  RETURN EXISTS (
    SELECT 1 FROM invite_codes
    WHERE code = code_input AND used_by IS NULL
  );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

COMMENT ON FUNCTION is_invite_code_valid IS 'Checks if an invite code is valid (exists and unused)';

-- Function to mark invite code as used
CREATE OR REPLACE FUNCTION use_invite_code(code_input UUID, user_id_input UUID)
RETURNS BOOLEAN AS $$
BEGIN
  UPDATE invite_codes
  SET used_by = user_id_input, used_at = NOW()
  WHERE code = code_input AND used_by IS NULL;

  RETURN FOUND;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

COMMENT ON FUNCTION use_invite_code IS 'Marks an invite code as used by a specific user';

-- ========================================
-- STEP 8: Initial Data
-- ========================================

-- Create initial admin invite code (for first admin user)
-- Save this code securely - it's needed to create the first admin account
-- After the first admin is created, they can generate more invite codes
DO $$
DECLARE
  admin_code UUID;
BEGIN
  -- Only create if no invite codes exist
  IF NOT EXISTS (SELECT 1 FROM invite_codes LIMIT 1) THEN
    INSERT INTO invite_codes (code, created_by)
    VALUES (gen_random_uuid(), NULL)
    RETURNING code INTO admin_code;

    RAISE NOTICE 'Initial admin invite code created: %', admin_code;
    RAISE NOTICE 'SAVE THIS CODE - You need it to create the first admin account!';
  END IF;
END $$;

-- ========================================
-- STEP 9: Grants for Service Role
-- ========================================

-- Grant necessary permissions to the service role
-- (Supabase uses service_role for backend API operations)

GRANT USAGE ON SCHEMA public TO service_role;
GRANT ALL ON ALL TABLES IN SCHEMA public TO service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO service_role;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO service_role;

-- ========================================
-- Schema Creation Complete
-- ========================================

-- Verify the schema was created successfully
DO $$
DECLARE
  table_count INTEGER;
BEGIN
  SELECT COUNT(*) INTO table_count
  FROM information_schema.tables
  WHERE table_schema = 'public'
  AND table_name IN (
    'user_profiles',
    'user_api_keys',
    'invite_codes',
    'usage_logs',
    'rate_limits',
    'email_verifications',
    'password_resets'
  );

  IF table_count = 7 THEN
    RAISE NOTICE '✓ All 7 auth tables created successfully';
  ELSE
    RAISE WARNING '✗ Only % out of 7 tables were created', table_count;
  END IF;
END $$;

-- Display summary
SELECT
  'Auth Schema Created' AS status,
  (SELECT COUNT(*) FROM invite_codes) AS invite_codes_count,
  NOW() AS created_at;
