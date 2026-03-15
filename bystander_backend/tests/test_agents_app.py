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

    def run(self, data):
        return {"route": "general_info", "is_emergency": False}


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


if __name__ == "__main__":
    unittest.main()
