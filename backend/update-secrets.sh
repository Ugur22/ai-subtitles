#!/bin/bash

###############################################################################
# AI-Subs Backend - Update Secrets Configuration
###############################################################################
# This script updates the Cloud Run service to use Secret Manager for
# sensitive values instead of plain environment variables.
#
# Usage: ./update-secrets.sh
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

print_warning() {
    echo -e "${YELLOW}Warning: $1${NC}"
}

echo ""
print_info "╔═══════════════════════════════════════════════════════════╗"
print_info "║      AI-Subs Backend - Update Secrets Configuration      ║"
print_info "╚═══════════════════════════════════════════════════════════╝"
echo ""

print_info "This will update the service to use Secret Manager for:"
print_info "  - SUPABASE_SERVICE_KEY"
print_info "  - APP_PASSWORD_HASH"
print_info "  - HUGGINGFACE_TOKEN"
echo ""

# Confirm update
read -p "$(echo -e ${YELLOW}Continue with update? [y/N]: ${NC})" -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    print_info "Update cancelled"
    exit 0
fi

print_step "Updating Cloud Run service configuration..."

# Update the service with secrets
# First, remove the plain-text env vars
gcloud run services update "${SERVICE_NAME}" \
    --platform=managed \
    --region="${REGION}" \
    --project="${PROJECT_ID}" \
    --remove-env-vars="APP_PASSWORD_HASH,SUPABASE_SERVICE_KEY"

# Then, set the secrets
gcloud run services update "${SERVICE_NAME}" \
    --platform=managed \
    --region="${REGION}" \
    --project="${PROJECT_ID}" \
    --update-secrets="SUPABASE_SERVICE_KEY=supabase-service-key:latest,APP_PASSWORD_HASH=app-password-hash:latest,HUGGINGFACE_TOKEN=huggingface-token:latest"

print_step "Verifying configuration..."

# Get service URL
SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" \
    --platform=managed \
    --region="${REGION}" \
    --project="${PROJECT_ID}" \
    --format='value(status.url)')

print_info "Service URL: ${SERVICE_URL}"

# Wait a moment for the service to update
sleep 5

# Test health endpoint
print_step "Testing health endpoint..."
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${SERVICE_URL}/" || echo "000")

if [ "${HTTP_STATUS}" == "200" ]; then
    print_info "Health check passed (HTTP ${HTTP_STATUS})"
else
    print_warning "Health check returned HTTP ${HTTP_STATUS}"
fi

echo ""
print_info "╔═══════════════════════════════════════════════════════════╗"
print_info "║         Secrets configuration updated successfully!      ║"
print_info "╚═══════════════════════════════════════════════════════════╝"
echo ""

print_info "Secrets are now managed via Secret Manager:"
print_info "  ✓ SUPABASE_SERVICE_KEY -> supabase-service-key:latest"
print_info "  ✓ APP_PASSWORD_HASH -> app-password-hash:latest"
print_info "  ✓ HUGGINGFACE_TOKEN -> huggingface-token:latest"
echo ""
