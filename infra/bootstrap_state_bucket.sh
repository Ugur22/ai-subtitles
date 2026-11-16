#!/usr/bin/env bash
# Creates the GCS bucket that holds Terraform state for infra/terraform.
# Terraform cannot create its own backend bucket, so this runs once by hand
# (with Owner credentials). Safe to re-run: existing settings are re-applied, never removed.
#
# Usage: infra/bootstrap_state_bucket.sh [--dry-run]

set -euo pipefail

PROJECT_ID="ai-subs-poc"
LOCATION="us-central1"
BUCKET="gs://ai-subs-poc-tfstate"
# Noncurrent state versions to keep; each apply writes one.
KEEP_NONCURRENT_VERSIONS=20

DRY_RUN="false"
for arg in "$@"; do
    case "${arg}" in
        --dry-run) DRY_RUN="true" ;;
        -h|--help) sed -n '2,7p' "$0"; exit 0 ;;
        *) echo "Unknown argument: ${arg}" >&2; exit 2 ;;
    esac
done

run() {
    if [ "${DRY_RUN}" == "true" ]; then
        printf '[dry-run]'; printf ' %q' "$@"; printf '\n'
    else
        "$@"
    fi
}

LIFECYCLE_FILE="$(mktemp "${TMPDIR:-/tmp}/tfstate-lifecycle.XXXXXX")"
trap 'rm -f "${LIFECYCLE_FILE}"' EXIT
cat > "${LIFECYCLE_FILE}" <<EOF
{"rule": [{"action": {"type": "Delete"}, "condition": {"isLive": false, "numNewerVersions": ${KEEP_NONCURRENT_VERSIONS}}}]}
EOF

if gcloud storage buckets describe "${BUCKET}" --project="${PROJECT_ID}" --format="value(name)" >/dev/null 2>&1; then
    echo "${BUCKET} exists; re-applying its settings"
else
    echo "Creating ${BUCKET}"
    run gcloud storage buckets create "${BUCKET}" \
        --project="${PROJECT_ID}" \
        --location="${LOCATION}" \
        --uniform-bucket-level-access \
        --public-access-prevention
fi

run gcloud storage buckets update "${BUCKET}" \
    --project="${PROJECT_ID}" \
    --versioning \
    --uniform-bucket-level-access \
    --public-access-prevention \
    --lifecycle-file="${LIFECYCLE_FILE}"

if [ "${DRY_RUN}" == "true" ]; then
    echo "Lifecycle policy that would be applied:"
    cat "${LIFECYCLE_FILE}"
else
    gcloud storage buckets describe "${BUCKET}" --project="${PROJECT_ID}" \
        --format="yaml(name,location,versioning_enabled,public_access_prevention,uniform_bucket_level_access)"
fi
