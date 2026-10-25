-- ========================================
-- Lock down user_profiles writes (privilege escalation fix)
-- ========================================
-- Run this in Supabase SQL Editor.
--
-- user_profiles holds authorization state (is_admin, email_verified,
-- subscription_plan, subscription_status, stripe_*). The old owner policy
-- was FOR ALL on auth.uid() = id with no column restriction, and Supabase
-- grants UPDATE on public tables to anon/authenticated by default. Any
-- registered user could PATCH their own row through PostgREST with their own
-- JWT and set is_admin = true or subscription_plan = 'pro'.
--
-- Every writer is the backend, which uses SUPABASE_SERVICE_KEY and bypasses
-- RLS, and the frontend never touches this table, so client roles only need
-- to read their own row.

BEGIN;

-- Dropped by role rather than by name: the INSERT policy for authenticated
-- users was created in the dashboard and is not defined in the repo.
DO $$
DECLARE r record;
BEGIN
  FOR r IN
    SELECT policyname FROM pg_policies
    WHERE schemaname = 'public' AND tablename = 'user_profiles'
      AND NOT ('service_role' = ANY(roles))
  LOOP
    EXECUTE format('DROP POLICY %I ON public.user_profiles', r.policyname);
  END LOOP;
END $$;

CREATE POLICY user_profiles_select_own ON public.user_profiles
  FOR SELECT TO authenticated
  USING (auth.uid() = id);

REVOKE INSERT, UPDATE, DELETE ON public.user_profiles FROM anon, authenticated;

COMMIT;
