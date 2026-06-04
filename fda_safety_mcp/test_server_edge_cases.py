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
from unittest.mock import patch, MagicMock
import json

import server

class TestServerEdgeCases(unittest.IsolatedAsyncioTestCase):

    @patch('server.search_device_events')
    async def test_search_device_events_empty_results(self, mock_search):
        mock_search.return_value = {"results": []}
        res = await server.tool_search_device_events(device_name="None")
        self.assertEqual(res, "No device adverse event reports found matching your criteria.")

    @patch('server.search_device_events')
    async def test_search_device_events_json(self, mock_search):
        mock_data = {"meta": {"results": {"total": 1}}, "results": [{"id": 1}]}
        mock_search.return_value = mock_data
        
        res = await server.tool_search_device_events(device_name="Pump", response_format="json")
        self.assertEqual(res, json.dumps(mock_data, indent=2, default=str))

        res_count = await server.tool_search_device_events(device_name="Pump", count_field="device", response_format="json")
        self.assertEqual(res_count, json.dumps(mock_data, indent=2, default=str))

    @patch('server.search_drug_enforcement')
    async def test_search_drug_recalls_empty(self, mock_search):
        mock_search.return_value = {"results": []}
        res = await server.search_drug_recalls(drug_name="None")
        self.assertEqual(res, "No drug recall actions found matching your criteria.")

    @patch('server.search_drug_enforcement')
    async def test_search_drug_recalls_json(self, mock_search):
        mock_data = {"meta": {"results": {"total": 1}}, "results": [{"id": 1}]}
        mock_search.return_value = mock_data
        
        res = await server.search_drug_recalls(drug_name="Pills", response_format="json")
        self.assertEqual(res, json.dumps(mock_data, indent=2, default=str))

    @patch('server.search_device_enforcement')
    async def test_search_device_recalls_empty(self, mock_search):
        mock_search.return_value = {"results": []}
        res = await server.tool_search_device_recalls(device_name="None")
        self.assertEqual(res, "No device recall actions found matching your criteria.")

    @patch('server.search_device_enforcement')
    async def test_search_device_recalls_json(self, mock_search):
        mock_data = {"meta": {"results": {"total": 1}}, "results": [{"id": 1}]}
        mock_search.return_value = mock_data
        
        res = await server.tool_search_device_recalls(device_name="Pump", response_format="json")
        self.assertEqual(res, json.dumps(mock_data, indent=2, default=str))

    @patch('server.search_510k')
    async def test_get_510k_empty(self, mock_search):
        mock_search.return_value = {"results": []}
        res = await server.get_510k(k_number="None")
        self.assertEqual(res, "No 510(k) records found matching your criteria.")

    @patch('server.search_510k')
    async def test_get_510k_json(self, mock_search):
        mock_data = {"meta": {"results": {"total": 1}}, "results": [{"id": 1}]}
        mock_search.return_value = mock_data
        
        res = await server.get_510k(k_number="123", response_format="json")
        self.assertEqual(res, json.dumps(mock_data, indent=2, default=str))

    @patch('server.search_device_classification')
    async def test_get_device_classification_json(self, mock_search):
        mock_data = {"meta": {"results": {"total": 1}}, "results": [{"id": 1}]}
        mock_search.return_value = mock_data
        
        res = await server.get_device_classification(device_name="Cool", response_format="json")
        self.assertEqual(res, json.dumps(mock_data, indent=2, default=str))

if __name__ == '__main__':
    unittest.main()
