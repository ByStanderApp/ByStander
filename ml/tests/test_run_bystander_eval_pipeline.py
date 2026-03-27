import asyncio
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "llm_evaluation"
    / "run_bystander_eval_pipeline.py"
)
spec = importlib.util.spec_from_file_location("run_bystander_eval_pipeline", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec is not None and spec.loader is not None
spec.loader.exec_module(module)


ScenarioSeed = module.ScenarioSeed


class EvalPipelineTests(unittest.TestCase):
    def test_normalize_source_severity_maps_expected_values(self) -> None:
        self.assertEqual(module.normalize_source_severity("critical"), "critical")
        self.assertEqual(module.normalize_source_severity("mild"), "moderate")
        self.assertEqual(module.normalize_source_severity("no need"), "none")
        self.assertEqual(module.normalize_source_severity("unknown"), "moderate")

    def test_select_scenario_seeds_respects_distribution(self) -> None:
        seeds = []
        for index in range(40):
            seeds.append(ScenarioSeed("critical", f"critical-{index}", "", "step", "", "hospital"))
            seeds.append(ScenarioSeed("moderate", f"moderate-{index}", "", "step", "", "clinic"))
        for index in range(3):
            seeds.append(ScenarioSeed("none", f"none-{index}", "", "step", "", "none"))

        selected = module.select_scenario_seeds(seeds, seed_value=7)
        counts = {"critical": 0, "moderate": 0, "none": 0}
        for item in selected:
            counts[item.severity] += 1

        self.assertEqual(counts, {"critical": 36, "moderate": 36, "none": 3})
        self.assertEqual(len(selected), 75)

    def test_materialize_prompt_rows_expands_three_styles(self) -> None:
        batch = [
            ScenarioSeed("critical", "หัวใจหยุดเต้นเฉียบพลัน", "", "ref", "", "hospital"),
        ]
        topic_order = {("critical", "หัวใจหยุดเต้นเฉียบพลัน"): 1}
        generation_output = [
            {
                "scenario_topic": "หัวใจหยุดเต้นเฉียบพลัน",
                "severity": "critical",
                "panic": "ช่วยด้วย คนล้มไม่หายใจ",
                "calm": "มีผู้ป่วยหมดสติและไม่หายใจ",
                "misspelled": "คนล้มไม่หายใจ ช่วยที",
            }
        ]

        rows = module.materialize_prompt_rows(generation_output, batch, topic_order)

        self.assertEqual(len(rows), 3)
        self.assertEqual([row["prompt_style"] for row in rows], ["panic", "calm", "misspelled"])
        self.assertTrue(rows[0]["id"].endswith("-panic"))

    def test_coerce_judge_output_clamps_and_totals_scores(self) -> None:
        payload = {
            "guidance": {"compliance": 7, "correctness": 0, "readability": 4},
            "facilities": {
                "facility_scores": [
                    {
                        "facility_name": "A",
                        "relevance_score": 1.4,
                        "open_score": -1,
                        "weighted_score_percent": 33,
                    }
                ]
            },
            "script": {"rule_scores": [1, 0.5]},
        }
        source_facilities = [{"name": "A"}]

        result = module.coerce_judge_output(payload, source_facilities)

        self.assertEqual(result["guidance"], {"compliance": 5, "correctness": 1, "readability": 4})
        self.assertEqual(result["facilities"]["facility_scores"][0]["facility_name"], "A")
        self.assertEqual(result["facilities"]["total_score_percent"], 10.0)
        self.assertEqual(result["script"]["rule_scores"][:3], [1.0, 0.5, 0.0])
        self.assertEqual(result["script"]["total_compliance"], 1.5)

    def test_coerce_judge_output_zero_fills_missing_or_mismatched_facilities(self) -> None:
        payload = {
            "facilities": {
                "facility_scores": [
                    {
                        "facility_name": "Wrong Hospital",
                        "relevance_score": 1,
                        "open_score": 1,
                        "weighted_score_percent": 20,
                    }
                ]
            }
        }
        source_facilities = [{"name": "Hospital A"}, {"name": "Hospital B"}]

        result = module.coerce_judge_output(payload, source_facilities)

        self.assertEqual(
            result["facilities"]["facility_scores"],
            [
                {
                    "facility_name": "Hospital A",
                    "relevance_score": 0.0,
                    "open_score": 0.0,
                    "weighted_score_percent": 0.0,
                },
                {
                    "facility_name": "Hospital B",
                    "relevance_score": 0.0,
                    "open_score": 0.0,
                    "weighted_score_percent": 0.0,
                },
            ],
        )
        self.assertEqual(result["facilities"]["total_score_percent"], 0.0)

    def test_build_judge_prompt_lists_script_protocol_rules(self) -> None:
        row = {
            "scenario_topic": "อาหารติดคอ",
            "severity": "critical",
            "prompt_style": "panic",
            "prompt_text": "ช่วยด้วย คนสำลักพูดไม่ได้",
        }
        ai_response = {
            "guidance_text": "โทร 1669",
            "facilities": [],
            "script_text": "แจ้งเหตุฉุกเฉิน",
        }
        seed = ScenarioSeed("critical", "อาหารติดคอ", "", "โทร 1669 และประเมินการหายใจ", "", "hospital")

        prompt = module.build_judge_prompt(
            row,
            ai_response,
            seed,
            coordinate_context={
                "label": "Bangkok",
                "latitude": 13.7563,
                "longitude": 100.5018,
            },
        )

        self.assertIn("1) ตั้งสติ และโทรแจ้ง 1669", prompt)
        self.assertIn("9) รอทีมกู้ชีพมารับเพื่อนำส่งโรงพยาบาล", prompt)
        self.assertIn("human place description", prompt)
        self.assertIn("Bangkok", prompt)

    def test_coordinate_context_for_row_is_deterministic_in_random_thailand_mode(self) -> None:
        first = module.coordinate_context_for_row(
            "row-123",
            coordinate_mode="random-thailand",
            coordinate_seed=17,
            fixed_latitude=13.0,
            fixed_longitude=100.0,
        )
        second = module.coordinate_context_for_row(
            "row-123",
            coordinate_mode="random-thailand",
            coordinate_seed=17,
            fixed_latitude=13.0,
            fixed_longitude=100.0,
        )

        self.assertEqual(first, second)
        self.assertIn("label", first)
        self.assertIn("latitude", first)
        self.assertIn("longitude", first)

    def test_merge_judge_output_preserves_existing_guidance_and_script_in_facilities_only_mode(self) -> None:
        existing = {
            "guidance": {"compliance": 4, "correctness": 4, "readability": 4},
            "facilities": {"facility_scores": [], "total_score_percent": 20},
            "script": {"rule_scores": [1.0] * 9, "total_compliance": 9.0},
        }
        new = {
            "guidance": {"compliance": 1, "correctness": 1, "readability": 1},
            "facilities": {"facility_scores": [], "total_score_percent": 80},
            "script": {"rule_scores": [0.0] * 9, "total_compliance": 0.0},
        }

        merged = module.merge_judge_output(existing, new, "facilities-only")

        self.assertEqual(merged["guidance"], existing["guidance"])
        self.assertEqual(merged["script"], existing["script"])
        self.assertEqual(merged["facilities"], new["facilities"])

    def test_build_failed_judge_output_zeroes_current_facilities_without_stale_scores(self) -> None:
        existing = {
            "guidance": {"compliance": 4, "correctness": 4, "readability": 4},
            "facilities": {
                "facility_scores": [{"facility_name": "Old", "relevance_score": 1, "open_score": 1, "weighted_score_percent": 20}],
                "total_score_percent": 20,
            },
            "script": {"rule_scores": [1.0] * 9, "total_compliance": 9.0},
        }

        failed = module.build_failed_judge_output(
            [{"name": "New A"}, {"name": "New B"}],
            existing_judge=existing,
            evaluation_scope="facilities-only",
        )

        self.assertEqual(failed["guidance"], existing["guidance"])
        self.assertEqual(failed["script"], existing["script"])
        self.assertEqual(
            failed["facilities"]["facility_scores"],
            [
                {
                    "facility_name": "New A",
                    "relevance_score": 0.0,
                    "open_score": 0.0,
                    "weighted_score_percent": 0.0,
                },
                {
                    "facility_name": "New B",
                    "relevance_score": 0.0,
                    "open_score": 0.0,
                    "weighted_score_percent": 0.0,
                },
            ],
        )
        self.assertEqual(failed["facilities"]["total_score_percent"], 0.0)

    def test_infer_facility_type_prefers_reference_seed(self) -> None:
        row = {"severity": "moderate"}
        seed = ScenarioSeed("moderate", "topic", "", "instructions", "", "hospital")
        self.assertEqual(module.infer_facility_type(row, seed), "hospital")
        self.assertEqual(module.infer_facility_type({"severity": "critical"}, None), "hospital")
        self.assertEqual(module.infer_facility_type({"severity": "none"}, None), "none")

    def test_fetch_bystander_response_facilities_only_calls_find_facilities_directly(self) -> None:
        row = {
            "id": "001-test-panic",
            "severity": "critical",
            "prompt_style": "panic",
            "scenario_topic": "topic",
            "prompt_text": "help",
        }
        seed = ScenarioSeed("critical", "topic", "", "instructions", "", "hospital")
        seen_endpoints = []

        async def fake_call(base_url, endpoint, payload, timeout_s, retries):
            del base_url, timeout_s, retries
            seen_endpoints.append((endpoint, payload))
            if endpoint == "/find_facilities":
                return {"facilities": [{"name": "Hospital A", "open_now": True}]}
            raise AssertionError(f"Unexpected endpoint: {endpoint}")

        with patch.object(module, "call_bystander_endpoint", side_effect=fake_call):
            result = asyncio.run(
                module.fetch_bystander_response(
                    row,
                    base_url="http://127.0.0.1:5003",
                    latitude=13.7,
                    longitude=100.5,
                    timeout_s=5,
                    retries=1,
                    evaluation_scope="facilities-only",
                    reference_seed=seed,
                )
            )

        self.assertEqual([item["name"] for item in result["facilities"]], ["Hospital A"])
        self.assertEqual(result["guidance_text"], "")
        self.assertEqual(result["script_text"], "")
        self.assertEqual([endpoint for endpoint, _payload in seen_endpoints], ["/find_facilities"])
        self.assertEqual(seen_endpoints[0][1]["severity"], "critical")
        self.assertEqual(seen_endpoints[0][1]["facility_type"], "hospital")


if __name__ == "__main__":
    unittest.main()
