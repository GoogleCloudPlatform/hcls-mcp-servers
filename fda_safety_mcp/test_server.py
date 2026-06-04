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
from unittest.mock import patch, AsyncMock
import json
import httpx

import server
import api_client

class TestServer(unittest.IsolatedAsyncioTestCase):

    @patch('server.search_drug_events')
    async def test_search_adverse_events(self, mock_search):
        # Empty input should return an error
        err = await server.search_adverse_events()
        self.assertIn("Error: Provide at least one", err)

        # Successful call with results
        mock_search.return_value = {
            "meta": {"results": {"total": 1}},
            "results": [{
                "safetyreportid": "123",
                "receivedate": "20240101",
                "serious": "1",
                "occurcountry": "US",
                "patient": {
                    "drug": [{"medicinalproduct": "Aspirin", "drugcharacterization": "1"}],
                    "reaction": [{"reactionmeddrapt": "Headache"}]
                }
            }]
        }

        res = await server.search_adverse_events(
            drug_name="Aspirin", 
            ndc="12345678901",
            reaction="Headache",
            serious=True,
            outcome="death",
            date_from="20200101",
            date_to="20210101"
        )
        self.assertIn("### Report 123", res)
        self.assertIn("**Drugs:** Aspirin (suspect)", res)
        self.assertIn("**Reactions:** Headache", res)
        mock_search.assert_called_once()
        args, kwargs = mock_search.call_args
        self.assertIn("patient.drug.openfda.brand_name:Aspirin OR", kwargs["search"])
        self.assertIn("patient.drug.openfda.ndc:\"12345678901\"", kwargs["search"])
        self.assertIn("patient.reaction.reactionmeddrapt:\"Headache\"", kwargs["search"])
        self.assertIn("serious:1", kwargs["search"])
        self.assertIn("seriousnessdeath:1", kwargs["search"])
        self.assertIn("receivedate:[20200101 TO20210101]", kwargs["search"])

        # Test count field format
        mock_search.reset_mock()
        mock_search.return_value = {
            "results": [
                {"term": "Nausea", "count": 100},
                {"term": "Vomiting", "count": 50}
            ]
        }
        res_count = await server.search_adverse_events(drug_name="Aspirin", count_field="patient.reaction")
        self.assertIn("- **Nausea**: 100 reports", res_count)
        self.assertIn("- **Vomiting**: 50 reports", res_count)

    @patch('server.search_device_events')
    async def test_search_device_events(self, mock_search):
        # Empty input should return an error
        err = await server.tool_search_device_events()
        self.assertIn("Error: Provide at least one search parameter", err)

        mock_search.return_value = {
            "meta": {"results": {"total": 1}},
            "results": [{
                "mdr_report_key": "456",
                "date_received": "20230101",
                "event_type": "Malfunction",
                "device": [{"generic_name": "Pacemaker", "manufacturer_d_name": "ACME"}],
                "mdr_text": [{"text_type_code": "Description of Event or Problem", "text": "Failed"}]
            }]
        }
        
        res = await server.tool_search_device_events(
            device_name="Pacemaker",
            product_code="DXY",
            event_type="malfunction",
            date_from="20220101"
        )
        self.assertIn("### Report 456", res)
        self.assertIn("**Device:** Pacemaker", res)
        self.assertIn("**Manufacturer:** ACME", res)
        self.assertIn("**Description:** Failed...", res)
        mock_search.assert_called_once()
        kwargs = mock_search.call_args[1]
        self.assertIn("device.generic_name:\"Pacemaker\"", kwargs["search"])
        self.assertIn("device.device_report_product_code:\"DXY\"", kwargs["search"])
        self.assertIn("event_type:\"Malfunction\"", kwargs["search"])

        # Test count field format
        mock_search.reset_mock()
        mock_search.return_value = {
            "results": [
                {"term": "Device1", "count": 10},
            ]
        }
        res_count = await server.tool_search_device_events(device_name="Device", count_field="device.generic_name")
        self.assertIn("- **Device1**: 10 reports", res_count)

    @patch('server.search_drug_enforcement')
    async def test_search_drug_recalls(self, mock_search):
        mock_search.return_value = {
            "meta": {"results": {"total": 1}},
            "results": [{
                "recall_number": "D-123-2023",
                "report_date": "20230505",
                "classification": "Class I",
                "status": "Ongoing",
                "product_description": "Bad Pills",
                "reason_for_recall": "Contamination",
                "recalling_firm": "Bad Corp",
                "distribution_pattern": "Nationwide"
            }]
        }
        res = await server.search_drug_recalls(
            drug_name="Pills",
            reason="Contamination",
            classification="I",
            status="Ongoing",
            firm="Bad Corp",
            state="NY",
            date_to="20231231"
        )
        self.assertIn("### D-123-2023", res)
        self.assertIn("**Firm:** Bad Corp", res)
        self.assertIn("**Product:** Bad Pills", res)
        
        mock_search.assert_called_once()
        kwargs = mock_search.call_args[1]
        self.assertIn("product_description:\"Pills\"", kwargs["search"])
        self.assertIn("reason_for_recall:\"Contamination\"", kwargs["search"])
        self.assertIn("classification:\"Class I\"", kwargs["search"])
        self.assertIn("status:\"Ongoing\"", kwargs["search"])
        self.assertIn("recalling_firm:\"Bad Corp\"", kwargs["search"])
        self.assertIn("state:\"NY\"", kwargs["search"])
        self.assertIn("report_date:[19000101 TO20231231]", kwargs["search"])

    @patch('server.search_device_enforcement')
    async def test_search_device_recalls(self, mock_search):
        mock_search.return_value = {
            "meta": {"results": {"total": 1}},
            "results": [{
                "recall_number": "Z-456-2023",
                "report_date": "20230606",
                "classification": "Class II",
                "status": "Ongoing",
                "product_description": "Defective Pump",
                "reason_for_recall": "Software Bug",
                "recalling_firm": "Pump Corp"
            }]
        }
        res = await server.tool_search_device_recalls(
            device_name="Pump",
            reason="Bug",
            classification="II",
            status="Ongoing",
            firm="Pump Corp"
        )
        self.assertIn("### Z-456-2023", res)
        self.assertIn("**Firm:** Pump Corp", res)
        self.assertIn("**Reason:** Software Bug", res)

    @patch('server.search_510k')
    async def test_get_510k(self, mock_search):
        mock_search.return_value = {
            "meta": {"results": {"total": 1}},
            "results": [{
                "k_number": "K212345",
                "device_name": "New Device",
                "applicant": "Innovators Inc",
                "decision_code": "SESE",
                "decision_date": "20211010",
                "product_code": "DXY",
                "statement_or_summary": "Substantially equivalent."
            }]
        }
        res = await server.get_510k(
            k_number="K212345",
            device_name="New Device",
            applicant="Innovators Inc",
            product_code="DXY",
            decision="SESE"
        )
        self.assertIn("### K212345: New Device", res)
        self.assertIn("**Applicant:** Innovators Inc", res)
        self.assertIn("**Decision:** Substantially Equivalent", res)
        self.assertIn("**Summary:** Substantially equivalent....", res)

    @patch('server.search_device_classification')
    async def test_get_device_classification(self, mock_search):
        err = await server.get_device_classification()
        self.assertIn("Error: Provide at least one search parameter", err)

        mock_search.return_value = {
            "meta": {"results": {"total": 1}},
            "results": [{
                "device_name": "Cool Device",
                "product_code": "ABC",
                "device_class": "2",
                "regulation_number": "870.1234",
                "review_panel": "Cardiovascular",
                "submission_type_id": "510(k)",
                "definition": "A device."
            }]
        }
        res = await server.get_device_classification(
            device_name="Cool",
            product_code="ABC",
            device_class="2",
            regulation_number="870.1234"
        )
        self.assertIn("### Cool Device", res)
        self.assertIn("**Class II (Moderate Risk)**", res)
        self.assertIn("**Regulation:** 870.1234", res)
        self.assertIn("**Definition:** A device....", res)

    @patch('server.search_device_classification')
    async def test_get_device_classification_empty(self, mock_search):
        mock_search.return_value = {"results": []}
        res = await server.get_device_classification(device_name="Nonexistent")
        self.assertEqual(res, "No device classifications found matching your criteria.")

    @patch('server.search_drug_events')
    async def test_search_adverse_events_json(self, mock_search):
        mock_data = {"meta": {"results": {"total": 1}}, "results": [{"id": 1}]}
        mock_search.return_value = mock_data
        
        res = await server.search_adverse_events(drug_name="Aspirin", response_format="json")
        self.assertEqual(res, json.dumps(mock_data, indent=2, default=str))

    @patch('server.search_drug_events')
    async def test_search_adverse_events_exception(self, mock_search):
        response = httpx.Response(404, request=httpx.Request("GET", "https://api.fda.gov"))
        mock_search.side_effect = httpx.HTTPStatusError("404 Not Found", request=response.request, response=response)
        
        res = await server.search_adverse_events(drug_name="Aspirin")
        self.assertIn("Error: No results found matching your query.", res)

if __name__ == '__main__':
    unittest.main()
