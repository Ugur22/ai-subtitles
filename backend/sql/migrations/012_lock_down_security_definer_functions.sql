-- ========================================
-- Lock Down SECURITY DEFINER Functions & face_tags RLS
-- ========================================
-- Run this in Supabase SQL Editor to fix security warnings
-- Date: 2026-08-16
--
-- Fixes:
-- 1. get_vault_secret, cleanup_expired_codes, is_invite_code_valid,
--    use_invite_code are SECURITY DEFINER functions still executable
--    by anon/authenticated via Postgres's default PUBLIC EXECUTE grant.
--    get_vault_secret in particular can return the vault secret used to
--    encrypt user API keys to any unauthenticated caller.
--    All backend call sites use SupabaseService.get_client(), which is
--    hardcoded to SUPABASE_SERVICE_KEY, so service_role-only access
--    breaks nothing.
-- 2. face_tags has USING (true) / WITH CHECK (true) policies for
--    INSERT/UPDATE/DELETE. service_role (the only writer) bypasses RLS
--    entirely, so these policies only serve to let anon/authenticated
--    write directly if a client key leaked. Same pattern already fixed
--    for other tables in 001_security_fixes.sql.
-- ========================================

-- ========================================
-- Phase 1: Restrict SECURITY DEFINER functions to service_role
-- ========================================

REVOKE EXECUTE ON FUNCTION get_vault_secret(TEXT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION get_vault_secret(TEXT) TO service_role;

REVOKE EXECUTE ON FUNCTION cleanup_expired_codes() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION cleanup_expired_codes() TO service_role;

REVOKE EXECUTE ON FUNCTION is_invite_code_valid(UUID) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION is_invite_code_valid(UUID) TO service_role;

REVOKE EXECUTE ON FUNCTION use_invite_code(UUID, UUID) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION use_invite_code(UUID, UUID) TO service_role;

-- ========================================
-- Phase 2: Drop overly-permissive face_tags policies
-- ========================================

DROP POLICY IF EXISTS "Allow insert face tags" ON face_tags;
DROP POLICY IF EXISTS "Allow update face tags" ON face_tags;
DROP POLICY IF EXISTS "Allow delete face tags" ON face_tags;

-- ========================================
-- Verification
-- ========================================

-- Check EXECUTE grants: should show only service_role (and postgres/owner) for these functions
SELECT
  p.proname,
  r.rolname AS grantee,
  has_function_privilege(r.rolname, p.oid, 'EXECUTE') AS can_execute
FROM pg_proc p
CROSS JOIN (VALUES ('anon'), ('authenticated'), ('service_role')) AS r(rolname)
WHERE p.proname IN ('get_vault_secret', 'cleanup_expired_codes', 'is_invite_code_valid', 'use_invite_code')
ORDER BY p.proname, r.rolname;

-- Check face_tags policies were removed (should return no rows for these policy names)
SELECT schemaname, tablename, policyname
FROM pg_policies
WHERE tablename = 'face_tags'
AND policyname IN ('Allow insert face tags', 'Allow update face tags', 'Allow delete face tags');

-- ========================================
-- Migration Complete
-- ========================================
-- After running this migration:
-- 1. Re-run the Security Advisor to verify these warnings are resolved:
--    - rls_policy_always_true (face_tags x3)
--    - anon_security_definer_function_executable (x4)
--    - authenticated_security_definer_function_executable (x4)
-- 2. Remaining warnings (not addressed here, see migration comments):
--    - extension_in_public (vector) — deferred, high blast radius, no exploit path
--    - auth_leaked_password_protection — enable via Dashboard:
--      Authentication > Providers > Email > Leaked Password Protection
-- ========================================
