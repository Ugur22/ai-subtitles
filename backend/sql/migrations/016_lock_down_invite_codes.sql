-- ========================================
-- Lock down invite_codes (signup gate secrets)
-- ========================================
-- Run this in Supabase SQL Editor.
--
-- invite_codes_read_unused was FOR SELECT USING (used_by IS NULL) with no role
-- restriction, and Supabase grants SELECT on public tables to anon by default.
-- Anyone holding the public anon key could list every unused code via
-- GET /rest/v1/invite_codes?used_by=is.null and use one to register.
--
-- Invite checks, creation and admin management all go through the backend,
-- which uses SUPABASE_SERVICE_KEY (bypasses RLS), and the frontend never reads
-- this table, so client roles need no access at all.
--
-- Existing unused codes were readable before this migration: delete and
-- re-issue any that have not been handed out.

BEGIN;

ALTER TABLE public.invite_codes ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE r record;
BEGIN
  FOR r IN
    SELECT policyname FROM pg_policies
    WHERE schemaname = 'public' AND tablename = 'invite_codes'
      AND NOT ('service_role' = ANY(roles))
  LOOP
    EXECUTE format('DROP POLICY %I ON public.invite_codes', r.policyname);
  END LOOP;
END $$;

REVOKE ALL ON public.invite_codes FROM anon, authenticated;

COMMIT;
