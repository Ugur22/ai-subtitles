#!/usr/bin/env bash
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

set -euo pipefail

# shellcheck source=deploy_image.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/deploy_image.sh"

AB_JOB_NAME="ai-subs-diarization-ab"

usage() { sed -n '/^# Usage:/,/^# Keep/p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 1; }

ab_build() {
    resolve_tag
    check_prerequisites
    build_and_push
    print_info "Built ${IMAGE_REF}; next: $0 deploy ${IMAGE_TAG}"
}

ab_deploy() {
    REQUESTED_TAG="$1"
    resolve_tag
    if ! image_exists "${IMAGE_REF}"; then
        print_error "${IMAGE_REF} does not exist in Artifact Registry"
        exit 1
    fi
    WORKER_JOB_NAME="${AB_JOB_NAME}"
    WORKER_ARGS="evals/diarization_ab.py"
    deploy_worker_job
}

ab_run() {
    local clip="$1" label="$2"
    shift 2
    local IFS=,
    local args="evals/diarization_ab.py,--clip,${clip},--label,${label}${*:+,$*}"
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
