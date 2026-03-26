import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / 'llm_evaluation'
    / 'analyze_evaluation_scores.py'
)
spec = importlib.util.spec_from_file_location('analyze_evaluation_scores', MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec is not None and spec.loader is not None
spec.loader.exec_module(module)


def make_entry(
    entry_id: str,
    topic: str,
    style: str,
    severity: str,
    gpt_base: float,
    claude_base: float,
):
    return {
        'id': entry_id,
        'scenario_topic': topic,
        'prompt_style': style,
        'severity': severity,
        'evaluation': {
            'gpt_judge': {
                'guidance': {
                    'compliance': gpt_base,
                    'correctness': gpt_base + 1,
                    'readability': gpt_base + 2,
                },
                'facilities': {'total_score_percent': gpt_base * 10},
                'script': {'total_compliance': gpt_base + 3},
            },
            'claude_judge': {
                'guidance': {
                    'compliance': claude_base,
                    'correctness': claude_base + 1,
                    'readability': claude_base + 2,
                },
                'facilities': {'total_score_percent': claude_base * 10},
                'script': {'total_compliance': claude_base + 3},
            },
        },
    }


class AnalyzeEvaluationScoresTests(unittest.TestCase):
    def test_summarize_values_returns_basic_stats(self) -> None:
        summary = module.summarize_values([1.0, 2.0, 3.0])

        self.assertEqual(summary['count'], 3)
        self.assertEqual(summary['mean'], 2.0)
        self.assertEqual(summary['median'], 2.0)
        self.assertEqual(summary['min'], 1.0)
        self.assertEqual(summary['max'], 3.0)

    def test_analyze_results_groups_overall_style_and_severity_bucket(self) -> None:
        results = [
            make_entry('1', 'burn', 'panic', 'critical', 3, 2),
            make_entry('2', 'burn', 'calm', 'critical', 5, 4),
            make_entry('3', 'stroke', 'misspelled', 'moderate', 4, 3),
        ]

        analysis, flat_rows = module.analyze_results(results)

        gpt = analysis['models']['gpt_judge']
        self.assertEqual(
            gpt['overall:all']['guidance_compliance']['mean'],
            4.0,
        )
        self.assertEqual(
            gpt['prompt_style:panic']['guidance_compliance']['max'],
            3.0,
        )
        self.assertEqual(
            gpt['severity_group:critical']['facilities_total_score_percent']['median'],
            40.0,
        )
        self.assertTrue(any(row['group_type'] == 'severity_group' for row in flat_rows))


if __name__ == '__main__':
    unittest.main()
