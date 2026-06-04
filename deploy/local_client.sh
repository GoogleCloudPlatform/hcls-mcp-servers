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
# A helper script to fetch an IAP identity token and inject it into an MCP SSE request.
# Useful for local testing with tools like Gemini CLI.
#
# Usage:
#   ./deploy/local_client.sh <CLOUD_RUN_URL>

set -euo pipefail

URL="${1:?Usage: ./local_client.sh <CLOUD_RUN_URL>}"

# Fetch the short-lived OIDC token using your gcloud identity
TOKEN=$(gcloud auth print-identity-token)

if [[ -z "$TOKEN" ]]; then
  echo "Error: Failed to fetch identity token. Try running 'gcloud auth login'." >&2
  exit 1
fi

echo "Got token for IAP/Cloud Run authentication." >&2
echo "Depending on your MCP client, you can use the token like this:" >&2
echo "" >&2
echo "Header: Authorization: Bearer $TOKEN" >&2
echo "" >&2
echo "Example using curl:" >&2
echo "  curl -H \"Authorization: Bearer $TOKEN\" $URL" >&2
echo "" >&2

# If you have an MCP CLI installed (e.g., npx @modelcontextprotocol/inspector), you can run it:
# npx @modelcontextprotocol/inspector sse $URL --header "Authorization: Bearer $TOKEN"

# Note for Gemini CLI users:
# If Gemini CLI does not natively support dynamic OIDC headers for remote SSE endpoints,
# you should continue to use the local stdio approach for testing:
#   cd rxnorm_mcp && python server.py
