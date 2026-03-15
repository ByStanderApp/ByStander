import os
import tempfile
import unittest
from unittest.mock import patch

from bystander_backend.agents.agents import MapAgent, ProtocolRetriever


class ProtocolRetrieverTests(unittest.TestCase):
    def _make_csv(self):
        fd, path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        with open(path, "w", encoding="utf-8") as f:
            f.write(
                "Case Name (TH),Case Name (EN),Keywords,Instructions,severity,facility_type\n"
                "หัวใจหยุดเต้นเฉียบพลัน,cardiac arrest,CPR,โทร 1669 และเริ่ม CPR,critical,hospital\n"
                "หมดสติ (หายใจอยู่),unconscious breathing,สลบ,จัดท่าพักฟื้นและเฝ้าระวัง,mild,clinic\n"
            )
        return path

    def test_retrieve_with_meta_falls_back_to_csv_when_vertex_empty(self):
        csv_path = self._make_csv()
        try:
            retriever = ProtocolRetriever(csv_path=csv_path)
            with patch.object(ProtocolRetriever, "_search_vertex", return_value=[]):
                result = retriever.retrieve_with_meta(
                    query="คนหมดสติไม่หายใจ ต้อง CPR", severity="critical", top_k=2
                )
            self.assertEqual(result["source"], "csv")
            self.assertGreaterEqual(result["count"], 1)
            self.assertIn("[Protocol 1]", result["context"])
        finally:
            os.remove(csv_path)

    def test_retrieve_with_meta_uses_vertex_when_docs_found(self):
        csv_path = self._make_csv()
        try:
            retriever = ProtocolRetriever(csv_path=csv_path)
            fake_docs = [
                {
                    "title": "Vertex CPR",
                    "body": "โทร 1669 และกดหน้าอก 30 ครั้ง",
                    "meta": "source=gs://test/doc.txt",
                }
            ]
            with patch.object(ProtocolRetriever, "_search_vertex", return_value=fake_docs):
                result = retriever.retrieve_with_meta(
                    query="ไม่หายใจ", severity="critical", top_k=1
                )
            self.assertEqual(result["source"], "vertex")
            self.assertEqual(result["count"], 1)
            self.assertIn("[Vertex Protocol 1]", result["context"])
        finally:
            os.remove(csv_path)


class MapAgentTests(unittest.TestCase):
    def test_map_agent_sorts_by_distance_for_critical(self):
        agent = MapAgent()
        fake_result = {
            "facilities": [
                {
                    "name": "A",
                    "address": "",
                    "phone_number": "",
                    "rating": 3.0,
                    "latitude": 13.75,
                    "longitude": 100.55,
                },
                {
                    "name": "B",
                    "address": "",
                    "phone_number": "",
                    "rating": 4.8,
                    "latitude": 13.70,
                    "longitude": 100.50,
                },
            ]
        }
        with patch("bystander_backend.agents.agents.search_nearby_facilities", return_value=fake_result):
            out = agent.run(
                scenario="critical",
                severity="critical",
                facility_type="hospital",
                latitude=13.7563,
                longitude=100.5018,
            )
        self.assertEqual(len(out), 2)
        self.assertLessEqual(out[0]["distance_km"], out[1]["distance_km"])
        self.assertIn("critical", out[0]["selection_reason"])

    def test_map_agent_sorts_by_rating_for_moderate(self):
        agent = MapAgent()
        fake_result = {
            "facilities": [
                {
                    "name": "Low",
                    "address": "",
                    "phone_number": "",
                    "rating": 2.0,
                    "latitude": 13.75,
                    "longitude": 100.55,
                },
                {
                    "name": "High",
                    "address": "",
                    "phone_number": "",
                    "rating": 4.9,
                    "latitude": 13.75,
                    "longitude": 100.56,
                },
            ]
        }
        with patch("bystander_backend.agents.agents.search_nearby_facilities", return_value=fake_result):
            out = agent.run(
                scenario="moderate",
                severity="moderate",
                facility_type="clinic",
                latitude=13.7563,
                longitude=100.5018,
            )
        self.assertEqual(out[0]["name"], "High")
        self.assertIn("moderate", out[0]["selection_reason"])


if __name__ == "__main__":
    unittest.main()
