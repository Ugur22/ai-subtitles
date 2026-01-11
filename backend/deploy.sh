#!/bin/bash

###############################################################################
# AI-Subs Backend - Cloud Run Deployment Script
###############################################################################
# This script builds and deploys the AI-Subs backend to Google Cloud Run
# with proper environment configuration and secret management.
#
# Usage: ./deploy.sh
#
# Requirements:
# - gcloud CLI installed and configured
# - Proper GCP permissions for Cloud Run and Secret Manager
# - Docker (for local builds, optional if using Cloud Build)
###############################################################################

set -e  # Exit on error
set -u  # Exit on undefined variable

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
PROJECT_ID="ai-subs-poc"
REGION="us-central1"
SERVICE_NAME="ai-subs-backend"
IMAGE_NAME="us-central1-docker.pkg.dev/ai-subs-poc/ai-subs-repo/ai-subs-backend:latest"
SERVICE_ACCOUNT="1052285886390-compute@developer.gserviceaccount.com"

# Resource limits (GPU requires minimum 4 CPU and 16Gi memory)
MEMORY="16Gi"
CPU="4"
TIMEOUT="300"
MIN_INSTANCES="0"
MAX_INSTANCES="1"  # Set to 1 for GPU quota (10 units per instance, request more quota for 3)
PORT="8000"

# GPU configuration
GPU_COUNT="1"
GPU_TYPE="nvidia-l4"
GPU_ZONAL_REDUNDANCY="false"  # Requires less quota (10 vs 30 per instance)

# Environment variables (non-sensitive)
CORS_ORIGINS='["https://ai-subs.netlify.app"]'
ENABLE_GCS_UPLOADS="true"
GCS_BUCKET_NAME="ai-subs-uploads"
SUPABASE_URL="https://ngfcjdxfhppnzpocgktw.supabase.co"
XAI_MODEL="grok-4-1-fast-reasoning"
ENVIRONMENT="production"

# Speaker diarization settings
MIN_SPEAKERS="1"
MAX_SPEAKERS="0"  # 0 = unlimited/auto-detect speakers

# Ensure PATH includes gcloud
export PATH="/opt/homebrew/share/google-cloud-sdk/bin:/usr/bin:/bin:/usr/local/bin:$PATH"

# Helper functions
print_step() {
    echo -e "${BLUE}==>${NC} ${GREEN}$1${NC}"
}

print_error() {
    echo -e "${RED}Error: $1${NC}" >&2
}

print_warning() {
    echo -e "${YELLOW}Warning: $1${NC}"
}

print_info() {
    echo -e "${BLUE}$1${NC}"
}

# Check prerequisites
check_prerequisites() {
    print_step "Checking prerequisites..."

    # Check if gcloud is installed
    if ! command -v gcloud &> /dev/null; then
        print_error "gcloud CLI is not installed. Please install it from https://cloud.google.com/sdk/docs/install"
        exit 1
    fi

    # Check if authenticated
    if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" &> /dev/null; then
        print_error "Not authenticated with gcloud. Please run: gcloud auth login"
        exit 1
    fi

    print_info "Prerequisites check passed"
}

# Build and push Docker image
build_and_push() {
    print_step "Building and pushing Docker image..."

    cd "$(dirname "$0")"

    # Use Cloud Build for building (handles large images better)
    print_info "Using Cloud Build to build and push image..."
    if gcloud builds submit \
        --config=cloudbuild.yaml \
        --project="${PROJECT_ID}"; then
        print_info "Docker image built and pushed successfully"
    else
        print_error "Failed to build and push Docker image"
        exit 1
    fi
}

