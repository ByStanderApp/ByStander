#!/usr/bin/env python3
"""
Sample catalog scenarios by severity buckets for evaluation runs.

Default target:
- critical: 36
- non_critical: 36
- not_emergency: 3
"""

import argparse
import json
import random
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_CATALOG_PATH = (
    ROOT_DIR / "bystander_frontend" / "assets" / "general_first_aid_catalog.json"
)
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "outputs"


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _to_bucket(severity: str) -> str:
    sev = _normalize_text(severity).lower()
    if sev == "critical":
        return "critical"
    if sev in {"none", "no need", "not emergency", "non emergency", "non-emergency"}:
        return "not_emergency"
    return "non_critical"


def _load_items(path: Path) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    items = payload.get("items", [])
    if not isinstance(items, list):
        return []
    out: List[Dict[str, Any]] = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        row = dict(item)
        row["_source_index"] = idx
        row["_bucket"] = _to_bucket(_normalize_text(item.get("severity")))
        out.append(row)
    return out


def _sample_bucket(
    rows: List[Dict[str, Any]],
    target: int,
    rng: random.Random,
    allow_replacement: bool,
) -> Tuple[List[Dict[str, Any]], int]:
    if target <= 0:
        return [], 0
    if len(rows) >= target:
        chosen = rng.sample(rows, target)
        return [dict(x) for x in chosen], 0

    shortage = target - len(rows)
    chosen = [dict(x) for x in rows]
    if allow_replacement and rows:
        for _ in range(shortage):
            chosen.append(dict(rng.choice(rows)))
    return chosen, shortage


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Sample scenarios from general_first_aid_catalog.json by 3 buckets: "
            "critical / non_critical / not_emergency."
        )
    )
    parser.add_argument(
        "--catalog",
        default=str(DEFAULT_CATALOG_PATH),
        help="Path to general_first_aid_catalog.json",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Output JSON path. If omitted, writes to outputs/sampled_cases_<timestamp>.json",
    )
    parser.add_argument(
        "--critical-count",
        type=int,
        default=36,
        help="Target number of critical cases.",
    )
    parser.add_argument(
        "--non-critical-count",
        type=int,
        default=36,
        help="Target number of non-critical cases.",
    )
    parser.add_argument(
        "--not-emergency-count",
        type=int,
        default=3,
        help="Target number of not-emergency cases.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducible sampling.",
    )
    parser.add_argument(
        "--no-replacement-on-shortage",
        action="store_true",
        help="If set, does not duplicate rows when a bucket has fewer rows than requested.",
    )
    parser.add_argument(
        "--keep-group-order",
        action="store_true",
        help="If set, keep grouped order (critical -> non_critical -> not_emergency).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    catalog_path = Path(args.catalog).resolve()
    if not catalog_path.exists():
        print(f"Catalog file not found: {catalog_path}")
        return 2

    if args.output:
        output_path = Path(args.output).resolve()
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = (DEFAULT_OUTPUT_DIR / f"sampled_cases_{ts}.json").resolve()

    rng = random.Random(args.seed)
    rows = _load_items(catalog_path)
    if not rows:
        print("No items found in catalog.")
        return 1

    pools: Dict[str, List[Dict[str, Any]]] = {
        "critical": [],
        "non_critical": [],
        "not_emergency": [],
    }
    for row in rows:
        bucket = _normalize_text(row.get("_bucket"))
        if bucket not in pools:
            continue
        pools[bucket].append(row)

    targets = {
        "critical": max(0, int(args.critical_count)),
        "non_critical": max(0, int(args.non_critical_count)),
        "not_emergency": max(0, int(args.not_emergency_count)),
    }
    allow_replacement = not bool(args.no_replacement_on_shortage)

    selected: List[Dict[str, Any]] = []
    shortages: Dict[str, int] = {}
    selected_counts: Dict[str, int] = {}

    for bucket in ("critical", "non_critical", "not_emergency"):
        sampled, shortage = _sample_bucket(
            rows=pools[bucket],
            target=targets[bucket],
            rng=rng,
            allow_replacement=allow_replacement,
        )
        for item in sampled:
            item["_sample_bucket"] = bucket
        selected.extend(sampled)
        shortages[bucket] = max(0, shortage)
        selected_counts[bucket] = len(sampled)

    if not args.keep_group_order:
        rng.shuffle(selected)

    for idx, item in enumerate(selected):
        item["_sample_id"] = idx + 1

    output_payload = {
        "config": {
            "generated_at": datetime.now().isoformat(),
            "catalog_path": str(catalog_path),
            "seed": int(args.seed),
            "allow_replacement_on_shortage": allow_replacement,
            "keep_group_order": bool(args.keep_group_order),
            "requested_counts": targets,
        },
        "available_counts": {k: len(v) for k, v in pools.items()},
        "selected_counts": selected_counts,
        "shortages_before_replacement": shortages,
        "items": selected,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(output_payload, f, ensure_ascii=False, indent=2)

    print(f"Catalog path: {catalog_path}")
    print(f"Available: critical={len(pools['critical'])}, non_critical={len(pools['non_critical'])}, not_emergency={len(pools['not_emergency'])}")
    print(f"Requested: critical={targets['critical']}, non_critical={targets['non_critical']}, not_emergency={targets['not_emergency']}")
    print(f"Selected total: {len(selected)}")
    if any(v > 0 for v in shortages.values()):
        print(
            "Shortage detected before replacement: "
            f"critical={shortages['critical']}, "
            f"non_critical={shortages['non_critical']}, "
            f"not_emergency={shortages['not_emergency']}"
        )
        if allow_replacement:
            print("Shortage was filled by sampling with replacement.")
        else:
            print("No replacement mode: output may contain fewer items than requested.")
    print(f"Output JSON: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
