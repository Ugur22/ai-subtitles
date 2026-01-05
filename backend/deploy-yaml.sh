#!/bin/bash

###############################################################################
# AI-Subs Backend - Cloud Run YAML Deployment Script
###############################################################################
# This script deploys the AI-Subs backend using the declarative YAML config
#
# Usage: ./deploy-yaml.sh
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
YAML_FILE="cloudrun-service.yaml"

# Ensure PATH includes gcloud
export PATH="/opt/homebrew/share/google-cloud-sdk/bin:/usr/bin:/bin:/usr/local/bin:$PATH"

# Helper functions
print_step() {
    echo -e "${BLUE}==>${NC} ${GREEN}$1${NC}"
}

print_error() {
    echo -e "${RED}Error: $1${NC}" >&2
}

print_info() {
    echo -e "${BLUE}$1${NC}"
}

# Check if YAML file exists
if [ ! -f "${YAML_FILE}" ]; then
    print_error "YAML file not found: ${YAML_FILE}"
    exit 1
fi

print_step "Deploying using YAML configuration..."

# Deploy using gcloud run services replace
gcloud run services replace "${YAML_FILE}" \
    --region="${REGION}" \
    --project="${PROJECT_ID}"

print_step "Getting service URL..."

SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" \
    --platform=managed \
    --region="${REGION}" \
    --project="${PROJECT_ID}" \
    --format='value(status.url)')

print_info "Service URL: ${SERVICE_URL}"
print_info "API Docs: ${SERVICE_URL}/docs"

echo ""
print_info "Deployment completed successfully!"
