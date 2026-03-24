#!/usr/bin/env python3
"""
Analyze judge_results score outputs filtered by prompts present in prompt_scores.csv.

Scores analyzed:
- output.facility_score
- output.script_score
- output.compliance_score
- output.correctness_score
- output.readability_score
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set


EVAL_DIR = Path(__file__).resolve().parent
DEFAULT_PROMPT_CSV = EVAL_DIR / "agent_workflow_eval_20260320_151309_prompt_scores.csv"
DEFAULT_JUDGE_DIR = EVAL_DIR / "judge_results"
DEFAULT_STYLE_ORDER = ("calm", "misspelled", "panic")
SCORE_NAMES = (
    "facility_score",
    "script_score",
    "compliance_score",
    "correctness_score",
    "readability_score",
)
PROMPT_KEYS = ("prompt", "scenario", "user_prompt", "user_input", "query", "question")


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_prompt(value: Any) -> str:
    text = _normalize_text(value)
    return re.sub(r"\s+", " ", text).strip()


def _safe_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except Exception:
        return None


def _stats(values: Iterable[float]) -> Dict[str, Any]:
    seq = list(values)
    if not seq:
        return {
            "count": 0,
            "average": None,
            "mean": None,
            "median": None,
            "min": None,
            "max": None,
        }
    mean_value = statistics.fmean(seq)
    return {
        "count": len(seq),
        "average": round(mean_value, 4),
        "mean": round(mean_value, 4),
        "median": round(statistics.median(seq), 4),
        "min": round(min(seq), 4),
        "max": round(max(seq), 4),
    }


def _extract_prompt_from_record(record: Dict[str, Any]) -> str:
    input_payload = record.get("input")
    if not isinstance(input_payload, dict):
        return ""

    kwargs = input_payload.get("kwargs")
    if isinstance(kwargs, dict):
        for key in PROMPT_KEYS:
            if key in kwargs and _normalize_text(kwargs.get(key)):
                return _normalize_prompt(kwargs.get(key))

    for key in PROMPT_KEYS:
        if key in input_payload and _normalize_text(input_payload.get(key)):
            return _normalize_prompt(input_payload.get(key))

    args = input_payload.get("args")
    if isinstance(args, list):
        for item in args:
            if isinstance(item, str) and _normalize_text(item):
                return _normalize_prompt(item)
            if isinstance(item, dict):
                for key in PROMPT_KEYS:
                    if key in item and _normalize_text(item.get(key)):
                        return _normalize_prompt(item.get(key))

    return ""


def _load_prompt_styles(prompt_csv_path: Path) -> Dict[str, Set[str]]:
    with prompt_csv_path.open("r", encoding="utf-8", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        mapping: Dict[str, Set[str]] = defaultdict(set)
        for row in reader:
            prompt_key = _normalize_prompt(row.get("prompt"))
            style = _normalize_text(row.get("style")).lower()
            if not prompt_key:
                continue
            if style:
                mapping[prompt_key].add(style)
            else:
                mapping[prompt_key].add("unknown")
    return dict(mapping)


def _load_judge_records(judge_dir: Path) -> Dict[str, List[Dict[str, Any]]]:
    files = {
        "facilities": judge_dir / "judge_facilities_results.json",
        "script": judge_dir / "judge_script_results.json",
        "guidance": judge_dir / "judge_guidance_results.json",
    }
    out: Dict[str, List[Dict[str, Any]]] = {}
    for source, path in files.items():
        if not path.exists():
            out[source] = []
            continue
        with path.open("r", encoding="utf-8") as json_file:
            payload = json.load(json_file)
        if isinstance(payload, list):
            out[source] = [row for row in payload if isinstance(row, dict)]
        else:
            out[source] = []
    return out


def _write_summary_csv(output_path: Path, analysis: Dict[str, Any]) -> None:
    rows: List[Dict[str, Any]] = []
    for score_name, score_stats in analysis["overall_by_score"].items():
        rows.append(
            {
                "scope": "overall",
                "style": "all",
                "score_name": score_name,
                **score_stats,
            }
        )
    for style_name, score_map in analysis["by_style"].items():
        for score_name, score_stats in score_map.items():
            rows.append(
                {
                    "scope": "style",
                    "style": style_name,
                    "score_name": score_name,
                    **score_stats,
                }
            )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=[
                "scope",
                "style",
                "score_name",
                "count",
                "average",
                "mean",
                "median",
                "min",
                "max",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def _build_analysis(
    prompt_styles: Dict[str, Set[str]],
    judge_records_by_source: Dict[str, List[Dict[str, Any]]],
) -> Dict[str, Any]:
    overall_values: Dict[str, List[float]] = defaultdict(list)
    style_values: Dict[str, Dict[str, List[float]]] = {
        style: defaultdict(list) for style in DEFAULT_STYLE_ORDER
    }
    per_prompt_values: Dict[str, Dict[str, List[float]]] = defaultdict(
        lambda: defaultdict(list)
    )

    matched_record_count = 0
    missing_prompt_count = 0
    unmatched_prompt_count = 0
    total_judge_records = 0
    matched_prompt_set: Set[str] = set()

    records_by_source = {
        key: len(value) for key, value in judge_records_by_source.items()
    }
    matched_records_by_source = defaultdict(int)

    for source, records in judge_records_by_source.items():
        for record in records:
            total_judge_records += 1
            prompt_key = _extract_prompt_from_record(record)
            if not prompt_key:
                missing_prompt_count += 1
                continue

            styles = prompt_styles.get(prompt_key)
            if not styles:
                unmatched_prompt_count += 1
                continue

            output_payload = record.get("output")
            if not isinstance(output_payload, dict):
                continue

            score_payload: Dict[str, float] = {}
            for score_name in SCORE_NAMES:
                score_value = _safe_float(output_payload.get(score_name))
                if score_value is not None:
                    score_payload[score_name] = score_value

            if not score_payload:
                continue

            matched_record_count += 1
            matched_records_by_source[source] += 1
            matched_prompt_set.add(prompt_key)

            for score_name, score_value in score_payload.items():
                overall_values[score_name].append(score_value)
                per_prompt_values[prompt_key][score_name].append(score_value)
                for style in styles:
                    style_values.setdefault(style, defaultdict(list))
                    style_values[style][score_name].append(score_value)

    overall_summary = {
        score_name: _stats(overall_values.get(score_name, []))
        for score_name in SCORE_NAMES
    }

    style_order = list(DEFAULT_STYLE_ORDER)
    extra_styles = sorted(set(style_values.keys()) - set(DEFAULT_STYLE_ORDER))
    style_order.extend(extra_styles)
    by_style_summary = {
        style: {
            score_name: _stats(style_values.get(style, {}).get(score_name, []))
            for score_name in SCORE_NAMES
        }
        for style in style_order
    }

    per_prompt_summary = []
    for prompt_key in sorted(per_prompt_values.keys()):
        score_map = per_prompt_values[prompt_key]
        per_prompt_summary.append(
            {
                "prompt": prompt_key,
                "styles": sorted(prompt_styles.get(prompt_key, [])),
                "scores": {
                    score_name: _stats(score_map.get(score_name, []))
                    for score_name in SCORE_NAMES
                },
            }
        )

    return {
        "generated_at": datetime.now().isoformat(),
        "filtering": {
            "csv_unique_prompts": len(prompt_styles),
            "judge_records_total": total_judge_records,
            "judge_records_matched_prompts": matched_record_count,
            "judge_records_unmatched_prompts": unmatched_prompt_count,
            "judge_records_missing_prompt": missing_prompt_count,
            "matched_unique_prompts": len(matched_prompt_set),
        },
        "records_by_source": records_by_source,
        "matched_records_by_source": dict(matched_records_by_source),
        "overall_by_score": overall_summary,
        "by_style": by_style_summary,
        "per_prompt": per_prompt_summary,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Analyze judge_results score outputs filtered by prompts that exist in a "
            "prompt_scores.csv file."
        )
    )
    parser.add_argument(
        "--prompt-csv",
        default=str(DEFAULT_PROMPT_CSV),
        help="Path to prompt scores CSV (must contain columns: prompt, style).",
    )
    parser.add_argument(
        "--judge-dir",
        default=str(DEFAULT_JUDGE_DIR),
        help=(
            "Directory containing judge_facilities_results.json, "
            "judge_script_results.json, judge_guidance_results.json."
        ),
    )
    parser.add_argument(
        "--output-json",
        default="",
        help=(
            "Output path for JSON report. Defaults to "
            "<prompt_csv_stem>_judge_results_analysis.json"
        ),
    )
    parser.add_argument(
        "--output-csv",
        default="",
        help=(
            "Output path for summary CSV. Defaults to "
            "<prompt_csv_stem>_judge_results_summary.csv"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    prompt_csv_path = Path(args.prompt_csv).resolve()
    judge_dir = Path(args.judge_dir).resolve()
    if not prompt_csv_path.exists():
        raise FileNotFoundError(f"Prompt CSV not found: {prompt_csv_path}")
    if not judge_dir.exists():
        raise FileNotFoundError(f"Judge results directory not found: {judge_dir}")

    prompt_styles = _load_prompt_styles(prompt_csv_path)
    judge_records_by_source = _load_judge_records(judge_dir)
    analysis = _build_analysis(prompt_styles, judge_records_by_source)

    output_json = (
        Path(args.output_json).resolve()
        if _normalize_text(args.output_json)
        else prompt_csv_path.with_name(
            f"{prompt_csv_path.stem}_judge_results_analysis.json"
        )
    )
    output_csv = (
        Path(args.output_csv).resolve()
        if _normalize_text(args.output_csv)
        else prompt_csv_path.with_name(
            f"{prompt_csv_path.stem}_judge_results_summary.csv"
        )
    )

    output_json.parent.mkdir(parents=True, exist_ok=True)
    with output_json.open("w", encoding="utf-8") as json_file:
        json.dump(analysis, json_file, ensure_ascii=False, indent=2)
    _write_summary_csv(output_csv, analysis)

    filtering = analysis["filtering"]
    print(f"Prompt CSV: {prompt_csv_path}")
    print(f"Judge dir: {judge_dir}")
    print(f"CSV unique prompts: {filtering['csv_unique_prompts']}")
    print(f"Judge records total: {filtering['judge_records_total']}")
    print(f"Matched judge records: {filtering['judge_records_matched_prompts']}")
    print(f"Matched unique prompts: {filtering['matched_unique_prompts']}")
    print(f"Analysis JSON: {output_json}")
    print(f"Summary CSV: {output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
