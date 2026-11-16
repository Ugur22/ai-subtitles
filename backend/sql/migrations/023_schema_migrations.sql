BEGIN;

-- Records which files in backend/sql/migrations have been applied, so a deploy
-- can refuse code that needs a migration Supabase does not have yet
-- (infra/scripts/check_migrations.sh, run by infra/scripts/deploy_image.sh).
-- Rollback: 023_schema_migrations_rollback.sql
--
-- Convention from here on: every migration ends with
--   INSERT INTO public.schema_migrations (version) VALUES ('NNN') ON CONFLICT (version) DO NOTHING;
-- inside its own transaction, so the row exists exactly when the migration committed.
-- backend/tests/test_schema_migrations.py enforces this.

CREATE TABLE IF NOT EXISTS public.schema_migrations (
  version TEXT PRIMARY KEY CHECK (version ~ '^[0-9]{3}$'),
  applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The deploy check reads this with the public anon key, so anon may SELECT and
-- nothing else. Migration numbers are the only data here and reveal nothing
-- that the public repository does not. Writes need the service role or the SQL editor.
ALTER TABLE public.schema_migrations ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.schema_migrations FROM anon, authenticated;
GRANT SELECT ON public.schema_migrations TO anon;

DROP POLICY IF EXISTS schema_migrations_anon_read ON public.schema_migrations;
CREATE POLICY schema_migrations_anon_read ON public.schema_migrations
  FOR SELECT TO anon USING (true);

-- Backfill: every migration in the repo before this one, all live in production
-- as of 2026-11-16 (014 was never used). Confirm before applying; see docs/INFRASTRUCTURE.md.
INSERT INTO public.schema_migrations (version) VALUES
  ('001'),
  ('002'),
  ('003'),
  ('004'),
  ('005'),
  ('006'),
  ('007'),
  ('008'),
  ('009'),
  ('010'),
  ('011'),
  ('012'),
  ('013'),
  ('015'),
  ('016'),
  ('017'),
  ('018'),
  ('019'),
  ('020'),
  ('021'),
  ('022'),
  ('023')
ON CONFLICT (version) DO NOTHING;

COMMIT;
