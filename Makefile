# Offline, free feedback loop for humans, git hooks and agents.
# Never calls deploy.sh, gcloud, Supabase or any paid LLM; paid evals stay manual (backend/evals/README.md).
# One-time setup for the pre-commit hook: git config core.hooksPath scripts/githooks

PY := backend/venv/bin/python

.PHONY: check check-fast lint-backend lint-frontend test-backend typecheck-frontend

check-fast: lint-backend lint-frontend

check: check-fast test-backend typecheck-frontend

# Syntax-only (ast.parse): the backend has no linter configured and this writes no .pyc files.
lint-backend:
	@find backend -name '*.py' -not -path 'backend/venv/*' -not -path '*/node_modules/*' -print0 \
		| xargs -0 $(PY) -c "import ast, sys; [ast.parse(open(f).read(), f) for f in sys.argv[1:]]"

lint-frontend:
	@cd frontend && npx eslint .

# TEST_DATABASE_URL unset keeps the Postgres integration tests skipped (no network).
test-backend:
	@env -u TEST_DATABASE_URL $(PY) -m pytest -q

typecheck-frontend:
	@cd frontend && npx tsc -b --noEmit
