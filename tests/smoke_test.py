# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Smoke tests for Healthcare MCP Servers.

Two modes:
  Local:  pytest tests/smoke_test.py -v
  Cloud:  pytest tests/smoke_test.py -v --cloud --project=PROJECT_ID

Local mode starts each server process, runs tests, and stops it.
Cloud mode tests deployed Cloud Run services using gcloud for auth.
"""

import json
import os
import signal
import subprocess
import time

import httpx
import pytest

# ---------------------------------------------------------------------------
# Server definitions
# ---------------------------------------------------------------------------

SERVERS = [
    {
        "name": "rxnorm-mcp",
        "dir": "rxnorm_mcp",
        "tool": "normalize_drug",
        "args": {"name": "aspirin"},
    },
    {
        "name": "clinical-trials-mcp",
        "dir": "clinical_trials_mcp",
        "tool": "search_trials",
        "args": {"condition": "asthma", "page_size": 1},
    },
    {
        "name": "pubmed-mcp",
        "dir": "pubmed_mcp",
        "tool": "search_pubmed",
        "args": {"query": "influenza", "max_results": 1},
    },
    {
        "name": "fda-safety-mcp",
        "dir": "fda_safety_mcp",
        "tool": "search_adverse_events",
        "args": {"drug_name": "aspirin", "limit": 1},
    },
    {
        "name": "drug-data-mcp",
        "dir": "drug_data_mcp",
        "tool": "get_nadac_price",
        "args": {"drug_name": "metformin", "limit": 1},
    },
    {
        "name": "umls-mcp",
        "dir": "umls_mcp",
        "tool": "search_concepts",
        "args": {"term": "diabetes"},
        "requires_env": "UMLS_API_KEY",
    },
    {
        "name": "icd10-mcp",
        "dir": "icd10_mcp",
        "tool": "search_codes",
        "args": {"query": "diabetes", "max_results": 1},
        "requires_data": True,
    },
    {
        "name": "npi-mcp",
        "dir": "npi_mcp",
        "tool": "npi_search",
        "args": {"last_name": "Smith", "state": "CA", "limit": 1},
    },
    {
        "name": "cms-coverage-mcp",
        "dir": "cms_coverage_mcp",
        "tool": "search_ncd",
        "args": {"keyword": "diabetes", "page_size": 1},
    },
    {
        "name": "medlineplus-mcp",
        "dir": "medlineplus_mcp",
        "tool": "search_health_topics",
        "args": {"term": "diabetes", "max_results": 1},
    },
]

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MCP_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


# ---------------------------------------------------------------------------
# Pytest fixtures (options registered in conftest.py)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def cloud_mode(request):
    return request.config.getoption("--cloud")


@pytest.fixture(scope="session")
def cloud_services(request):
    """Discover deployed Cloud Run service URLs via gcloud."""
    if not request.config.getoption("--cloud"):
        return {}

    project = request.config.getoption("--project")
    region = request.config.getoption("--region")
    if not project:
        pytest.fail("--project is required with --cloud")

    result = subprocess.run(
        ["gcloud", "run", "services", "list",
         f"--project={project}", f"--region={region}",
         "--format=json"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        pytest.fail(f"gcloud run services list failed: {result.stderr}")

    services = {}
    for svc in json.loads(result.stdout):
        name = svc["metadata"]["name"]
        url = svc["status"]["url"]
        services[name] = url

    return services


def _get_cloud_token(service_url):
    """Mint an identity token for a Cloud Run service (GCP pattern)."""
    result = subprocess.run(
        ["gcloud", "auth", "print-identity-token", f"--audiences={service_url}"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        # Fallback for user credentials (not service accounts)
        result = subprocess.run(
            ["gcloud", "auth", "print-identity-token"],
            capture_output=True, text=True,
        )
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# Local server management
# ---------------------------------------------------------------------------

def _start_local_server(server, port):
    """Start a local MCP server and wait for health check."""
    server_dir = os.path.join(REPO_ROOT, server["dir"])

    if server.get("node"):
        # TypeScript server
        dist = os.path.join(server_dir, "dist", "index.js")
        if not os.path.exists(dist):
            return None  # Not built
        env = {
            **os.environ,
            "PORT": str(port),
            "TRANSPORT": "http",
            "EHR_FHIR_BASE_URL": "https://hapi.fhir.org/baseR4",
            "EHR_FHIR_VENDOR": "generic_fhir",
            "EHR_FHIR_AUTH_METHOD": "bearer_token",
            "EHR_FHIR_TOKEN": "none",
        }
        proc = subprocess.Popen(
            ["node", dist],
            cwd=server_dir, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    else:
        # Python server
        env = {**os.environ, "PORT": str(port)}
        if server["dir"] == "icd10_mcp":
            data_dir = os.environ.get("ICD10_DATA_DIR", os.path.join(server_dir, "data"))
            if not os.path.isdir(data_dir):
                return None  # Data not downloaded
            env["ICD10_DATA_DIR"] = data_dir
        proc = subprocess.Popen(
            ["python", "server.py"],
            cwd=server_dir, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    # Wait for health check
    url = f"http://localhost:{port}/health"
    for _ in range(30):
        try:
            resp = httpx.get(url, timeout=2.0)
            if resp.status_code == 200:
                return proc
        except httpx.ConnectError:
            pass
        time.sleep(0.5)

    proc.kill()
    return None


def _stop_server(proc):
    """Stop a local server process."""
    if proc is None:
        return
    try:
        os.kill(proc.pid, signal.SIGTERM)
        proc.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        proc.kill()


# ---------------------------------------------------------------------------
# MCP protocol helpers
# ---------------------------------------------------------------------------

def _mcp_request(base_url, method, params=None, headers=None):
    """Send a JSON-RPC request to an MCP endpoint."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
    }
    if params is not None:
        payload["params"] = params

    h = {**MCP_HEADERS, **(headers or {})}
    resp = httpx.post(f"{base_url}/mcp", json=payload, headers=h, timeout=30.0)
    return resp