# Deploy to Cloud Run
deploy_to_cloud_run() {
    print_step "Deploying to Cloud Run..."

    # Deploy with all configurations (GPU-enabled)
    if gcloud run deploy "${SERVICE_NAME}" \
        --image="${IMAGE_NAME}" \
        --platform=managed \
        --region="${REGION}" \
        --project="${PROJECT_ID}" \
        --service-account="${SERVICE_ACCOUNT}" \
        --memory="${MEMORY}" \
        --cpu="${CPU}" \
        --gpu="${GPU_COUNT}" \
        --gpu-type="${GPU_TYPE}" \
        --no-gpu-zonal-redundancy \
        --timeout="${TIMEOUT}" \
        --min-instances="${MIN_INSTANCES}" \
        --max-instances="${MAX_INSTANCES}" \
        --port="${PORT}" \
        --allow-unauthenticated \
        --set-env-vars="CORS_ORIGINS=${CORS_ORIGINS},ENABLE_GCS_UPLOADS=${ENABLE_GCS_UPLOADS},GCS_BUCKET_NAME=${GCS_BUCKET_NAME},SUPABASE_URL=${SUPABASE_URL},XAI_MODEL=${XAI_MODEL},ENVIRONMENT=${ENVIRONMENT},MIN_SPEAKERS=${MIN_SPEAKERS},MAX_SPEAKERS=${MAX_SPEAKERS}" \
        --set-secrets="SUPABASE_SERVICE_KEY=supabase-service-key:latest,APP_PASSWORD_HASH=app-password-hash:latest,HUGGINGFACE_TOKEN=huggingface-token:latest,GROQ_API_KEY=groq-api-key:latest,XAI_API_KEY=xai-api-key:latest"; then
        print_info "Deployment successful"
    else
        print_error "Deployment failed"
        exit 1
    fi
}

# Get service URL
get_service_url() {
    print_step "Getting service URL..."

    SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" \
        --platform=managed \
        --region="${REGION}" \
        --project="${PROJECT_ID}" \
        --format='value(status.url)')

    if [ -n "${SERVICE_URL}" ]; then
        print_info "Service URL: ${SERVICE_URL}"
        print_info "API Docs: ${SERVICE_URL}/docs"
    else
        print_warning "Could not retrieve service URL"
    fi
}

# Verify deployment
verify_deployment() {
    print_step "Verifying deployment..."

    # Get service URL
    SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" \
        --platform=managed \
        --region="${REGION}" \
        --project="${PROJECT_ID}" \
        --format='value(status.url)' 2>/dev/null || echo "")

    if [ -z "${SERVICE_URL}" ]; then
        print_warning "Could not retrieve service URL for health check"
        return 0
    fi

    print_info "Testing health endpoint at ${SERVICE_URL}/"

    # Wait a few seconds for the service to be ready
    sleep 5

    # Test health endpoint
    HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${SERVICE_URL}/" || echo "000")

    if [ "${HTTP_STATUS}" == "200" ]; then
        print_info "Health check passed (HTTP ${HTTP_STATUS})"
        return 0
    else
        print_warning "Health check returned HTTP ${HTTP_STATUS}"
        print_info "The service may still be starting up. Check logs with:"
        print_info "  gcloud run logs read ${SERVICE_NAME} --project=${PROJECT_ID} --region=${REGION}"
        return 0
    fi
}

# Main execution
main() {
    echo ""
    print_info "╔═══════════════════════════════════════════════════════════╗"
    print_info "║         AI-Subs Backend - Cloud Run Deployment           ║"
    print_info "╚═══════════════════════════════════════════════════════════╝"
    echo ""

    print_info "Project: ${PROJECT_ID}"
    print_info "Region: ${REGION}"
    print_info "Service: ${SERVICE_NAME}"
    print_info "Image: ${IMAGE_NAME}"
    print_info "GPU: ${GPU_COUNT}x ${GPU_TYPE}"
    print_info "Resources: ${CPU} vCPU, ${MEMORY} memory"
    echo ""

    # Confirm deployment
    read -p "$(echo -e ${YELLOW}Continue with deployment? [y/N]: ${NC})" -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_info "Deployment cancelled"
        exit 0
    fi

    # Run deployment steps
    check_prerequisites
    build_and_push
    deploy_to_cloud_run
    get_service_url
    verify_deployment

    echo ""
    print_info "╔═══════════════════════════════════════════════════════════╗"
    print_info "║              Deployment completed successfully!          ║"
    print_info "╚═══════════════════════════════════════════════════════════╝"
    echo ""

    if [ -n "${SERVICE_URL}" ]; then
        print_info "Next steps:"
        print_info "  1. Visit ${SERVICE_URL}/docs to view the API documentation"
        print_info "  2. Update your frontend CORS_ORIGINS if needed"
        print_info "  3. Monitor logs: gcloud run logs read ${SERVICE_NAME} --project=${PROJECT_ID} --region=${REGION} --limit=50 --tail"
        echo ""
    fi
}

# Run main function
main "$@"
