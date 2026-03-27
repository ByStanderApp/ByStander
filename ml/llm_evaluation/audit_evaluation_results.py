#!/usr/bin/env python3
import argparse
import csv
import json
import random
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_RESULTS_JSON = ROOT_DIR / "ml" / "llm_evaluation" / "results" / "evaluation_results.json"
DEFAULT_DISAGREEMENTS_CSV = ROOT_DIR / "ml" / "llm_evaluation" / "results" / "judge_disagreements.csv"
DEFAULT_REVIEW_CSV = ROOT_DIR / "ml" / "llm_evaluation" / "results" / "manual_review_sample.csv"
REVIEW_BUCKETS = [
    ("critical", "panic", 5),
    ("critical", "misspelled", 5),
    ("moderate", "panic", 5),
    ("moderate", "misspelled", 5),
    ("none", None, 3),
]


def normalize_text(value: Any) -> str:
    return str(value or "").strip()


def load_results(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Expected a JSON array in {path}")
    return [item for item in payload if isinstance(item, dict)]


def _guidance_value(judge: dict[str, Any], key: str) -> float:
    guidance = judge.get("guidance") if isinstance(judge.get("guidance"), dict) else {}
    return float(guidance.get(key, 0) or 0)


def _facility_total(judge: dict[str, Any]) -> float:
    facilities = judge.get("facilities") if isinstance(judge.get("facilities"), dict) else {}
    return float(facilities.get("total_score_percent", 0) or 0)


def _script_total(judge: dict[str, Any]) -> float:
    script = judge.get("script") if isinstance(judge.get("script"), dict) else {}
    return float(script.get("total_compliance", 0) or 0)


def disagreement_breakdown(entry: dict[str, Any]) -> dict[str, float]:
    evaluation = entry.get("evaluation") if isinstance(entry.get("evaluation"), dict) else {}
    gpt = evaluation.get("gpt_judge") if isinstance(evaluation.get("gpt_judge"), dict) else {}
    claude = evaluation.get("claude_judge") if isinstance(evaluation.get("claude_judge"), dict) else {}

    guidance_compliance = abs(_guidance_value(gpt, "compliance") - _guidance_value(claude, "compliance"))
    guidance_correctness = abs(_guidance_value(gpt, "correctness") - _guidance_value(claude, "correctness"))
    guidance_readability = abs(_guidance_value(gpt, "readability") - _guidance_value(claude, "readability"))
    facility_total = abs(_facility_total(gpt) - _facility_total(claude))
    script_total = abs(_script_total(gpt) - _script_total(claude))
    return {
        "guidance_compliance_diff": guidance_compliance,
        "guidance_correctness_diff": guidance_correctness,
        "guidance_readability_diff": guidance_readability,
        "facility_total_diff": facility_total,
        "script_total_diff": script_total,
        "overall_diff": guidance_compliance
        + guidance_correctness
        + guidance_readability
        + (facility_total / 20.0)
        + script_total,
    }


def sort_by_disagreement(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        entries,
        key=lambda item: (
            disagreement_breakdown(item)["overall_diff"],
            disagreement_breakdown(item)["facility_total_diff"],
            disagreement_breakdown(item)["script_total_diff"],
            normalize_text(item.get("id")),
        ),
        reverse=True,
    )


def _compact_facilities_for_review(facilities: Any) -> list[dict[str, Any]]:
    if not isinstance(facilities, list):
        return []
    trimmed: list[dict[str, Any]] = []
    for facility in facilities:
        if not isinstance(facility, dict):
            continue
        trimmed.append(
            {
                "name": normalize_text(facility.get("name")),
                "open_now": facility.get("open_now"),
                "is_open": facility.get("is_open"),
                "address": normalize_text(facility.get("address")),
                "distance_km": facility.get("distance_km"),
                "rating": facility.get("rating"),
                "selection_reason": normalize_text(facility.get("selection_reason")),
            }
        )
    return trimmed


def _consensus_human_scores(entry: dict[str, Any]) -> dict[str, Any]:
    evaluation = entry.get("evaluation") if isinstance(entry.get("evaluation"), dict) else {}
    gpt = evaluation.get("gpt_judge") if isinstance(evaluation.get("gpt_judge"), dict) else {}
    claude = evaluation.get("claude_judge") if isinstance(evaluation.get("claude_judge"), dict) else {}
    bystander = (
        entry.get("bystander_ai_response")
        if isinstance(entry.get("bystander_ai_response"), dict)
        else {}
    )

    guidance_text = normalize_text(bystander.get("guidance_text"))
    script_text = normalize_text(bystander.get("script_text"))
    gpt_script = gpt.get("script") if isinstance(gpt.get("script"), dict) else {}
    claude_script = claude.get("script") if isinstance(claude.get("script"), dict) else {}
    gpt_rules = gpt_script.get("rule_scores") if isinstance(gpt_script.get("rule_scores"), list) else []
    claude_rules = (
        claude_script.get("rule_scores")
        if isinstance(claude_script.get("rule_scores"), list)
        else []
    )

    if guidance_text:
        guidance_compliance = min(_guidance_value(gpt, "compliance"), _guidance_value(claude, "compliance"))
        guidance_correctness = min(_guidance_value(gpt, "correctness"), _guidance_value(claude, "correctness"))
        guidance_readability = min(_guidance_value(gpt, "readability"), _guidance_value(claude, "readability"))
    else:
        guidance_compliance = 1.0
        guidance_correctness = 1.0
        guidance_readability = 1.0

    facilities_score = min(_facility_total(gpt), _facility_total(claude))

    rule_scores: list[float] = []
    for index in range(9):
        gpt_value = float(gpt_rules[index]) if index < len(gpt_rules) else 0.0
        claude_value = float(claude_rules[index]) if index < len(claude_rules) else 0.0
        if not script_text:
            rule_scores.append(0.0)
        else:
            rule_scores.append(round(min(gpt_value, claude_value), 2))

    diff = disagreement_breakdown(entry)
    notes = "AI conservative audit from raw output plus lower-of-two judge scores."
    if diff["facility_total_diff"] >= 20 or diff["script_total_diff"] >= 2 or diff["overall_diff"] >= 10:
        notes += " Large judge disagreement; review this row first."

    return {
        "human_guidance_compliance": int(guidance_compliance),
        "human_guidance_correctness": int(guidance_correctness),
        "human_guidance_readability": int(guidance_readability),
        "human_facilities_score": round(facilities_score, 2),
        "human_script_rule_1": rule_scores[0],
        "human_script_rule_2": rule_scores[1],
        "human_script_rule_3": rule_scores[2],
        "human_script_rule_4": rule_scores[3],
        "human_script_rule_5": rule_scores[4],
        "human_script_rule_6": rule_scores[5],
        "human_script_rule_7": rule_scores[6],
        "human_script_rule_8": rule_scores[7],
        "human_script_rule_9": rule_scores[8],
        "notes": notes,
    }


def extract_review_row(
    entry: dict[str, Any],
    reason: str,
    rank: int | None = None,
    prefill_human_scores: bool = False,
) -> dict[str, Any]:
    evaluation = entry.get("evaluation") if isinstance(entry.get("evaluation"), dict) else {}
    gpt = evaluation.get("gpt_judge") if isinstance(evaluation.get("gpt_judge"), dict) else {}
    claude = evaluation.get("claude_judge") if isinstance(evaluation.get("claude_judge"), dict) else {}
    bystander = (
        entry.get("bystander_ai_response")
        if isinstance(entry.get("bystander_ai_response"), dict)
        else {}
    )
    diff = disagreement_breakdown(entry)
    row = {
        "selection_reason": reason,
        "disagreement_rank": "" if rank is None else rank,
        "id": normalize_text(entry.get("id")),
        "severity": normalize_text(entry.get("severity")),
        "prompt_style": normalize_text(entry.get("prompt_style")),
        "scenario_topic": normalize_text(entry.get("scenario_topic")),
        "prompt_text": normalize_text(entry.get("prompt_text")),
        "guidance_text": normalize_text(bystander.get("guidance_text")),
        "facilities_json": json.dumps(
            _compact_facilities_for_review(bystander.get("facilities", [])),
            ensure_ascii=False,
        ),
        "script_text": normalize_text(bystander.get("script_text")),
        "gpt_guidance_compliance": _guidance_value(gpt, "compliance"),
        "gpt_guidance_correctness": _guidance_value(gpt, "correctness"),
        "gpt_guidance_readability": _guidance_value(gpt, "readability"),
        "gpt_facility_total": _facility_total(gpt),
        "gpt_script_total": _script_total(gpt),
        "claude_guidance_compliance": _guidance_value(claude, "compliance"),
        "claude_guidance_correctness": _guidance_value(claude, "correctness"),
        "claude_guidance_readability": _guidance_value(claude, "readability"),
        "claude_facility_total": _facility_total(claude),
        "claude_script_total": _script_total(claude),
        "guidance_compliance_diff": diff["guidance_compliance_diff"],
        "guidance_correctness_diff": diff["guidance_correctness_diff"],
        "guidance_readability_diff": diff["guidance_readability_diff"],
        "facility_total_diff": diff["facility_total_diff"],
        "script_total_diff": diff["script_total_diff"],
        "overall_diff": round(diff["overall_diff"], 2),
        "human_guidance_compliance": "",
        "human_guidance_correctness": "",
        "human_guidance_readability": "",
        "human_facilities_score": "",
        "human_script_rule_1": "",
        "human_script_rule_2": "",
        "human_script_rule_3": "",
        "human_script_rule_4": "",
        "human_script_rule_5": "",
        "human_script_rule_6": "",
        "human_script_rule_7": "",
        "human_script_rule_8": "",
        "human_script_rule_9": "",
        "notes": "",
    }
    if prefill_human_scores:
        row.update(_consensus_human_scores(entry))
    return row


def write_csv(rows: list[dict[str, Any]], output_path: Path) -> None:
    if not rows:
        raise ValueError("No rows to write")
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def export_disagreement_csv(
    entries: list[dict[str, Any]],
    output_path: Path,
    top_n: int,
) -> list[dict[str, Any]]:
    ranked = sort_by_disagreement(entries)
    rows = [
        extract_review_row(item, reason="top_disagreement", rank=index)
        for index, item in enumerate(ranked[:top_n], start=1)
    ]
    write_csv(rows, output_path)
    return ranked


def _matches_bucket(entry: dict[str, Any], severity: str, prompt_style: str | None) -> bool:
    if normalize_text(entry.get("severity")).lower() != severity:
        return False
    if prompt_style is None:
        return True
    return normalize_text(entry.get("prompt_style")).lower() == prompt_style


def select_manual_review_sample(
    entries: list[dict[str, Any]],
    random_seed: int,
    prefill_human_scores: bool = False,
) -> list[dict[str, Any]]:
    ranked = sort_by_disagreement(entries)
    rng = random.Random(random_seed)
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()

    def add_entry(entry: dict[str, Any], reason: str, rank: int | None = None) -> None:
        entry_id = normalize_text(entry.get("id"))
        if entry_id in selected_ids:
            return
        selected.append(
            extract_review_row(
                entry,
                reason=reason,
                rank=rank,
                prefill_human_scores=prefill_human_scores,
            )
        )
        selected_ids.add(entry_id)

    for severity, prompt_style, count in REVIEW_BUCKETS:
        bucket = [item for item in entries if _matches_bucket(item, severity, prompt_style)]
        if len(bucket) < count:
            raise ValueError(
                f"Not enough entries for bucket severity={severity} prompt_style={prompt_style}: "
                f"need {count}, found {len(bucket)}"
            )
        bucket_copy = list(bucket)
        rng.shuffle(bucket_copy)
        for item in bucket_copy[:count]:
            reason = f"bucket:{severity}:{prompt_style or 'any'}"
            add_entry(item, reason=reason)

    disagreement_added = 0
    for rank, item in enumerate(ranked, start=1):
        entry_id = normalize_text(item.get("id"))
        if entry_id in selected_ids:
            continue
        add_entry(item, reason="top_disagreement_random", rank=rank)
        disagreement_added += 1
        if disagreement_added >= 5:
            break

    if disagreement_added < 5:
        raise ValueError("Could not find 5 additional disagreement rows outside the fixed review buckets")
    return selected


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit GPT-vs-Claude evaluation disagreements")
    parser.add_argument(
        "--results-json",
        default=str(DEFAULT_RESULTS_JSON),
        help="Path to evaluation_results.json",
    )
    parser.add_argument(
        "--disagreements-csv",
        default=str(DEFAULT_DISAGREEMENTS_CSV),
        help="Output CSV for ranked GPT-vs-Claude disagreements",
    )
    parser.add_argument(
        "--manual-review-csv",
        default=str(DEFAULT_REVIEW_CSV),
        help="Output CSV for manual review sample",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=25,
        help="How many top disagreements to export",
    )
    parser.add_argument(
        "--random-seed",
        type=int,
        default=42,
        help="Random seed for manual review sampling",
    )
    parser.add_argument(
        "--prefill-human-scores",
        action="store_true",
        help="Pre-fill the manual review CSV with a conservative AI audit pass.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    results = load_results(Path(args.results_json))
    ranked = export_disagreement_csv(results, Path(args.disagreements_csv), args.top_n)
    manual_review_rows = select_manual_review_sample(
        results,
        args.random_seed,
        prefill_human_scores=args.prefill_human_scores,
    )
    write_csv(manual_review_rows, Path(args.manual_review_csv))

    print(f"Loaded {len(results)} evaluation rows")
    print(f"Wrote top {min(args.top_n, len(ranked))} disagreements to {args.disagreements_csv}")
    print(f"Wrote {len(manual_review_rows)} manual review rows to {args.manual_review_csv}")
    print("Top 5 disagreements:")
    for index, item in enumerate(ranked[:5], start=1):
        diff = disagreement_breakdown(item)
        print(
            f"{index}. {item.get('id')} | overall_diff={diff['overall_diff']:.2f} | "
            f"guidance=({diff['guidance_compliance_diff']:.1f},"
            f"{diff['guidance_correctness_diff']:.1f},"
            f"{diff['guidance_readability_diff']:.1f}) | "
            f"facility={diff['facility_total_diff']:.1f} | script={diff['script_total_diff']:.1f}"
        )


if __name__ == "__main__":
    main()