def _mcp_initialize(base_url, headers=None):
    """Perform MCP initialize handshake."""
    return _mcp_request(base_url, "initialize", {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "smoke-test", "version": "1.0"},
    }, headers)


def _mcp_tool_call(base_url, tool_name, arguments, headers=None):
    """Call an MCP tool."""
    return _mcp_request(base_url, "tools/call", {
        "name": tool_name,
        "arguments": arguments,
    }, headers)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(params=[s["name"] for s in SERVERS], scope="module")
def server_under_test(request, cloud_mode, cloud_services):
    """Fixture that provides a running server URL for each MCP server."""
    server_name = request.param
    server = next(s for s in SERVERS if s["name"] == server_name)

    if cloud_mode:
        # Cloud mode: use discovered service URL
        base_url = None
        # First try an exact match
        if server_name in cloud_services:
            base_url = cloud_services[server_name]
        else:
            # Fallback to matching prefix (e.g., if only 'rxnorm-mcp-public' exists)
            for name, url in cloud_services.items():
                if name.startswith(server_name):
                    base_url = url
                    break
        if not base_url:
            pytest.skip(f"{server_name} not deployed")
        token = _get_cloud_token(base_url)
        headers = {"Authorization": f"Bearer {token}"}
        yield {"server": server, "url": base_url, "headers": headers}
    else:
        # Local mode: start server process
        port = 8090 + [s["name"] for s in SERVERS].index(server_name)
        proc = _start_local_server(server, port)
        if proc is None:
            skip_reason = "Node.js build required" if server.get("node") else "data files required"
            pytest.skip(f"{server_name}: {skip_reason}")
        try:
            yield {"server": server, "url": f"http://localhost:{port}", "headers": {}}
        finally:
            _stop_server(proc)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestHealthCheck:
    def test_health_returns_200(self, server_under_test):
        url = server_under_test["url"]
        headers = server_under_test["headers"]
        resp = httpx.get(f"{url}/health", headers=headers, timeout=10.0)
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("status") in ("ok", "healthy")


class TestMCPHandshake:
    def test_initialize_returns_server_info(self, server_under_test):
        url = server_under_test["url"]
        headers = server_under_test["headers"]
        resp = _mcp_initialize(url, headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "result" in data
        assert "serverInfo" in data["result"]
        assert "capabilities" in data["result"]


class TestToolCall:
    def test_tool_returns_content(self, server_under_test):
        server = server_under_test["server"]
        url = server_under_test["url"]
        headers = server_under_test["headers"]

        # Check if this server needs an API key
        required_env = server.get("requires_env")
        if required_env and not os.environ.get(required_env):
            pytest.skip(f"Set {required_env} env var to test {server['name']} tool calls")

        resp = _mcp_tool_call(url, server["tool"], server["args"], headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "result" in data, f"Expected 'result' in response, got: {data}"
        result = data["result"]
        assert "content" in result
        assert len(result["content"]) > 0
        assert result.get("isError") is not True, f"Tool returned error: {result['content']}"
