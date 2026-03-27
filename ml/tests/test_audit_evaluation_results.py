import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "llm_evaluation"
    / "audit_evaluation_results.py"
)
spec = importlib.util.spec_from_file_location("audit_evaluation_results", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec is not None and spec.loader is not None
spec.loader.exec_module(module)


def make_entry(entry_id: str, severity: str, prompt_style: str, overall_bias: float = 0.0):
    return {
        "id": entry_id,
        "severity": severity,
        "prompt_style": prompt_style,
        "scenario_topic": entry_id,
        "prompt_text": entry_id,
        "bystander_ai_response": {
            "guidance_text": "guidance",
            "facilities": [],
            "script_text": "script",
        },
        "evaluation": {
            "gpt_judge": {
                "guidance": {
                    "compliance": 5,
                    "correctness": 4,
                    "readability": 4,
                },
                "facilities": {"facility_scores": [], "total_score_percent": 100 - overall_bias},
                "script": {"rule_scores": [1] * 9, "total_compliance": 9 - overall_bias},
            },
            "claude_judge": {
                "guidance": {
                    "compliance": 3,
                    "correctness": 3,
                    "readability": 2,
                },
                "facilities": {"facility_scores": [], "total_score_percent": 20},
                "script": {"rule_scores": [0] * 9, "total_compliance": 0},
            },
        },
    }


class AuditEvaluationResultsTests(unittest.TestCase):
    def test_disagreement_breakdown_computes_weighted_total(self) -> None:
        entry = make_entry("a", "critical", "panic", overall_bias=0)
        diff = module.disagreement_breakdown(entry)

        self.assertEqual(diff["guidance_compliance_diff"], 2.0)
        self.assertEqual(diff["guidance_correctness_diff"], 1.0)
        self.assertEqual(diff["guidance_readability_diff"], 2.0)
        self.assertEqual(diff["facility_total_diff"], 80.0)
        self.assertEqual(diff["script_total_diff"], 9.0)
        self.assertEqual(diff["overall_diff"], 18.0)

    def test_consensus_human_scores_uses_conservative_lower_scores(self) -> None:
        entry = make_entry("a", "critical", "panic", overall_bias=0)

        scores = module._consensus_human_scores(entry)

        self.assertEqual(scores["human_guidance_compliance"], 3)
        self.assertEqual(scores["human_guidance_correctness"], 3)
        self.assertEqual(scores["human_guidance_readability"], 2)
        self.assertEqual(scores["human_facilities_score"], 20.0)
        self.assertEqual(scores["human_script_rule_1"], 0.0)
        self.assertEqual(scores["human_script_rule_9"], 0.0)
        self.assertIn("AI conservative audit", scores["notes"])

    def test_select_manual_review_sample_uses_requested_bucket_counts(self) -> None:
        entries = []
        for i in range(8):
            entries.append(make_entry(f"cp-{i}", "critical", "panic", overall_bias=i))
            entries.append(make_entry(f"cm-{i}", "critical", "misspelled", overall_bias=i))
            entries.append(make_entry(f"mp-{i}", "moderate", "panic", overall_bias=i))
            entries.append(make_entry(f"mm-{i}", "moderate", "misspelled", overall_bias=i))
        for i in range(5):
            entries.append(make_entry(f"none-{i}", "none", "calm", overall_bias=i))
        entries.extend(
            [
                make_entry("extra-1", "critical", "calm", overall_bias=30),
                make_entry("extra-2", "moderate", "calm", overall_bias=29),
                make_entry("extra-3", "critical", "calm", overall_bias=28),
                make_entry("extra-4", "moderate", "calm", overall_bias=27),
                make_entry("extra-5", "critical", "calm", overall_bias=26),
            ]
        )

        rows = module.select_manual_review_sample(entries, random_seed=7)

        self.assertEqual(len(rows), 28)
        bucket_counts = {}
        disagreement_count = 0
        for row in rows:
            reason = row["selection_reason"]
            if reason.startswith("bucket:"):
                bucket_counts[reason] = bucket_counts.get(reason, 0) + 1
            elif reason == "top_disagreement_random":
                disagreement_count += 1
        self.assertEqual(bucket_counts["bucket:critical:panic"], 5)
        self.assertEqual(bucket_counts["bucket:critical:misspelled"], 5)
        self.assertEqual(bucket_counts["bucket:moderate:panic"], 5)
        self.assertEqual(bucket_counts["bucket:moderate:misspelled"], 5)
        self.assertEqual(bucket_counts["bucket:none:any"], 3)
        self.assertEqual(disagreement_count, 5)

    def test_select_manual_review_sample_can_prefill_human_scores(self) -> None:
        entries = []
        for i in range(8):
            entries.append(make_entry(f"cp-{i}", "critical", "panic", overall_bias=i))
            entries.append(make_entry(f"cm-{i}", "critical", "misspelled", overall_bias=i))
            entries.append(make_entry(f"mp-{i}", "moderate", "panic", overall_bias=i))
            entries.append(make_entry(f"mm-{i}", "moderate", "misspelled", overall_bias=i))
        for i in range(5):
            entries.append(make_entry(f"none-{i}", "none", "calm", overall_bias=i))
        entries.extend(
            [
                make_entry("extra-1", "critical", "calm", overall_bias=30),
                make_entry("extra-2", "moderate", "calm", overall_bias=29),
                make_entry("extra-3", "critical", "calm", overall_bias=28),
                make_entry("extra-4", "moderate", "calm", overall_bias=27),
                make_entry("extra-5", "critical", "calm", overall_bias=26),
            ]
        )

        rows = module.select_manual_review_sample(entries, random_seed=7, prefill_human_scores=True)

        self.assertEqual(len(rows), 28)
        self.assertNotEqual(rows[0]["human_guidance_compliance"], "")
        self.assertNotEqual(rows[0]["human_script_rule_1"], "")


if __name__ == "__main__":
    unittest.main()
