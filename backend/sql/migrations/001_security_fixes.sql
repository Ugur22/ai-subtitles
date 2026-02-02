-- ========================================
-- Security Fixes Migration
-- ========================================
-- Run this in Supabase SQL Editor to fix security warnings
-- Date: 2026-02-02
--
-- Fixes:
-- 1. Function search_path vulnerabilities (8 warnings)
-- 2. Overly permissive RLS policies (4 warnings)
-- ========================================

-- ========================================
-- Phase 1: Fix Function Search Paths
-- ========================================

-- Fix get_vault_secret - SECURITY DEFINER with empty search_path for vault access
ALTER FUNCTION get_vault_secret(TEXT) SET search_path = '';

-- Fix update_updated_at_column trigger function
ALTER FUNCTION update_updated_at_column() SET search_path = public;

-- Fix cleanup_expired_codes
ALTER FUNCTION cleanup_expired_codes() SET search_path = public;

-- Fix is_invite_code_valid
ALTER FUNCTION is_invite_code_valid(UUID) SET search_path = public;

-- Fix use_invite_code
ALTER FUNCTION use_invite_code(UUID, UUID) SET search_path = public;

-- Fix search_images_by_embedding
ALTER FUNCTION search_images_by_embedding(vector(512), TEXT, INT, TEXT) SET search_path = public;

-- Fix functions that may only exist in Supabase (created via dashboard/triggers)
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'update_duration_stats') THEN
    EXECUTE 'ALTER FUNCTION update_duration_stats SET search_path = public';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'cleanup_old_jobs') THEN
    EXECUTE 'ALTER FUNCTION cleanup_old_jobs SET search_path = public';
  END IF;
END $$;

-- ========================================
-- Phase 2: Remove Overly Permissive RLS Policies
-- ========================================
-- These policies serve no purpose because:
-- 1. Service_role bypasses RLS entirely
-- 2. These tables are backend-only (never accessed via anon key)

DROP POLICY IF EXISTS email_verifications_service ON email_verifications;
DROP POLICY IF EXISTS password_resets_service ON password_resets;
DROP POLICY IF EXISTS rate_limits_service ON rate_limits;
DROP POLICY IF EXISTS usage_logs_insert ON usage_logs;

-- ========================================
-- Verification
-- ========================================

-- Check function search_paths were set correctly
SELECT proname, proconfig
FROM pg_proc
WHERE proname IN (
  'get_vault_secret',
  'cleanup_expired_codes',
  'is_invite_code_valid',
  'use_invite_code',
  'update_updated_at_column',
  'search_images_by_embedding'
)
ORDER BY proname;

-- Check RLS policies were removed (should return empty for these policy names)
SELECT schemaname, tablename, policyname
FROM pg_policies
WHERE policyname IN (
  'email_verifications_service',
  'password_resets_service',
  'rate_limits_service',
  'usage_logs_insert'
);

-- ========================================
-- Migration Complete
-- ========================================
-- After running this migration:
-- 1. Enable "Leaked Password Protection" in Supabase Dashboard
--    Location: Authentication > Providers > Email
-- 2. Re-run the Security Advisor to verify warnings are resolved
--    Expected: 1 remaining warning (vector extension in public schema)
-- ========================================
