#!/usr/bin/env bash
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# Tear down all GCP resources created by setup.sh.
# Deletes Cloud Run services, Artifact Registry images, Terraform state,
# IAM bindings, and the Cloud Build trigger.
#
# Usage:
#   cd deploy
#   ./teardown.sh <PROJECT_ID> [REGION]
#
# Example:
#   ./teardown.sh my-gcp-project us-central1

set -euo pipefail

PROJECT_ID="${1:?Usage: ./teardown.sh <PROJECT_ID> [REGION]}"
REGION="${2:-us-central1}"
REPO_NAME="healthcare-mcp"
TF_BUCKET="${PROJECT_ID}-tf-state"
TRIGGER_NAME="healthcare-mcp-deploy"

echo "============================================"
echo " Healthcare MCP Servers – Teardown"
echo "============================================"
echo ""
echo " Project:   $PROJECT_ID"
echo " Region:    $REGION"
echo ""
read -p " This will DELETE all deployed MCP servers and infrastructure. Continue? (y/N) " confirm
if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
    echo "Aborted."
    exit 0
fi

echo ""

# --------------------------------------------------
# 1. Delete Cloud Run services
# --------------------------------------------------
echo ">> Deleting Cloud Run services..."
SERVICES=$(gcloud run services list --region="$REGION" --project="$PROJECT_ID" --format='value(SERVICE)' 2>/dev/null || true)

for SVC in $SERVICES; do
    case "$SVC" in
        *-mcp|*-mcp-public|*-mcp-private)
            echo "   Deleting $SVC..."
            gcloud run services delete "$SVC" --region="$REGION" --project="$PROJECT_ID" --quiet 2>/dev/null || true
            ;;
    esac
done

echo "   Cloud Run services deleted."

# --------------------------------------------------
# 2. Delete Artifact Registry images and repo
# --------------------------------------------------
echo ">> Deleting Artifact Registry repo..."
gcloud artifacts repositories delete "$REPO_NAME" \
    --location="$REGION" --project="$PROJECT_ID" --quiet 2>/dev/null || true

echo "   Artifact Registry repo deleted."

# --------------------------------------------------
# 3. Delete Cloud Build trigger
# --------------------------------------------------
echo ">> Deleting Cloud Build trigger..."
gcloud builds triggers delete "$TRIGGER_NAME" \
    --region=global --project="$PROJECT_ID" --quiet 2>/dev/null || true

echo "   Cloud Build trigger deleted."

# --------------------------------------------------
# 4. Delete service account
# --------------------------------------------------
echo ">> Deleting Gemini Enterprise service account..."
gcloud iam service-accounts delete "gemini-mcp-sa@${PROJECT_ID}.iam.gserviceaccount.com" \
    --project="$PROJECT_ID" --quiet 2>/dev/null || true

echo "   Service account deleted."

# --------------------------------------------------
# 5. Delete Terraform state bucket
# --------------------------------------------------
echo ">> Deleting Terraform state bucket..."
gcloud storage rm -r "gs://${TF_BUCKET}" --project="$PROJECT_ID" --quiet 2>/dev/null || true

echo "   Terraform state bucket deleted."

echo ""
echo "============================================"
echo " Teardown complete."
echo "============================================"
echo ""
echo "The following were removed:"
echo "  - All Healthcare MCP Cloud Run services"
echo "  - Artifact Registry repo: $REPO_NAME"
echo "  - Cloud Build trigger: $TRIGGER_NAME"
echo "  - Service account: gemini-mcp-sa"
echo "  - Terraform state bucket: gs://$TF_BUCKET"
echo ""
echo "Note: IAM role bindings for the Cloud Build SA were NOT removed."
echo "To fully clean up, remove roles from ${PROJECT_ID}-compute SA manually."
