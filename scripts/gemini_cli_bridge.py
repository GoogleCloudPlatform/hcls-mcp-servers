#!/usr/bin/env python3
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
DEPRECATION NOTICE: 
This script is a temporary workaround to bridge the Gemini CLI (which requires stdio)
to remote IAM-secured Cloud Run MCP servers (which use SSE).
It will be removed once the Gemini CLI natively supports remote OIDC endpoints.
"""

import sys
import asyncio
import argparse
import logging
import signal
import google.auth
from google.auth.exceptions import DefaultCredentialsError
from google.auth.transport.requests import Request
from google.oauth2 import id_token
from mcp.client.sse import sse_client
from pydantic import TypeAdapter
from mcp.types import JSONRPCMessage

# Configure logging to stderr so it doesn't pollute stdout (which is used for JSON-RPC)
logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s: %(message)s")

message_adapter = TypeAdapter(JSONRPCMessage)

import json
import os
import time

CACHE_FILE = os.path.expanduser("~/.gemini/mcp/.oidc_token_cache")

def get_cached_token():
    if not os.path.exists(CACHE_FILE):
        return None
    try:
        with open(CACHE_FILE, "r") as f:
            data = json.load(f)
            # Check if token is older than 50 minutes (3000 seconds)
            if time.time() - data.get("timestamp", 0) < 3000:
                return data.get("token")
    except Exception:
        pass
    return None

def save_cached_token(token):
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        with open(CACHE_FILE, "w") as f:
            json.dump({"token": token, "timestamp": time.time()}, f)
    except Exception:
        pass

async def run_bridge(target_url: str):
    try:
        # 1. Fetch GCP OIDC Token
        logging.info(f"Fetching OIDC token for {target_url}...")
        try:
            credentials, project = google.auth.default()
        except DefaultCredentialsError:
            logging.error("Failed to find Google default credentials.")
            logging.error("Please run: gcloud auth application-default login")
            sys.exit(1)
            
        auth_req = Request()
        
        # Cloud Run audience is the URL without the trailing path
        audience = target_url.replace("/mcp", "").rstrip("/")
        
        token = get_cached_token()
        if not token:
            logging.info("Token cache miss. Fetching new token...")
            import subprocess
            try:
                # Fetch user-level identity token directly
                result = subprocess.run(
                    ["gcloud", "auth", "print-identity-token"],
                    capture_output=True, text=True, check=True
                )
                token = result.stdout.strip()
                save_cached_token(token)
            except Exception as e:
                logging.error(f"Failed to fetch user OIDC token via gcloud: {e}")
                sys.exit(1)
        else:
            logging.info("Using cached token.")
            
        headers = {"Authorization": f"Bearer {token}"}

        # 2. Bridge the transports
        logging.info("Connecting to remote SSE endpoint...")
        
        async with sse_client(target_url, headers=headers) as (read_stream, write_stream):
            logging.info("Connection established. Piping stdio...")
            
            # Helper to pipe stdin to remote write_stream
            async def pipe_stdin_to_remote():
                loop = asyncio.get_event_loop()
                while True:
                    # Read from stdin asynchronously
                    line = await loop.run_in_executor(None, sys.stdin.buffer.readline)
                    if not line:
                        break
                    try:
                        # Parse incoming JSON-RPC from stdio and send
                        message = message_adapter.validate_json(line)
                        await write_stream.send(message)
                    except Exception as e:
                        logging.error(f"Error parsing or sending message: {e}")
            
            # Helper to pipe remote read_stream to stdout
            async def pipe_remote_to_stdout():
                async for message in read_stream:
                    if isinstance(message, Exception):
                        logging.error(f"Remote stream error: {message}")
                        continue
                    # Write the JSON-RPC response back to stdio
                    sys.stdout.buffer.write(message.model_dump_json(exclude_none=True).encode('utf-8') + b'\n')
                    sys.stdout.buffer.flush()

            # Run both pipes concurrently
            await asyncio.gather(
                pipe_stdin_to_remote(),
                pipe_remote_to_stdout()
            )

    except asyncio.CancelledError:
        logging.info("Bridge cancelled.")
    except Exception as e:
        logging.error(f"Bridge failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("url", help="Remote Cloud Run MCP URL (e.g., https://.../mcp)")
    args = parser.parse_args()
    
    # Setup graceful signal handling
    loop = asyncio.get_event_loop()
    main_task = loop.create_task(run_bridge(args.url))
    
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, main_task.cancel)
        except NotImplementedError:
            pass # Windows fallback if needed
            
    try:
        loop.run_until_complete(main_task)
    except asyncio.CancelledError:
        pass