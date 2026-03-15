import unittest
import sys
import types
from unittest.mock import MagicMock, patch

try:
    import requests  # noqa: F401
except Exception:
    requests_stub = types.ModuleType("requests")

    class RequestException(Exception):
        pass

    def _not_implemented(*args, **kwargs):
        raise NotImplementedError("requests.get stubbed in tests")

    requests_stub.RequestException = RequestException
    requests_stub.get = _not_implemented
    sys.modules["requests"] = requests_stub

from bystander_backend.facility_finder import main as facility_main


class FacilityFinderCoreTests(unittest.TestCase):
    def test_is_veterinary_place(self):
        self.assertTrue(
            facility_main._is_veterinary_place({"name": "Happy Vet Clinic", "types": []})
        )
        self.assertTrue(
            facility_main._is_veterinary_place({"name": "คลินิกสัตว์", "types": []})
        )
        self.assertFalse(
            facility_main._is_veterinary_place(
                {"name": "Bangkok Hospital", "types": ["hospital"]}
            )
        )

    @patch("bystander_backend.facility_finder.main._get_google_maps_api_key", return_value="k")
    @patch("bystander_backend.facility_finder.main.get_place_details")
    @patch("bystander_backend.facility_finder.main.requests.get")
    def test_search_filters_vet_and_returns_human_facilities(
        self, mock_get, mock_details, _mock_key
    ):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "status": "OK",
            "results": [
                {
                    "place_id": "1",
                    "name": "Good Hospital",
                    "vicinity": "addr1",
                    "geometry": {"location": {"lat": 13.7, "lng": 100.5}},
                    "types": ["hospital"],
                },
                {
                    "place_id": "2",
                    "name": "Animal Vet",
                    "vicinity": "addr2",
                    "geometry": {"location": {"lat": 13.71, "lng": 100.51}},
                    "types": ["veterinary_care"],
                },
            ],
        }
        mock_get.return_value = mock_resp
        mock_details.return_value = {"phone_number": "02-000", "website": "https://a"}

        result = facility_main.search_nearby_facilities(13.7, 100.5, "hospital", "critical")
        self.assertNotIn("error", result)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["facilities"][0]["name"], "Good Hospital")


class FacilityFinderEndpointTests(unittest.TestCase):
    def setUp(self):
        self.client = facility_main.app.test_client()

    def test_find_facilities_requires_lat_lng(self):
        resp = self.client.post("/find_facilities", json={"facility_type": "hospital"})
        self.assertEqual(resp.status_code, 400)

    @patch(
        "bystander_backend.facility_finder.main.search_nearby_facilities",
        return_value={"facilities": [], "total": 0},
    )
    def test_find_facilities_success(self, _mock_search):
        resp = self.client.post(
            "/find_facilities",
            json={
                "latitude": 13.75,
                "longitude": 100.50,
                "facility_type": "hospital",
                "severity": "critical",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("facilities", resp.get_json())


if __name__ == "__main__":
    unittest.main()
