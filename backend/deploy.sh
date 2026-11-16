#!/bin/bash

###############################################################################
# AI-Subs Backend - Cloud Run Deployment Script
###############################################################################
# Builds the backend image with Cloud Build and deploys it to the Cloud Run
# Service and the GPU worker Job. Run it from your own terminal with Owner
# credentials; CI deploys through .github/workflows/deploy.yml instead.
#
# Usage: ./deploy.sh [--skip-build] [--allow-dirty] [--skip-migration-check]
#   --skip-build   Redeploy the image already built for the current commit.
#   --allow-dirty  Deploy uncommitted changes, tagged <sha>-dirty.
#   --skip-migration-check  Skip the check that every repo migration is applied in Supabase.
#
# The Service and Job definitions (resources, env vars, secrets) live in
# infra/scripts/deploy_image.sh, which this script runs; edit them there.
# Roll back with infra/scripts/rollback.sh <tag>.
###############################################################################

set -euo pipefail

for arg in "$@"; do
    case "${arg}" in
        --skip-build|--allow-dirty|--skip-migration-check) ;;
        *) echo "Error: Unknown argument: ${arg}" >&2; exit 2 ;;
    esac
done

echo ""
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║         AI-Subs Backend - Cloud Run Deployment           ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo ""

exec "$(cd "$(dirname "$0")/.." && pwd)/infra/scripts/deploy_image.sh" "$@"
