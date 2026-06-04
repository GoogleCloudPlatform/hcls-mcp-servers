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

import unittest
import asyncio
from unittest.mock import patch, AsyncMock, MagicMock
import httpx
import time

import api_client

class TestApiClientHelpers(unittest.TestCase):
    def test_build_search_query(self):
        self.assertEqual(api_client.build_search_query(["a", "b"]), "a AND b")
        self.assertEqual(api_client.build_search_query(["a", "", "b"]), "a AND b")
        self.assertEqual(api_client.build_search_query([]), "")

    def test_escape_query_value(self):
        # tests escape for +, -, &&, etc.
        self.assertEqual(api_client.escape_query_value("a+b"), "a\\+b")
        self.assertEqual(api_client.escape_query_value("a(b)"), "a\\(b\\)")

    def test_quote_value(self):
        self.assertEqual(api_client.quote_value("abc"), '"abc"')
        self.assertEqual(api_client.quote_value('a"b'), '"a\\"b"')

class TestTokenBucket(unittest.IsolatedAsyncioTestCase):
    async def test_acquire_fast(self):
        bucket = api_client.TokenBucket(rate=100.0, capacity=2.0)
        start = time.monotonic()
        await bucket.acquire()
        await bucket.acquire()
        end = time.monotonic()
        self.assertLess(end - start, 0.1)

    async def test_acquire_wait(self):
        bucket = api_client.TokenBucket(rate=10.0, capacity=1.0)
        start = time.monotonic()
        await bucket.acquire() # consumes 1 token
        await bucket.acquire() # should wait 0.1s
        end = time.monotonic()
        self.assertGreaterEqual(end - start, 0.09)

class TestApiGet(unittest.IsolatedAsyncioTestCase):
    @patch('api_client._limiter')
    @patch('api_client.httpx.AsyncClient')
    async def test_api_get_success(self, mock_client_class, mock_limiter):
        mock_limiter.acquire = AsyncMock()
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {"success": True}
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client_class.return_value = mock_client
        
        result = await api_client.api_get("/test")
        self.assertEqual(result, {"success": True})
        mock_client.get.assert_called_once_with("https://api.fda.gov/test", params={})

    @patch('api_client._limiter')
    @patch('api_client.httpx.AsyncClient')
    @patch('api_client.asyncio.sleep', new_callable=AsyncMock)
    async def test_api_get_retry_429(self, mock_sleep, mock_client_class, mock_limiter):
        mock_limiter.acquire = AsyncMock()
        mock_client = AsyncMock()
        
        # Setup 429 response
        response_429 = MagicMock()
        response_429.status_code = 429
        error_429 = httpx.HTTPStatusError("429", request=MagicMock(), response=response_429)
        
        # Setup Success response
        response_success = MagicMock()
        response_success.json.return_value = {"success": True}
        
        mock_client.get.side_effect = [error_429, response_success]
        mock_client.__aenter__.return_value = mock_client
        mock_client_class.return_value = mock_client

        result = await api_client.api_get("/test")
        self.assertEqual(result, {"success": True})
        self.assertEqual(mock_client.get.call_count, 2)
        mock_sleep.assert_called_once_with(1)

    @patch('api_client._limiter')
    @patch('api_client.httpx.AsyncClient')
    @patch('api_client.asyncio.sleep', new_callable=AsyncMock)
    async def test_api_get_timeout(self, mock_sleep, mock_client_class, mock_limiter):
        mock_limiter.acquire = AsyncMock()
        mock_client = AsyncMock()
        
        timeout_error = httpx.TimeoutException("timeout")
        mock_client.get.side_effect = timeout_error
        mock_client.__aenter__.return_value = mock_client
        mock_client_class.return_value = mock_client

        with self.assertRaises(httpx.TimeoutException):
            await api_client.api_get("/test")
            
        self.assertEqual(mock_client.get.call_count, 3)

class TestApiEndpoints(unittest.IsolatedAsyncioTestCase):
    @patch('api_client.api_get')
    async def test_search_drug_events(self, mock_get):
        mock_get.return_value = {"res": 1}
        res = await api_client.search_drug_events(search="test", limit=50)
        self.assertEqual(res, {"res": 1})
        mock_get.assert_called_once_with(api_key=None, path="/drug/event.json", params={"limit": 50, "search": "test"})

    @patch('api_client.api_get')
    async def test_search_device_events(self, mock_get):
        mock_get.return_value = {"res": 2}
        res = await api_client.search_device_events(search="test", skip=10)
        self.assertEqual(res, {"res": 2})
        mock_get.assert_called_once_with(api_key=None, path="/device/event.json", params={"limit": 10, "search": "test", "skip": 10})

    @patch('api_client.api_get')
    async def test_search_drug_enforcement(self, mock_get):
        mock_get.return_value = {"res": 3}
        res = await api_client.search_drug_enforcement()
        self.assertEqual(res, {"res": 3})
        mock_get.assert_called_once_with(api_key=None, path="/drug/enforcement.json", params={"limit": 10})

    @patch('api_client.api_get')
    async def test_search_device_enforcement(self, mock_get):
        mock_get.return_value = {"res": 4}
        res = await api_client.search_device_enforcement()
        self.assertEqual(res, {"res": 4})
        mock_get.assert_called_once_with(api_key=None, path="/device/enforcement.json", params={"limit": 10})

    @patch('api_client.api_get')
    async def test_search_510k(self, mock_get):
        mock_get.return_value = {"res": 5}
        res = await api_client.search_510k()
        self.assertEqual(res, {"res": 5})
        mock_get.assert_called_once_with(api_key=None, path="/device/510k.json", params={"limit": 10})

    @patch('api_client.api_get')
    async def test_search_device_classification(self, mock_get):
        mock_get.return_value = {"res": 6}
        res = await api_client.search_device_classification()
        self.assertEqual(res, {"res": 6})
        mock_get.assert_called_once_with(api_key=None, path="/device/classification.json", params={"limit": 10})

class TestFormatApiError(unittest.TestCase):
    def test_format_404(self):
        response = MagicMock()
        response.status_code = 404
        exc = httpx.HTTPStatusError("404", request=MagicMock(), response=response)
        msg = api_client.format_api_error(exc)
        self.assertIn("No results found", msg)

    def test_format_400(self):
        response = MagicMock()
        response.status_code = 400
        exc = httpx.HTTPStatusError("400", request=MagicMock(), response=response)
        msg = api_client.format_api_error(exc)
        self.assertIn("Invalid query syntax", msg)

    def test_format_timeout(self):
        exc = httpx.TimeoutException("timeout")
        msg = api_client.format_api_error(exc)
        self.assertIn("Request timed out", msg)

    def test_format_generic(self):
        exc = ValueError("bad value")
        msg = api_client.format_api_error(exc)
        self.assertIn("ValueError — bad value", msg)

if __name__ == "__main__":
    unittest.main()
