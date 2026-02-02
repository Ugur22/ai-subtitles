-- ========================================
-- Security Fixes Rollback
-- ========================================
-- Run this ONLY if you need to revert the security fixes
-- This will restore the previous (less secure) state
-- ========================================

-- ========================================
-- Rollback Function Search Paths
-- ========================================

ALTER FUNCTION get_vault_secret(TEXT) RESET search_path;
ALTER FUNCTION update_updated_at_column() RESET search_path;
ALTER FUNCTION cleanup_expired_codes() RESET search_path;
ALTER FUNCTION is_invite_code_valid(UUID) RESET search_path;
ALTER FUNCTION use_invite_code(UUID, UUID) RESET search_path;
ALTER FUNCTION search_images_by_embedding(vector(512), TEXT, INT, TEXT) RESET search_path;

-- ========================================
-- Recreate RLS Policies
-- ========================================
-- WARNING: These policies are overly permissive and create security warnings
-- Only restore if absolutely necessary for functionality

-- Usage logs: backend service can insert logs
CREATE POLICY usage_logs_insert ON usage_logs
  FOR INSERT
  WITH CHECK (TRUE);

-- Rate limits: backend service can manage limits
CREATE POLICY rate_limits_service ON rate_limits
  FOR ALL
  USING (TRUE)
  WITH CHECK (TRUE);

-- Email verifications: backend service can insert/delete codes
CREATE POLICY email_verifications_service ON email_verifications
  FOR ALL
  USING (TRUE)
  WITH CHECK (TRUE);

-- Password resets: backend service manages all operations
CREATE POLICY password_resets_service ON password_resets
  FOR ALL
  USING (TRUE)
  WITH CHECK (TRUE);

-- ========================================
-- Rollback Complete
-- ========================================
