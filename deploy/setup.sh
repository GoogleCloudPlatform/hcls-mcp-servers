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
# First-time setup: enables GCP APIs, creates Artifact Registry repo,
# creates GCS bucket for Terraform state, connects GitHub repo,
# and creates a Cloud Build trigger for automatic deploys on push.
#
# Usage:
#   cd deploy
#   chmod +x setup.sh
#   ./setup.sh <PROJECT_ID> <GITHUB_OWNER/REPO> [REGION]
#
# Example:
#   ./setup.sh my-gcp-project my-github-org/my-mcp-repo us-central1
#
# Prerequisites:
#   - gcloud CLI authenticated (gcloud auth login)
#   - GitHub repo connected to Cloud Build (see README)

set -euo pipefail

PROJECT_ID="${1:?Usage: ./setup.sh <PROJECT_ID> <GITHUB_OWNER/REPO> [REGION]}"
GITHUB_REPO="${2:?Usage: ./setup.sh <PROJECT_ID> <GITHUB_OWNER/REPO> [REGION]}"
REGION="${3:-us-central1}"
REPO_NAME="healthcare-mcp"
TF_BUCKET="${PROJECT_ID}-tf-state"
TRIGGER_NAME="healthcare-mcp-deploy"
# Auto-detect the current user's email to grant local access via IAP
CURRENT_USER=$(gcloud config get-value account 2>/dev/null || echo "")
DEVELOPER_EMAILS="[]"
if [[ "$CURRENT_USER" == *"@"* ]]; then
  # Ensure the list string does not have outer single quotes when passed to substitutions
  DEVELOPER_EMAILS="[\"${CURRENT_USER}\"]"
fi

echo "============================================"
echo " Healthcare MCP Servers – First-Time Setup"
echo "============================================"
echo ""
echo " Project:     $PROJECT_ID"
echo " Region:      $REGION"
echo " GitHub repo: $GITHUB_REPO"
echo " AR repo:     $REPO_NAME"
echo " TF bucket:   $TF_BUCKET"
echo " Dev Access:  $DEVELOPER_EMAILS"
echo ""

# --------------------------------------------------
# 1. Set project and enable required APIs
# --------------------------------------------------
echo ">> Setting project and enabling APIs..."
gcloud config set project "$PROJECT_ID"

gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  storage.googleapis.com \
  cloudresourcemanager.googleapis.com \
  iam.googleapis.com \
  iap.googleapis.com \
  --quiet

echo "   APIs enabled."

# --------------------------------------------------
# 2. Create Artifact Registry repo (if not exists)
# --------------------------------------------------
echo ">> Creating Artifact Registry repo..."
gcloud artifacts repositories describe "$REPO_NAME" \
  --location="$REGION" --quiet 2>/dev/null || \
gcloud artifacts repositories create "$REPO_NAME" \
  --repository-format=docker \
  --location="$REGION" \
  --description="Docker images for Healthcare MCP servers" \
  --quiet

echo "   Repo ready: ${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}"

# --------------------------------------------------
# 3. Create GCS bucket for Terraform state
# --------------------------------------------------
echo ">> Creating Terraform state bucket..."
gcloud storage buckets describe "gs://${TF_BUCKET}" --quiet 2>/dev/null || \
gcloud storage buckets create "gs://${TF_BUCKET}" \
  --location="$REGION" \
  --uniform-bucket-level-access \
  --quiet

echo "   State bucket ready: gs://${TF_BUCKET}"

# --------------------------------------------------
# 4. Grant Cloud Build the necessary IAM roles
# --------------------------------------------------
echo ">> Granting Cloud Build service account permissions..."
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
CB_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

for ROLE in roles/run.admin roles/iam.serviceAccountUser roles/storage.admin roles/artifactregistry.writer roles/iam.serviceAccountAdmin roles/iam.securityAdmin; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${CB_SA}" \
    --role="$ROLE" \
    --condition=None \
    --quiet > /dev/null
done

echo "   Permissions granted to ${CB_SA}"

# --------------------------------------------------
# 5. Create Cloud Build trigger (GitHub push to main)
# --------------------------------------------------
echo ">> Creating Cloud Build trigger..."
OWNER=$(echo "$GITHUB_REPO" | cut -d'/' -f1)
REPO=$(echo "$GITHUB_REPO" | cut -d'/' -f2)

# Delete existing trigger if present
gcloud builds triggers describe "$TRIGGER_NAME" --region=global --quiet 2>/dev/null && \
  gcloud builds triggers delete "$TRIGGER_NAME" --region=global --quiet 2>/dev/null

gcloud builds triggers create github \
  --name="$TRIGGER_NAME" \
  --repo-owner="$OWNER" \
  --repo-name="$REPO" \
  --branch-pattern="^main$" \
  --build-config="deploy/cloudbuild.yaml" \
  --substitutions="_REGION=${REGION},_REPO_NAME=${REPO_NAME},_DEVELOPER_EMAILS=${DEVELOPER_EMAILS}" \
  --service-account="projects/${PROJECT_ID}/serviceAccounts/${CB_SA}" \
  --region=global \
  --quiet

echo "   Trigger created: pushes to main will auto-deploy."

# --------------------------------------------------
# 6. Run initial build + deploy
# --------------------------------------------------
echo ">> Running initial build and deploy..."
cd "$(dirname "$0")/.."  # Go to repo root

gcloud builds submit \
  --config=deploy/cloudbuild.yaml \
  --substitutions="_REGION=${REGION},_REPO_NAME=${REPO_NAME},_DEVELOPER_EMAILS=${DEVELOPER_EMAILS}" \
  --quiet

echo ""
echo "============================================"
echo " Setup complete!"
echo "============================================"
echo ""
echo "What happens now:"
echo "  - Every push to main auto-builds and deploys all servers"
echo "  - Cloud Build builds Docker images → Artifact Registry"
echo "  - Terraform deploys/updates Cloud Run services"
echo ""
echo "To check service URLs:"
echo "  gcloud run services list --region=${REGION} --format='table(SERVICE,URL)'"
echo ""
echo "To manually trigger a build:"
echo "  gcloud builds triggers run ${TRIGGER_NAME} --branch=main --region=global"
echo ""
echo "To verify your deployment:"
echo "  pip install -r tests/requirements.txt"
echo "  pytest tests/smoke_test.py -v --cloud --project=${PROJECT_ID}"
