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
# Manually trigger a rebuild + redeploy of all servers.
# Normally this happens automatically on push to main.
#
# Usage:
#   cd deploy
#   ./redeploy.sh [PROJECT_ID] [REGION]

set -euo pipefail

PROJECT_ID="${1:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${2:-us-central1}"
REPO_NAME="healthcare-mcp"
TRIGGER_NAME="healthcare-mcp-deploy"

echo ">> Triggering build for project: $PROJECT_ID"

# Option 1: Trigger via the GitHub trigger (uses latest commit on main)
gcloud builds triggers run "$TRIGGER_NAME" \
  --branch=main \
  --region=global \
  --project="$PROJECT_ID" \
  2>/dev/null && {
    echo "   Build triggered. Monitor at:"
    echo "   https://console.cloud.google.com/cloud-build/builds?project=$PROJECT_ID"
    exit 0
  }

# Option 2: Fallback to manual submit if trigger doesn't exist
echo "   Trigger not found. Running manual build..."
cd "$(dirname "$0")/.."  # Go to repo root

gcloud builds submit \
  --config=deploy/cloudbuild.yaml \
  --substitutions="_REGION=${REGION},_REPO_NAME=${REPO_NAME}" \
  --project="$PROJECT_ID"

echo ">> Redeployment complete."
