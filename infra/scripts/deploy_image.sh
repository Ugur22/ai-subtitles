#!/usr/bin/env bash
###############################################################################
# Build and deploy one immutable image to the Cloud Run Service and worker Job.
#
# This is the single definition of the deployed Service and Job: resources,
# env vars and secret mounts. backend/deploy.sh (local), infra/scripts/rollback.sh
# and .github/workflows/deploy.yml all call it. There is deliberately no Cloud
# Run YAML: a second copy drifts, and `gcloud run services replace` with a stale
# file drops env vars and secrets.
#
# Usage: infra/scripts/deploy_image.sh [options]
#   --skip-build            Deploy the image already built for HEAD; fail if it does not exist.
#   --allow-dirty           Allow uncommitted changes; the image is tagged <sha>-dirty.
#   --tag <tag>             Deploy an existing SHA tag or sha256:<digest> (used by rollback.sh);
#                           no build, no git checks. Digests reach images from before SHA tags.
#   --yes                   Do not ask for confirmation (CI).
#
# Images are tagged with the 12-character git SHA and never with :latest, so a
# tag always names exactly one build and the Service and Job always run the same code.
###############################################################################

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
BACKEND_DIR="${REPO_ROOT}/backend"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
PROJECT_ID="ai-subs-poc"
REGION="us-central1"
SERVICE_NAME="ai-subs-backend"
WORKER_JOB_NAME="ai-subs-worker"
IMAGE_REPO="${REGION}-docker.pkg.dev/${PROJECT_ID}/ai-subs-repo/ai-subs-backend"
# Least-privilege runtime identities, created by infra/terraform/iam.tf.
API_SERVICE_ACCOUNT="ai-subs-api@${PROJECT_ID}.iam.gserviceaccount.com"
WORKER_SERVICE_ACCOUNT="ai-subs-worker@${PROJECT_ID}.iam.gserviceaccount.com"
# Cloud Build runs as the deployer (infra/terraform/wif.tf) for local and CI deploys alike,
# so builds never depend on the default compute SA.
DEPLOYER_SERVICE_ACCOUNT="ai-subs-deployer@${PROJECT_ID}.iam.gserviceaccount.com"
BUILD_STAGING_BUCKET="gs://${PROJECT_ID}-build-staging"

# Service (HTTP only) — no GPU; the heavy work has moved to the worker Job.
SERVICE_MEMORY="8Gi"
SERVICE_CPU="2"
SERVICE_TIMEOUT="300"
SERVICE_MIN_INSTANCES="0"
SERVICE_MAX_INSTANCES="2"
PORT="8000"

# Worker Job (GPU pipeline). 1h is the GPU task-timeout cap on Cloud Run Jobs.
WORKER_MEMORY="16Gi"
WORKER_CPU="4"
WORKER_TASK_TIMEOUT="3600"
# Cloud Run does not expose the task timeout to the container, so it is passed
# as CLOUD_RUN_TASK_TIMEOUT. The worker stops ~10 min before it and continues
# in a new execution (see docs/ARCHITECTURE.md, "Long files").
WORKER_MAX_RETRIES="0"  # Don't auto-retry — leave it to our own retry endpoint.
GPU_COUNT="1"
GPU_TYPE="nvidia-l4"

# Environment variables (non-sensitive)
CORS_ORIGINS='["https://ai-subs.netlify.app"]'
ENABLE_GCS_UPLOADS="true"
GCS_BUCKET_NAME="ai-subs-uploads"
SUPABASE_URL="https://ngfcjdxfhppnzpocgktw.supabase.co"
XAI_MODEL="grok-4.3"
ENVIRONMENT="production"
# Where Stripe redirects users after Checkout / Customer Portal
PUBLIC_APP_URL="https://ai-subs.netlify.app"

# Speaker diarization settings
MIN_SPEAKERS="1"
MAX_SPEAKERS="0"  # 0 = unlimited/auto-detect speakers

# Whisper settings
FASTWHISPER_DEVICE="cuda"  # Use GPU for transcription (faster than CPU)
FASTWHISPER_MODEL="large-v3"  # Worker only; must match WHISPER_MODEL_REPO baked in the Dockerfile
FASTWHISPER_COMPUTE_TYPE="float16"  # int8 is the CPU default

export PATH="/opt/homebrew/share/google-cloud-sdk/bin:${PATH}"

print_step() { echo -e "${BLUE}==>${NC} ${GREEN}$1${NC}"; }
print_error() { echo -e "${RED}Error: $1${NC}" >&2; }
print_warning() { echo -e "${YELLOW}Warning: $1${NC}"; }
print_info() { echo -e "${BLUE}$1${NC}"; }

