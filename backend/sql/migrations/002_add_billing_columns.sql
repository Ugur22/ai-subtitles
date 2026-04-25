-- Migration 002: Add billing / subscription / usage-metering columns.
--
-- Run this once in Supabase SQL editor (or psql) to prepare the DB for
-- Stripe-backed monetization.
--
-- Changes:
--   1. user_profiles gets subscription_plan + Stripe IDs + status
--   2. jobs gets video_duration_seconds + gpu_seconds (cost metering)
--   3. New user_usage_monthly table (rollup for quota checks)
--
-- Design notes:
--   - subscription_plan defaults to 'free'. Admins (is_admin=true) bypass
--     all quota checks regardless of plan — enforced in application code.
--   - user_usage_monthly uses first-of-month as the period key. One row per
--     (user, month). Cheap to query: WHERE user_id = X AND period_start = Y.
--   - gpu_seconds is wall-clock time the GPU was busy for this job; it is
--     used for internal cost accounting, not for quota enforcement. Quota
--     is based on transcription_seconds (i.e. video length the user pushed
--     through the system).

BEGIN;

-- ─── user_profiles: subscription state ──────────────────────────────────────
ALTER TABLE user_profiles
  ADD COLUMN IF NOT EXISTS subscription_plan TEXT NOT NULL DEFAULT 'free'
    CHECK (subscription_plan IN ('free', 'pro', 'studio'));

ALTER TABLE user_profiles
  ADD COLUMN IF NOT EXISTS stripe_customer_id TEXT;

ALTER TABLE user_profiles
  ADD COLUMN IF NOT EXISTS stripe_subscription_id TEXT;

ALTER TABLE user_profiles
  ADD COLUMN IF NOT EXISTS subscription_status TEXT
    CHECK (subscription_status IN ('active', 'past_due', 'canceled', 'incomplete', 'trialing', NULL));

ALTER TABLE user_profiles
  ADD COLUMN IF NOT EXISTS current_period_end TIMESTAMPTZ;

-- Uniqueness (separately so existing NULLs are allowed)
CREATE UNIQUE INDEX IF NOT EXISTS idx_user_profiles_stripe_customer_id
  ON user_profiles (stripe_customer_id)
  WHERE stripe_customer_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_user_profiles_stripe_subscription_id
  ON user_profiles (stripe_subscription_id)
  WHERE stripe_subscription_id IS NOT NULL;

-- ─── jobs: cost metering ────────────────────────────────────────────────────
ALTER TABLE jobs
  ADD COLUMN IF NOT EXISTS video_duration_seconds INTEGER;

ALTER TABLE jobs
  ADD COLUMN IF NOT EXISTS gpu_seconds DECIMAL(10,2);

-- Index to make "how many seconds did user X transcribe this month" fast.
CREATE INDEX IF NOT EXISTS idx_jobs_user_created
  ON jobs (user_id, created_at DESC)
  WHERE user_id IS NOT NULL;

-- ─── user_usage_monthly: quota rollup ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS user_usage_monthly (
  user_id UUID NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
  period_start DATE NOT NULL,
  transcription_seconds INTEGER NOT NULL DEFAULT 0,
  llm_tokens INTEGER NOT NULL DEFAULT 0,
  chat_messages INTEGER NOT NULL DEFAULT 0,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (user_id, period_start)
);

-- RLS: users can only read their own row
ALTER TABLE user_usage_monthly ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS user_usage_monthly_select_own ON user_usage_monthly;
CREATE POLICY user_usage_monthly_select_own
  ON user_usage_monthly
  FOR SELECT
  USING (auth.uid() = user_id);

-- The service role (backend) bypasses RLS via service key, so no INSERT/UPDATE
-- policies are needed here. Writes happen from the worker after each job
-- completes and from the chat router after each streamed response.

COMMIT;
