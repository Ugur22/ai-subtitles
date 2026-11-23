#!/usr/bin/env bash
###############################################################################
# Run backend/evals/diarization_ab.py on a dedicated GPU job, to compare
# diarization between two images (e.g. pyannote 3.1 vs 4.x). Never touches the
# prod Service or worker Job. Run from your own terminal with Owner credentials.
#
# Usage: infra/scripts/diarization_ab.sh <command>
#   build                     Build HEAD (clean tree) as ai-subs-backend:<sha>, the same
#                             tag deploy_image.sh uses, so a later release reuses it.
#   deploy <sha>              Point the A/B job at that image.
#   run <clip> <label> [...]  Diarize gs://<bucket>/<clip> on the job's current image and
#                             write ab-results/<label>/<clip>.json. Extra args go to the
#                             script (e.g. --max-speakers 4).
#   fetch <label> <dir>       Copy ab-results/<label>/ to a local directory.
#
# Keep clips under ab-clips/: uploads/ is deleted after 30 days by the bucket lifecycle.
###############################################################################

set -euo pipefail

# Shares the worker's project, identity, GPU, env and secrets, so the A/B job can't drift.
# shellcheck source=deploy_image.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/deploy_image.sh"

AB_JOB_NAME="ai-subs-diarization-ab"

usage() { sed -n '/^# Usage:/,/^# Keep/p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 1; }

ab_build() {
    if [ -n "$(git -C "${REPO_ROOT}" status --porcelain)" ]; then
        print_error "Uncommitted changes; commit first so the tag names exactly this code"
        exit 1
    fi
    IMAGE_TAG="$(git -C "${REPO_ROOT}" rev-parse --short=12 HEAD)"
    IMAGE_REF="${IMAGE_REPO}:${IMAGE_TAG}"
    check_prerequisites
    build_and_push
    print_info "Built ${IMAGE_REF}; next: $0 deploy ${IMAGE_TAG}"
}

ab_deploy() {
    local tag="$1"
    local image_ref="${IMAGE_REPO}:${tag}"
    if ! image_exists "${image_ref}"; then
        print_error "${image_ref} does not exist in Artifact Registry"
        exit 1
    fi
    print_step "Pointing ${AB_JOB_NAME} at ${image_ref}..."
    gcloud run jobs deploy "${AB_JOB_NAME}" \
        --image="${image_ref}" \
        --region="${REGION}" \
        --project="${PROJECT_ID}" \
        --service-account="${WORKER_SERVICE_ACCOUNT}" \
        --memory="${WORKER_MEMORY}" \
        --cpu="${WORKER_CPU}" \
        --gpu="${GPU_COUNT}" \
        --gpu-type="${GPU_TYPE}" \
        --no-gpu-zonal-redundancy \
        --task-timeout="${WORKER_TASK_TIMEOUT}" \
        --max-retries=0 \
        --parallelism=1 \
        --tasks=1 \
        --command="python" \
        --args="evals/diarization_ab.py,--help" \
        --set-env-vars="^@^ENABLE_GCS_UPLOADS=${ENABLE_GCS_UPLOADS}@GCS_BUCKET_NAME=${GCS_BUCKET_NAME}@SUPABASE_URL=${SUPABASE_URL}@ENVIRONMENT=${ENVIRONMENT}@FASTWHISPER_DEVICE=${FASTWHISPER_DEVICE}" \
        --set-secrets="^@^${WORKER_SECRETS}"
}

ab_run() {
    local clip="$1" label="$2"
    shift 2
    local args="evals/diarization_ab.py,run,--clip,${clip},--label,${label}"
    for extra in "$@"; do args="${args},${extra}"; done
    print_step "Running ${clip} as '${label}' on ${AB_JOB_NAME}..."
    gcloud run jobs execute "${AB_JOB_NAME}" \
        --region="${REGION}" --project="${PROJECT_ID}" \
        --args="${args}" --wait
    print_info "Result: gs://${GCS_BUCKET_NAME}/ab-results/${label}/$(basename "${clip%.*}").json"
}

ab_fetch() {
    local label="$1" dir="$2"
    mkdir -p "${dir}"
    gcloud storage cp "gs://${GCS_BUCKET_NAME}/ab-results/${label}/*.json" "${dir}/" --project="${PROJECT_ID}"
}

case "${1:-}" in
    build) ab_build ;;
    deploy) [ $# -eq 2 ] || usage; ab_deploy "$2" ;;
    run) [ $# -ge 3 ] || usage; shift; ab_run "$@" ;;
    fetch) [ $# -eq 3 ] || usage; ab_fetch "$2" "$3" ;;
    *) usage ;;
esac