SKIP_BUILD="false"
ALLOW_DIRTY="false"
ASSUME_YES="false"
REQUESTED_TAG=""

parse_args() {
    while [ $# -gt 0 ]; do
        case "$1" in
            --skip-build) SKIP_BUILD="true" ;;
            --allow-dirty) ALLOW_DIRTY="true" ;;
            --yes) ASSUME_YES="true" ;;
            --tag)
                [ $# -ge 2 ] || { print_error "--tag needs a value"; exit 2; }
                REQUESTED_TAG="$2"; shift ;;
            -h|--help) awk 'NR > 1 && /^#/ { print; next } NR > 1 { exit }' "$0"; exit 0 ;;
            *) print_error "Unknown argument: $1"; exit 2 ;;
        esac
        shift
    done
}

# Decided before any gcloud call, so a dirty tree is refused without touching GCP.
resolve_tag() {
    if [ -n "${REQUESTED_TAG}" ]; then
        if [[ "${REQUESTED_TAG}" =~ ^sha256:[0-9a-f]{64}$ ]]; then
            IMAGE_REF="${IMAGE_REPO}@${REQUESTED_TAG}"
        elif [[ "${REQUESTED_TAG}" =~ ^[0-9a-f]{7,40}(-dirty)?$ ]]; then
            IMAGE_REF="${IMAGE_REPO}:${REQUESTED_TAG}"
        else
            print_error "'${REQUESTED_TAG}' is neither a git SHA tag (0123456789ab, 0123456789ab-dirty) nor sha256:<digest>"
            exit 2
        fi
        IMAGE_TAG="${REQUESTED_TAG}"
        SKIP_BUILD="true"
        return
    fi

    local sha
    sha="$(git -C "${REPO_ROOT}" rev-parse --short=12 HEAD)"
    if [ -n "$(git -C "${REPO_ROOT}" status --porcelain)" ]; then
        if [ "${ALLOW_DIRTY}" != "true" ]; then
            print_error "The working tree has uncommitted changes, so the image would not match commit ${sha}."
            git -C "${REPO_ROOT}" status --short >&2
            print_info "Commit or stash them, or pass --allow-dirty to deploy them as ${sha}-dirty." >&2
            exit 1
        fi
        IMAGE_TAG="${sha}-dirty"
        print_warning "Deploying uncommitted changes as ${IMAGE_TAG}; a later --allow-dirty build overwrites this tag"
    else
        IMAGE_TAG="${sha}"
    fi
    IMAGE_REF="${IMAGE_REPO}:${IMAGE_TAG}"
}

check_prerequisites() {
    print_step "Checking prerequisites..."

    if ! command -v gcloud &> /dev/null; then
        print_error "gcloud CLI is not installed. Please install it from https://cloud.google.com/sdk/docs/install"
        exit 1
    fi

    ACTIVE_ACCOUNT=$(gcloud auth list --filter=status:ACTIVE --format="value(account)" 2>/dev/null || true)
    if [ -z "${ACTIVE_ACCOUNT}" ]; then
        print_error "Not authenticated with gcloud. Please run: gcloud auth login"
        exit 1
    fi

    print_info "Prerequisites check passed (${ACTIVE_ACCOUNT})"
}

image_exists() {
    gcloud artifacts docker images describe "$1" \
        --project="${PROJECT_ID}" --format="value(image_summary.digest)" >/dev/null 2>&1
}

build_and_push() {
    print_step "Building and pushing ${IMAGE_REF}..."

    # A clean SHA tag names one commit, so an existing image is that build; reruns skip it.
    if [[ "${IMAGE_TAG}" != *-dirty ]] && image_exists "${IMAGE_REF}"; then
        print_info "${IMAGE_REF} already exists; skipping the build"
        return
    fi

    # Layer cache: the image the Service runs now. A missing image only costs a cold build.
    local cache_from
    cache_from=$(gcloud run services describe "${SERVICE_NAME}" \
        --region="${REGION}" --project="${PROJECT_ID}" \
        --format='value(spec.template.spec.containers[0].image)' 2>/dev/null || true)
    cache_from="${cache_from:-${IMAGE_REF}}"
    print_info "Layer cache from ${cache_from}"

    if gcloud builds submit "${BACKEND_DIR}" \
        --config="${BACKEND_DIR}/cloudbuild.yaml" \
        --project="${PROJECT_ID}" \
        --region="${REGION}" \
        --service-account="projects/${PROJECT_ID}/serviceAccounts/${DEPLOYER_SERVICE_ACCOUNT}" \
        --gcs-source-staging-dir="${BUILD_STAGING_BUCKET}/source" \
        --gcs-log-dir="${BUILD_STAGING_BUCKET}/logs" \
        --substitutions="_IMAGE=${IMAGE_REF},_CACHE_FROM=${cache_from}"; then
        print_info "Image built and pushed"
    else
        print_error "Failed to build and push ${IMAGE_REF}"
        exit 1
    fi
}

