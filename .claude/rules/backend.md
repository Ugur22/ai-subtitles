---
paths:
  - "backend/**/*.py"
  - "backend/requirements.txt"
  - "backend/constraints.txt"
  - "backend/ruff.toml"
  - "pytest.ini"
---

# Backend rules

## Layout
- `backend/main.py` includes the routers in `backend/routers/`; business logic lives in `backend/services/`; settings are in `backend/config.py` (`os.getenv` with defaults).
- Data is in Supabase. `backend/services/supabase_service.py` creates the client lazily and `backend/services/transcription_repository.py` holds the transcription queries. Migrations: `.claude/rules/database-and-migrations.md`.
- Models baked into the Docker image: `backend/download_models.py`. Runtime defaults (Whisper size, embedding model): `backend/config.py`.

## Auth and ownership
- Every route needs auth: `@require_auth` or `@require_admin` from `backend/middleware/auth.py`. Get the caller with `authenticated_user_id(request)` from `backend/services/transcription_access.py`, which fails closed with a 401.
- The Supabase service key bypasses row-level security, so enforce ownership in code: scope every query on user data by `user_id` and treat a null owner as no access. Another user's job, transcription, screenshot or key must be indistinguishable from a missing one.
- A new data path needs a test with a second user; `backend/tests/test_access_security.py` and `test_job_security.py` show the expected style.
- Never declare a route twice or bring back the removed legacy routes; `backend/tests/test_route_contracts.py` fails on both. The `route_access` ratchet (`tools/ratchets/rules/`) checks route auth.

## Statelessness and cost
- Cloud Run scales to zero and runs several instances: keep nothing that must survive a request on local disk or in module-level memory (the voiceprints bug).
- List endpoints never re-sign URLs per item (`GET /api/jobs` timed out that way).

## Heavy imports
- torch, torchaudio, pyannote, faster-whisper and sentence-transformers are imported at module level in some modules, and CI installs only the CPU torch build. Do not add new heavy imports at module level; import inside the function. The `heavy_imports` ratchet enforces this.

## Secrets
- Never log tokens, signed URLs or key material, and never return them in responses.
- Never read `backend/.env` or any key file.
- Config and secrets loading (`backend/config.py`, `dependencies.py`, `load_dotenv`, `os.environ[...]`) is Sensitive work.

## Verification
- Run pytest from the repo root (`pytest.ini` sets `testpaths = backend/tests`). Tests are offline: use fakes and `monkeypatch.setattr(settings, ...)`, with no network, no model downloads and no real Supabase.
- Add or extend a test for each behavior change; a test should fail without your change.
- `make check` before reporting done.
