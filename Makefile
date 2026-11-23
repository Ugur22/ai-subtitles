# Offline, free feedback loop for humans, git hooks and agents.
# Never calls deploy.sh, gcloud, Supabase or any paid LLM; paid evals stay manual (backend/evals/README.md).
# One-time setup for the pre-commit hook: git config core.hooksPath scripts/githooks

PY ?= backend/venv/bin/python

.PHONY: check check-fast lint-backend lint-frontend test-backend test-frontend typecheck-frontend

check-fast: lint-backend lint-frontend

check: check-fast test-backend typecheck-frontend test-frontend

lint-backend:
	@$(PY) -m ruff check backend

lint-frontend:
	@cd frontend && npx eslint .

# TEST_DATABASE_URL unset keeps the Postgres integration tests skipped (no network).
test-backend:
	@env -u TEST_DATABASE_URL $(PY) -m pytest -q

typecheck-frontend:
	@cd frontend && npx tsc -b --noEmit

test-frontend:
	@cd frontend && npx vitest run