# Deploy the FastAPI Service (HTTP API only — no GPU, no background pipeline).
# No --allow-unauthenticated: the allUsers invoker binding is already on the
# service, and re-asserting it needs run.services.setIamPolicy, which the deployer lacks.
deploy_to_cloud_run() {
    print_step "Deploying Cloud Run Service (HTTP, no GPU)..."

    if gcloud run deploy "${SERVICE_NAME}" \
        --image="${IMAGE_REF}" \
        --platform=managed \
        --region="${REGION}" \
        --project="${PROJECT_ID}" \
        --service-account="${API_SERVICE_ACCOUNT}" \
        --memory="${SERVICE_MEMORY}" \
        --cpu="${SERVICE_CPU}" \
        --gpu=0 \
        --cpu-boost \
        --timeout="${SERVICE_TIMEOUT}" \
        --min-instances="${SERVICE_MIN_INSTANCES}" \
        --max-instances="${SERVICE_MAX_INSTANCES}" \
        --port="${PORT}" \
        --set-env-vars="^@^CORS_ORIGINS=${CORS_ORIGINS}@ENABLE_GCS_UPLOADS=${ENABLE_GCS_UPLOADS}@GCS_BUCKET_NAME=${GCS_BUCKET_NAME}@SUPABASE_URL=${SUPABASE_URL}@XAI_MODEL=${XAI_MODEL}@ENVIRONMENT=${ENVIRONMENT}@MIN_SPEAKERS=${MIN_SPEAKERS}@MAX_SPEAKERS=${MAX_SPEAKERS}@FASTWHISPER_DEVICE=${FASTWHISPER_DEVICE}@PUBLIC_APP_URL=${PUBLIC_APP_URL}@WORKER_JOB_PROJECT=${PROJECT_ID}@WORKER_JOB_REGION=${REGION}@WORKER_JOB_NAME=${WORKER_JOB_NAME}" \
        --set-secrets="^@^SUPABASE_SERVICE_KEY=supabase-service-key:latest@APP_PASSWORD_HASH=app-password-hash:latest@HUGGINGFACE_TOKEN=huggingface-token:latest@GROQ_API_KEY=groq-api-key:latest@XAI_API_KEY=xai-api-key:latest@STRIPE_SECRET_KEY=stripe-secret-key:latest@STRIPE_PRO_PRICE_ID=stripe-pro-price-id:latest@STRIPE_WEBHOOK_SECRET=stripe-webhook-secret:latest@INTERNAL_API_KEY=internal-api-key:latest@FLAGSMITH_SERVER_KEY=flagsmith-server-key:latest"; then
        print_info "Service deployment successful"
    else
        print_error "Service deployment failed"
        exit 1
    fi
}

# Deploy / update the Cloud Run Job that runs the transcription pipeline.
# Same image as the Service, different entrypoint (python -m worker_main).
deploy_worker_job() {
    print_step "Deploying Cloud Run Worker Job (GPU)..."

    # `gcloud run jobs deploy` is upsert: creates if missing, updates if present.
    if gcloud run jobs deploy "${WORKER_JOB_NAME}" \
        --image="${IMAGE_REF}" \
        --region="${REGION}" \
        --project="${PROJECT_ID}" \
        --service-account="${WORKER_SERVICE_ACCOUNT}" \
        --memory="${WORKER_MEMORY}" \
        --cpu="${WORKER_CPU}" \
        --gpu="${GPU_COUNT}" \
        --gpu-type="${GPU_TYPE}" \
        --no-gpu-zonal-redundancy \
        --task-timeout="${WORKER_TASK_TIMEOUT}" \
        --max-retries="${WORKER_MAX_RETRIES}" \
        --parallelism=1 \
        --tasks=1 \
        --command="python" \
        --args="-m,worker_main" \
        --set-env-vars="^@^ENABLE_GCS_UPLOADS=${ENABLE_GCS_UPLOADS}@GCS_BUCKET_NAME=${GCS_BUCKET_NAME}@SUPABASE_URL=${SUPABASE_URL}@XAI_MODEL=${XAI_MODEL}@ENVIRONMENT=${ENVIRONMENT}@MIN_SPEAKERS=${MIN_SPEAKERS}@MAX_SPEAKERS=${MAX_SPEAKERS}@FASTWHISPER_DEVICE=${FASTWHISPER_DEVICE}@FASTWHISPER_MODEL=${FASTWHISPER_MODEL}@FASTWHISPER_COMPUTE_TYPE=${FASTWHISPER_COMPUTE_TYPE}@CLOUD_RUN_TASK_TIMEOUT=${WORKER_TASK_TIMEOUT}@WORKER_JOB_PROJECT=${PROJECT_ID}@WORKER_JOB_REGION=${REGION}@WORKER_JOB_NAME=${WORKER_JOB_NAME}" \
        --set-secrets="^@^SUPABASE_SERVICE_KEY=supabase-service-key:latest@HUGGINGFACE_TOKEN=huggingface-token:latest@GROQ_API_KEY=groq-api-key:latest@XAI_API_KEY=xai-api-key:latest"; then
        print_info "Worker Job deployment successful"
    else
        print_error "Worker Job deployment failed"
        exit 1
    fi
}

