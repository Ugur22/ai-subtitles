#!/usr/bin/env bash
# Point the Cloud Run Service and worker Job back at an image that was built before.
#
# Usage: infra/scripts/rollback.sh <sha-tag | sha256:digest> [--yes]
#        infra/scripts/rollback.sh --list     # the 10 most recent tags and what runs now
#
# Rolls back code only: env vars, secrets and resources come from the current
# deploy_image.sh, and the database is not touched. A tag built before a
# migration that the current schema has since changed may not work.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ID="ai-subs-poc"
REGION="us-central1"
IMAGE_REPO="${REGION}-docker.pkg.dev/${PROJECT_ID}/ai-subs-repo/ai-subs-backend"

usage() { awk 'NR > 1 && /^#/ { print; next } NR > 1 { exit }' "$0"; }

if [ $# -lt 1 ]; then
    usage >&2
    exit 2
fi

case "$1" in
    -h|--help) usage; exit 0 ;;
    --list)
        echo "Running now:"
        gcloud run services describe ai-subs-backend --region="${REGION}" --project="${PROJECT_ID}" \
            --format='value(spec.template.spec.containers[0].image)'
        echo ""
        echo "Most recent images:"
        gcloud artifacts docker images list "${IMAGE_REPO}" --project="${PROJECT_ID}" \
            --include-tags --sort-by=~UPDATE_TIME --limit=10 \
            --format='table(tags.list():label=TAGS,update_time.date("%Y-%m-%d %H:%M"):label=UPDATED,version.basename():label=DIGEST)'
        exit 0
        ;;
esac

TAG="$1"
shift
exec "${SCRIPT_DIR}/deploy_image.sh" --tag "${TAG}" "$@"
