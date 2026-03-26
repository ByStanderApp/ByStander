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
                result = retriever.retrieve_with_meta(query="ไม่หายใจ", severity="critical", top_k=1)
            self.assertEqual(result["source"], "vertex")
            self.assertEqual(result["count"], 1)
            self.assertIn("[Vertex Protocol 1]", result["context"])
        finally:
            os.remove(csv_path)


class MapAgentTests(unittest.TestCase):
    def test_map_agent_critical_requires_full_hospital_and_ranks_by_eta(self):
        agent = MapAgent()
        fake_result = {
            "facilities": [
                {
                    "place_id": "full-hospital-fast",
                    "name": "โรงพยาบาลเอ",
                    "address": "",
                    "phone_number": "",
                    "rating": 3.0,
                    "open_now": True,
                    "latitude": 13.75,
                    "longitude": 100.55,
                    "types": ["hospital"],
                },
                {
                    "place_id": "subdepartment",
                    "name": "ศูนย์อุบัติเหตุ รพ.บี",
                    "address": "",
                    "phone_number": "",
                    "rating": 4.8,
                    "open_now": True,
                    "latitude": 13.70,
                    "longitude": 100.50,
                    "types": ["hospital"],
                },
                {
                    "place_id": "full-hospital-slower",
                    "name": "โรงพยาบาลซี",
                    "address": "",
                    "phone_number": "",
                    "rating": 4.2,
                    "open_now": True,
                    "latitude": 13.71,
                    "longitude": 100.51,
                    "types": ["hospital"],
                },
            ]
        }
        with patch.object(MapAgent, "search_nearby_facilities", return_value=fake_result):
            with patch.object(
                MapAgent,
                "_estimate_route_eta_minutes",
                return_value={
                    "full-hospital-fast": 8.0,
                    "subdepartment": 3.0,
                    "full-hospital-slower": 16.0,
                },
            ):
                out = agent.run(
                    scenario="critical",
                    severity="critical",
                    facility_type="clinic",
                    latitude=13.7563,
                    longitude=100.5018,
                )
        self.assertEqual([item["name"] for item in out], ["โรงพยาบาลเอ", "โรงพยาบาลซี"])
        self.assertIn("critical", out[0]["selection_reason"])
        self.assertLess(out[0]["eta_minutes"], out[1]["eta_minutes"])
        self.assertGreater(out[0]["selection_score"], out[1]["selection_score"])
        self.assertIn("is_open", out[0])
        self.assertIn("open_now", out[0])
        self.assertNotIn("ศูนย์อุบัติเหตุ รพ.บี", [item["name"] for item in out])

    def test_map_agent_moderate_drops_irrelevant_specialty_places(self):
        agent = MapAgent()
        fake_result = {
            "facilities": [
                {
                    "place_id": "general-clinic",
                    "name": "คลินิกเวชกรรมทั่วไป",
                    "address": "",
                    "phone_number": "",
                    "rating": 4.0,
                    "open_now": True,
                    "latitude": 13.75,
                    "longitude": 100.55,
                    "types": ["doctor"],
                },
                {
                    "place_id": "dental-clinic",
                    "name": "Smile Dental Clinic",
                    "address": "",
                    "phone_number": "",
                    "rating": 4.9,
                    "open_now": True,
                    "latitude": 13.75,
                    "longitude": 100.56,
                    "types": ["doctor"],
                },
                {
                    "place_id": "blood-room",
                    "name": "ห้องเจาะเลือด รพ.กลาง",
                    "address": "",
                    "phone_number": "",
                    "rating": 5.0,
                    "open_now": True,
                    "latitude": 13.75,
                    "longitude": 100.54,
                    "types": ["hospital"],
                },
            ]
        }
        with patch.object(MapAgent, "search_nearby_facilities", return_value=fake_result):
            with patch.object(
                MapAgent,
                "_estimate_route_eta_minutes",
                return_value={
                    "general-clinic": 14.0,
                    "dental-clinic": 6.0,
                    "blood-room": 5.0,
                },
            ):
                out = agent.run(
                    scenario="ปวดท้องรุนแรง แต่ยังรู้สึกตัวดี",
                    severity="moderate",
                    facility_type="clinic",
                    latitude=13.7563,
                    longitude=100.5018,
                )
        self.assertEqual([item["name"] for item in out], ["คลินิกเวชกรรมทั่วไป"])
        self.assertIn("moderate", out[0]["selection_reason"])
        self.assertGreaterEqual(out[0]["selection_score"], 0.45)
        self.assertNotIn("Smile Dental Clinic", [item["name"] for item in out])
        self.assertNotIn("ห้องเจาะเลือด รพ.กลาง", [item["name"] for item in out])

    def test_map_agent_moderate_rewards_matching_specialty_clinic(self):
        agent = MapAgent()
        fake_result = {
            "facilities": [
                {
                    "place_id": "general-clinic",
                    "name": "คลินิกเวชกรรมทั่วไป",
                    "address": "",
                    "phone_number": "",
                    "rating": 3.8,
                    "open_now": True,
                    "latitude": 13.75,
                    "longitude": 100.55,
                    "types": ["doctor"],
                },
                {
                    "place_id": "eye-clinic",
                    "name": "คลินิกจักษุอโศก",
                    "address": "",
                    "phone_number": "",
                    "rating": 5.0,
                    "open_now": True,
                    "latitude": 13.75,
                    "longitude": 100.56,
                    "types": ["doctor"],
                },
            ]
        }
        with patch.object(MapAgent, "search_nearby_facilities", return_value=fake_result):
            with patch.object(
                MapAgent,
                "_estimate_route_eta_minutes",
                return_value={
                    "general-clinic": 8.0,
                    "eye-clinic": 14.0,
                },
            ):
                out = agent.run(
                    scenario="สารเคมีเข้าตา แสบตา ตามัว",
                    severity="moderate",
                    facility_type="clinic",
                    latitude=13.7563,
                    longitude=100.5018,
                )
        self.assertEqual(out[0]["name"], "คลินิกจักษุอโศก")
        self.assertGreater(out[0]["specialty_fit_score"], out[1]["specialty_fit_score"])

    def test_search_nearby_facilities_filters_closed_and_unknown_opening(self):
        agent = MapAgent()
        nearby_result = {
            "results": [
                {
                    "place_id": "open-place",
                    "name": "Open Hospital",
                    "vicinity": "Here",
                    "rating": 4.8,
                    "user_ratings_total": 100,
                    "types": ["hospital"],
                    "geometry": {"location": {"lat": 13.75, "lng": 100.50}},
                    "opening_hours": {"open_now": True},
                },
                {
                    "place_id": "closed-place",
                    "name": "Closed Hospital",
                    "vicinity": "There",
                    "rating": 4.9,
                    "user_ratings_total": 90,
                    "types": ["hospital"],
                    "geometry": {"location": {"lat": 13.76, "lng": 100.51}},
                    "opening_hours": {"open_now": False},
                },
                {
                    "place_id": "unknown-place",
                    "name": "Unknown Hospital",
                    "vicinity": "Elsewhere",
                    "rating": 4.0,
                    "user_ratings_total": 70,
                    "types": ["hospital"],
                    "geometry": {"location": {"lat": 13.77, "lng": 100.52}},
                },
            ]
        }
        details_by_id = {
            "open-place": {"phone_number": "", "website": "", "opening_hours": {"open_now": True}},
            "closed-place": {
                "phone_number": "",
                "website": "",
                "opening_hours": {"open_now": False},
            },
            "unknown-place": {"phone_number": "", "website": "", "opening_hours": {}},
        }

        with patch.object(MapAgent, "_build_query_plan", return_value=[{"radius": 1000, "type": "hospital", "keyword": ""}]):
            with patch.object(MapAgent, "_nearby_search", return_value=nearby_result):
                with patch.object(MapAgent, "_llm_validate_candidates", return_value={}):
                    with patch.object(
                        MapAgent,
                        "_get_place_details",
                        side_effect=lambda place_id: details_by_id[place_id],
                    ):
                        result = agent.search_nearby_facilities(
                            latitude=13.7563,
                            longitude=100.5018,
                            facility_type="hospital",
                            severity="critical",
                            scenario="เจ็บหน้าอก",
                        )

        self.assertEqual(result["total"], 1)
        self.assertEqual(result["facilities"][0]["place_id"], "open-place")
        self.assertTrue(result["facilities"][0]["open_now"])

    def test_search_nearby_facilities_falls_back_from_clinic_to_hospital(self):
        agent = MapAgent()

        def fake_search_once(*, requested_facility_type, **_kwargs):
            if requested_facility_type == "clinic":
                return {"facilities": [], "total": 0}
            return {
                "facilities": [
                    {
                        "place_id": "hospital-1",
                        "name": "Fallback Hospital",
                        "address": "Here",
                        "phone_number": "",
                        "website": "",
                        "rating": 4.7,
                        "user_ratings_total": 50,
                        "open_now": True,
                        "latitude": 13.75,
                        "longitude": 100.50,
                        "types": ["hospital"],
                    }
                ],
                "total": 1,
            }

        with patch.object(MapAgent, "_search_nearby_facilities_once", side_effect=fake_search_once):
            result = agent.search_nearby_facilities(
                latitude=13.7563,
                longitude=100.5018,
                facility_type="clinic",
                severity="moderate",
                scenario="ปวดท้อง",
            )

        self.assertEqual(result["total"], 1)
        self.assertEqual(result["fallback_facility_type"], "hospital")

    def test_strict_filter_rejects_hospital_subdepartments(self):
        agent = MapAgent()
        decision = agent._strict_filter(
            {
                "name": "ห้องเจาะเลือด โรงพยาบาลกลาง",
                "types": ["hospital"],
            },
            requested_facility_type="hospital",
            severity="critical",
        )
        self.assertEqual(decision, "reject")


if __name__ == "__main__":
    unittest.main()