verify_deployment() {
    print_step "Verifying deployment..."

    SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" \
        --region="${REGION}" --project="${PROJECT_ID}" \
        --format='value(status.url)' 2>/dev/null || echo "")
    local service_image job_image
    service_image=$(gcloud run services describe "${SERVICE_NAME}" \
        --region="${REGION}" --project="${PROJECT_ID}" \
        --format='value(spec.template.spec.containers[0].image)' 2>/dev/null || echo "")
    job_image=$(gcloud run jobs describe "${WORKER_JOB_NAME}" \
        --region="${REGION}" --project="${PROJECT_ID}" \
        --format='value(spec.template.spec.template.spec.containers[0].image)' 2>/dev/null || echo "")

    print_info "Service image: ${service_image:-unknown}"
    print_info "Job image:     ${job_image:-unknown}"
    if [ -n "${service_image}" ] && [ -n "${job_image}" ] && [ "${service_image}" != "${job_image}" ]; then
        print_error "The Service and the worker Job run different images"
        exit 1
    fi

    if [ -z "${SERVICE_URL}" ]; then
        print_warning "Could not retrieve service URL for health check"
        return 0
    fi

    print_info "Testing health endpoint at ${SERVICE_URL}/"
    sleep 5
    HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${SERVICE_URL}/" || echo "000")
    if [ "${HTTP_STATUS}" == "200" ]; then
        print_info "Health check passed (HTTP ${HTTP_STATUS})"
    else
        print_warning "Health check returned HTTP ${HTTP_STATUS}"
        print_info "The service may still be starting up. Check logs with:"
        print_info "  gcloud run services logs read ${SERVICE_NAME} --project=${PROJECT_ID} --region=${REGION}"
    fi
}

main() {
    parse_args "$@"
    resolve_tag

    print_info "Project:    ${PROJECT_ID} (${REGION})"
    print_info "Service:    ${SERVICE_NAME} (${SERVICE_CPU} vCPU / ${SERVICE_MEMORY}, no GPU) as ${API_SERVICE_ACCOUNT}"
    print_info "Worker Job: ${WORKER_JOB_NAME} (${WORKER_CPU} vCPU / ${WORKER_MEMORY} + ${GPU_COUNT}x ${GPU_TYPE}) as ${WORKER_SERVICE_ACCOUNT}"
    print_info "Image:      ${IMAGE_REF}"

    if [ "${ASSUME_YES}" != "true" ]; then
        read -p "$(echo -e "${YELLOW}Continue with deployment? [y/N]: ${NC}")" -n 1 -r
        echo ""
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            print_info "Deployment cancelled"
            exit 0
        fi
    fi

    check_prerequisites
    if [ "${SKIP_BUILD}" == "true" ]; then
        if ! image_exists "${IMAGE_REF}"; then
            print_error "${IMAGE_REF} does not exist in Artifact Registry"
            exit 1
        fi
        print_warning "Skipping image build; deploying the existing ${IMAGE_REF}"
    else
        build_and_push
    fi
    deploy_to_cloud_run
    deploy_worker_job
    verify_deployment

    echo ""
    print_info "Deployed tag: ${IMAGE_TAG}"
    print_info "Roll back with: infra/scripts/rollback.sh <previous tag>   (list tags: infra/scripts/rollback.sh --list)"
}

main "$@"
