import unittest
from unittest.mock import patch


class _StubRetriever:
    def catalog(self):
        return [{"case_name_th": "x"}]

    def retrieve_with_meta(self, query, severity, top_k):
        return {
            "source": "vertex",
            "count": 1,
            "vertex_error": "",
            "vertex_attempts": [],
            "context": "ctx",
        }

    def debug_vertex_status(self, scenario, severity, top_k):
        return {"source": "vertex", "count": 1}

    def debug_vertex_resources(self):
        return {"corpora": []}


class _StubWorkflow:
    def __init__(self):
        self.retriever = _StubRetriever()
        self.map_agent = self

    async def run_async(self, data):
        return {"route": "general_info", "is_emergency": False}

    async def find_facilities_async(self, data):
        latitude = data.get("latitude")
        longitude = data.get("longitude")
        if latitude is None or longitude is None:
            return {"facilities": [], "total": 0, "pending_location": True}
        return {
            "facilities": [
                {
                    "name": "Test Hospital",
                    "address": "Bangkok",
                    "phone_number": "02-000-0000",
                    "rating": 4.5,
                    "latitude": latitude,
                    "longitude": longitude,
                }
            ],
            "total": 1,
        }

    async def generate_call_script_async(self, data):
        return {
            "call_script": "test call script",
            "used_medical_history": ["asthma"],
            "location_context": "",
            "facilities": [],
        }


class AgentAppTests(unittest.TestCase):
    def setUp(self):
        patcher = patch("bystander_backend.agents.app.workflow", new=_StubWorkflow())
        self.addCleanup(patcher.stop)
        patcher.start()
        from bystander_backend.agents.app import app

        self.client = app.test_client()

    def test_agent_workflow_endpoint(self):
        resp = self.client.post("/agent_workflow", json={"scenario": "test"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("route", resp.get_json())

    def test_debug_retrieval_endpoint(self):
        resp = self.client.post("/debug_retrieval", json={"scenario": "x", "severity": "critical"})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["source"], "vertex")

    def test_find_facilities_endpoint(self):
        resp = self.client.post(
            "/find_facilities",
            json={
                "latitude": 13.75,
                "longitude": 100.50,
                "facility_type": "hospital",
                "severity": "critical",
                "scenario": "คนหมดสติไม่หายใจ",
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["total"], 1)

    def test_find_facilities_endpoint_handles_missing_location(self):
        resp = self.client.post("/find_facilities", json={"scenario": "เจ็บหน้าอก"})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["pending_location"])

    def test_call_script_endpoint(self):
        resp = self.client.post("/call_script", json={"scenario": "test"})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["call_script"], "test call script")
        self.assertEqual(data["used_medical_history"], ["asthma"])


if __name__ == "__main__":
    unittest.main()
