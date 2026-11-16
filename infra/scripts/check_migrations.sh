#!/usr/bin/env bash
# Fails when backend/sql/migrations holds a migration that Supabase has not
# recorded in public.schema_migrations (migration 023). Deploys never apply
# migrations; apply them by hand first, then deploy.
#
# Usage: infra/scripts/check_migrations.sh <supabase-url>
# Needs SUPABASE_ANON_KEY (the public anon/publishable key the frontend uses;
# a GitHub repository variable in CI). Locally it falls back to
# VITE_SUPABASE_ANON_KEY from frontend/.env.local or frontend/.env.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
MIGRATIONS_DIR="${REPO_ROOT}/backend/sql/migrations"

SUPABASE_URL="${1:-}"
if [ -z "${SUPABASE_URL}" ]; then
    echo "usage: $0 <supabase-url>" >&2
    exit 2
fi

fail() {
    echo -e "\033[0;31mMigration check failed: $1\033[0m" >&2
    exit 1
}

key="${SUPABASE_ANON_KEY:-}"
if [ -z "${key}" ]; then
    for env_file in "${REPO_ROOT}/frontend/.env.local" "${REPO_ROOT}/frontend/.env"; do
        if [ -f "${env_file}" ]; then
            key="$(sed -nE 's/^VITE_SUPABASE_ANON_KEY=["'\'']?([^"'\'']*)["'\'']?$/\1/p' "${env_file}" | tail -1)"
            [ -n "${key}" ] && break
        fi
    done
fi
[ -n "${key}" ] || fail "SUPABASE_ANON_KEY is not set. Export the Supabase anon key, or deploy with --skip-migration-check."

repo_versions="$(find "${MIGRATIONS_DIR}" -maxdepth 1 -name '[0-9][0-9][0-9]_*.sql' ! -name '*_rollback.sql' \
    -exec basename {} \; | cut -c1-3 | sort -u)"

response="$(curl -sS --max-time 20 -w '\n%{http_code}' \
    -H "apikey: ${key}" \
    "${SUPABASE_URL}/rest/v1/schema_migrations?select=version")" \
    || fail "could not reach ${SUPABASE_URL}"
status="${response##*$'\n'}"
body="${response%$'\n'*}"

if [ "${status}" == "404" ] || grep -q '"PGRST205"\|"42P01"' <<<"${body}"; then
    fail "public.schema_migrations does not exist in Supabase. Apply backend/sql/migrations/023_schema_migrations.sql first."
fi
[ "${status}" == "200" ] || fail "Supabase answered HTTP ${status}: ${body}"

applied_versions="$(python3 -c 'import json, sys; print("\n".join(sorted(r["version"] for r in json.load(sys.stdin))))' <<<"${body}")" \
    || fail "unexpected response from Supabase: ${body}"

missing="$(comm -23 <(echo "${repo_versions}") <(echo "${applied_versions}"))"
latest_applied="$(echo "${applied_versions}" | tail -1)"

if [ -n "${missing}" ]; then
    files="$(for v in ${missing}; do find "${MIGRATIONS_DIR}" -maxdepth 1 -name "${v}_*.sql" ! -name '*_rollback.sql' -exec basename {} \;; done)"
    fail "the repo has migrations that are not applied in Supabase (latest applied: ${latest_applied:-none}):
$(sed 's/^/  backend\/sql\/migrations\//' <<<"${files}")
Apply them in order in the Supabase SQL editor, then deploy again."
fi

echo "Migration check passed: all $(echo "${repo_versions}" | wc -l | tr -d ' ') repo migrations are applied (latest ${latest_applied})."
