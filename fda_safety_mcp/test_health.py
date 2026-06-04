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
from unittest.mock import MagicMock
import json

import server

class TestServerHealth(unittest.IsolatedAsyncioTestCase):
    async def test_health_check(self):
        request = MagicMock()
        response = await server.health_check(request)
        body = json.loads(response.body)
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["server"], "fda_safety_mcp")

if __name__ == '__main__':
    unittest.main()
