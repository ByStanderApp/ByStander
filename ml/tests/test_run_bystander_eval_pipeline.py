import importlib.util
import unittest
from pathlib import Path


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

        result = module.coerce_judge_output(payload)

        self.assertEqual(result["guidance"], {"compliance": 5, "correctness": 1, "readability": 4})
        self.assertEqual(result["facilities"]["total_score_percent"], 20.0)
        self.assertEqual(result["script"]["rule_scores"][:3], [1.0, 0.5, 0.0])
        self.assertEqual(result["script"]["total_compliance"], 1.5)

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


if __name__ == "__main__":
    unittest.main()
