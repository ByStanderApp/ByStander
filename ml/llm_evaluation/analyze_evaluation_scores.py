#!/usr/bin/env python3
import argparse
import csv
import json
import statistics
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_RESULTS_JSON = ROOT_DIR / 'evaluation_results.json'
DEFAULT_OUTPUT_JSON = ROOT_DIR / 'ml' / 'llm_evaluation' / 'results' / 'score_analysis.json'
DEFAULT_OUTPUT_CSV = ROOT_DIR / 'ml' / 'llm_evaluation' / 'results' / 'score_analysis.csv'
METRIC_PATHS = {
    'guidance_compliance': ('guidance', 'compliance'),
    'guidance_correctness': ('guidance', 'correctness'),
    'guidance_readability': ('guidance', 'readability'),
    'facilities_total_score_percent': ('facilities', 'total_score_percent'),
    'script_total_compliance': ('script', 'total_compliance'),
}
PROMPT_STYLES = ('panic', 'calm', 'misspelled')


def normalize_text(value: Any) -> str:
    return str(value or '').strip()


def load_results(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(payload, list):
        raise ValueError(f'Expected JSON array in {path}')
    return [item for item in payload if isinstance(item, dict)]


def get_nested_number(payload: dict[str, Any], path: tuple[str, ...]) -> float | None:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    try:
        return float(current)
    except (TypeError, ValueError):
        return None


def summarize_values(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {'count': 0, 'mean': None, 'median': None, 'min': None, 'max': None}
    return {
        'count': len(values),
        'mean': round(statistics.fmean(values), 4),
        'median': round(statistics.median(values), 4),
        'min': round(min(values), 4),
        'max': round(max(values), 4),
    }


def build_group_buckets(results: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = {('overall', 'all'): list(results)}
    for style in PROMPT_STYLES:
        buckets[('prompt_style', style)] = [
            item for item in results if normalize_text(item.get('prompt_style')).lower() == style
        ]
    buckets[('severity_group', 'critical')] = [
        item for item in results if normalize_text(item.get('severity')).lower() == 'critical'
    ]
    buckets[('severity_group', 'non-critical')] = [
        item for item in results if normalize_text(item.get('severity')).lower() != 'critical'
    ]
    return buckets


def analyze_results(results: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    grouped = build_group_buckets(results)
    analysis: dict[str, Any] = {'models': {}}
    flat_rows: list[dict[str, Any]] = []

    for model_key in ('gpt_judge', 'claude_judge'):
        model_analysis: dict[str, Any] = {}
        for (group_type, group_value), group_items in grouped.items():
            metric_summary: dict[str, Any] = {}
            for metric_name, metric_path in METRIC_PATHS.items():
                values = []
                for item in group_items:
                    evaluation = item.get('evaluation') if isinstance(item.get('evaluation'), dict) else {}
                    judge = evaluation.get(model_key) if isinstance(evaluation.get(model_key), dict) else {}
                    value = get_nested_number(judge, metric_path)
                    if value is not None:
                        values.append(value)
                summary = summarize_values(values)
                metric_summary[metric_name] = summary
                flat_rows.append(
                    {
                        'model': model_key,
                        'group_type': group_type,
                        'group_value': group_value,
                        'metric': metric_name,
                        **summary,
                    }
                )
            model_analysis[f'{group_type}:{group_value}'] = metric_summary
        analysis['models'][model_key] = model_analysis

    return analysis, flat_rows


def write_csv(rows: list[dict[str, Any]], output_path: Path) -> None:
    if not rows:
        raise ValueError('No rows to write')
    with output_path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Analyze evaluation score distributions')
    parser.add_argument('--results-json', default=str(DEFAULT_RESULTS_JSON), help='Path to evaluation_results.json')
    parser.add_argument('--output-json', default=str(DEFAULT_OUTPUT_JSON), help='Path to write score_analysis.json')
    parser.add_argument('--output-csv', default=str(DEFAULT_OUTPUT_CSV), help='Path to write score_analysis.csv')
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    results = load_results(Path(args.results_json))
    analysis, flat_rows = analyze_results(results)
    Path(args.output_json).write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding='utf-8')
    write_csv(flat_rows, Path(args.output_csv))
    print(f'Loaded {len(results)} evaluation rows')
    print(f'Wrote JSON analysis to {args.output_json}')
    print(f'Wrote CSV analysis to {args.output_csv}')


if __name__ == '__main__':
    main()
