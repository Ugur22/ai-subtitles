---
paths:
  - "backend/sql/**"
  - "backend/migrations/**"
  - "backend/services/supabase_service.py"
  - "backend/services/transcription_repository.py"
  - "backend/tests/test_schema_migrations.py"
  - "backend/tests/test_job_migration_rollbacks.py"
  - "backend/tests/*_postgres.py"
  - "infra/scripts/check_migrations.sh"
---

# Database and migration rules

SQL and migrations are Sensitive (`tools/harness/risk.py`): `advisor` on the plan first, a `## Risk` section, and a migration ships first and alone in a stacked PR. Details: "Database migrations" in `docs/INFRASTRUCTURE.md`.

## Writing a migration
- New migrations go in `backend/sql/migrations/` with the next free number and a matching `_rollback.sql`. Never edit an applied migration.
- Every migration after 023 ends with its own `public.schema_migrations` row inside its transaction, and its rollback deletes that row; `backend/tests/test_schema_migrations.py` enforces both:
  ```sql
  INSERT INTO public.schema_migrations (version) VALUES ('024') ON CONFLICT (version) DO NOTHING;
  COMMIT;
  ```
- Backward compatible: the user applies the migration before deploying, so the code currently on `main` must keep working against the new schema. Say in the rollback header whether the previous image works with either version (see `024_job_dedup_by_model_rollback.sql`).
- Make it safe to apply twice, as the existing migrations are (`IF NOT EXISTS`, `CREATE OR REPLACE`, `ON CONFLICT DO NOTHING`, `DROP ... IF EXISTS`), and check that the rollback really undoes it.

## Ownership in the schema
- Tables with user data carry `user_id`, and queries and SQL functions scope by it; a null owner means no access (the service key bypasses RLS). Earlier examples: migrations 009, 010 and 017 (owner-scoped embeddings and captions).
- `SECURITY DEFINER` functions are locked down (migration 012): revoke `EXECUTE` from `PUBLIC` (and `anon`, `authenticated`) and grant it to `service_role` only, as `022_gpu_slot_hold.sql` does.

## Repairs and deletes
- Anything that deletes or rewrites stored data is Sensitive. A one-off data repair goes in `backend/sql/cleanup/` as a manual script with a preview query before each delete (see `2026-11_orphaned_derived_data.sql`); it is never run by a migration or a deploy.
- Reverting the commit does not undo data changes: the `## Risk` section says whether recovery needs the `_rollback.sql`, a data repair or a backup.

## Authority
- Applying a migration to Supabase is the user's alone ("Irreversible or production" in `CLAUDE.md`): prepare the files and the exact SQL, then stop. Deploys never apply migrations; `infra/scripts/check_migrations.sh` fails a deploy while a repo migration is missing from `public.schema_migrations`.

## Tests
- `test_schema_migrations.py` and `test_job_migration_rollbacks.py` run offline in `make check`. Tests that need Postgres (`*_postgres.py`) are skipped unless `TEST_DATABASE_URL` points at a scratch database; `make check` unsets it. Say so when a change was not run against Postgres.
