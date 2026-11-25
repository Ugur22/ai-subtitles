# Offline, free feedback loop for humans, git hooks and agents.
# Never calls deploy.sh, gcloud, Supabase or any paid LLM; paid evals stay manual (backend/evals/README.md).
# One-time setup for the pre-commit hook: git config core.hooksPath scripts/githooks

PY ?= backend/venv/bin/python

.PHONY: check check-fast tests-isolated lint-backend lint-frontend test-backend test-frontend typecheck-frontend test-ratchets \
	ratchet-tighten mutation-check

check-fast: lint-backend lint-frontend

check: check-fast tests-isolated typecheck-frontend test-frontend

tests-isolated:
	@$(MAKE) --no-print-directory -j2 test-backend test-ratchets

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

# Owner-only engineering rules that may not get worse (tools/ratchets/ratchet.py). Agents fix the code, never the
# baseline; CI runs the same files, which agent PRs can't change.
test-ratchets:
	@env -u TEST_DATABASE_URL $(PY) -m pytest -q -p no:cacheprovider tools/ratchets/rules

# Owner: drop stale ratchet exceptions (never adds). Add one: make ratchet-tighten ARGS='--rule R --add FP --reason "..."'
ratchet-tighten:
	@$(PY) tools/ratchets/tighten.py $(ARGS)

# Proof that the critical tests catch the bugs they exist for (tools/ratchets/mutations.json). Needs a clean tree.
mutation-check:
	@env -u TEST_DATABASE_URL $(PY) tools/ratchets/run_mutations.py
