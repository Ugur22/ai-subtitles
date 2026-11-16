BEGIN;

-- Rollback of 023_schema_migrations.sql. Deploys then fail the migration check
-- until 023 is applied again (or deploy with --skip-migration-check).

DROP POLICY IF EXISTS schema_migrations_anon_read ON public.schema_migrations;
DROP TABLE IF EXISTS public.schema_migrations;

COMMIT;
