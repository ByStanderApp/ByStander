#!/usr/bin/env python3
"""
Evaluate ByStander main workflow with AI-generated user prompts.

Pipeline:
1) Load first-aid scenarios from general_first_aid_catalog.json.
2) Use an AI prompt generator (ChatGPT/OpenAI API) to create 3 user prompt styles per scenario:
   calm, misspelled, panic.
3) Send each generated prompt to the existing main agent workflow (ByStanderWorkflow.run).
4) Let workflow-internal judge_service.py handle judging asynchronously.
5) Persist run logs as JSON, including per-facility JSON logs.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

try:
    from openai import OpenAI

    OPENAI_AVAILABLE = True
except Exception:  # pragma: no cover
    OpenAI = None
    OPENAI_AVAILABLE = False


SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = None
for parent in SCRIPT_PATH.parents:
    if (parent / "bystander_backend").exists():
        PROJECT_ROOT = parent
        break
if PROJECT_ROOT is None:
    PROJECT_ROOT = SCRIPT_PATH.parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bystander_backend.agents.agents import ByStanderWorkflow  # noqa: E402
from bystander_backend.agents.observability import init_observability  # noqa: E402


STYLE_KEYS = ("calm", "misspelled", "panic")
DEFAULT_CATALOG_PATH = (
    PROJECT_ROOT / "bystander_frontend" / "assets" / "general_first_aid_catalog.json"
)
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "outputs"
DEFAULT_PROMPT_MODEL = "gpt-5.1-mini"


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _extract_json_block(text: str) -> Optional[str]:
    raw = _normalize_text(text)
    if not raw:
        return None
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return raw[start : end + 1]


def _parse_json_object(text: str) -> Optional[Dict[str, Any]]:
    block = _extract_json_block(text)
    if not block:
        return None
    try:
        payload = json.loads(block)
    except Exception:
        return None
    if isinstance(payload, dict):
        return payload
    return None


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _slugify_filename(value: str) -> str:
    ascii_only = _normalize_text(value).encode("ascii", "ignore").decode("ascii")
    base = re.sub(r"[^a-zA-Z0-9]+", "_", ascii_only).strip("_").lower()
    if base:
        return base[:80]
    digest = hashlib.sha1(_normalize_text(value).encode("utf-8")).hexdigest()[:12]
    return f"facility_{digest}"


class PromptGenerationAgent:
    def __init__(
        self,
        api_key: str,
        model: str,
        timeout_s: float,
        temperature: float,
    ) -> None:
        self.model = _normalize_text(model) or DEFAULT_PROMPT_MODEL
        self.timeout_s = max(5.0, float(timeout_s))
        self.temperature = max(0.0, min(1.2, float(temperature)))
        self.enabled = bool(api_key and OPENAI_AVAILABLE and OpenAI is not None)
        self.client = OpenAI(api_key=api_key) if self.enabled and OpenAI else None

    def _fallback_prompts(self, scenario: Dict[str, Any]) -> Dict[str, str]:
        case_name = _normalize_text(scenario.get("case_name_th") or scenario.get("case_name_en"))
        keywords = _normalize_text(scenario.get("keywords"))
        keywords_short = ", ".join([x.strip() for x in keywords.split(",") if x.strip()][:3])
        hint = f" อาการประมาณ: {keywords_short}" if keywords_short else ""
        return {
            "calm": f"สวัสดีครับ ช่วยแนะนำปฐมพยาบาลเบื้องต้นกรณี{case_name}หน่อยครับ{hint}",
            "misspelled": f"ชวยเเนะนำปฐมพยาบานหน่อยครับ เคส{case_name} ตอนนี้ควรทำไงดี{hint}",
            "panic": f"ช่วยด้วย!! {case_name} ด่วนมาก ต้องทำอะไรตอนนี้ โทร 1669 เลยไหม?!",
        }

    def _build_prompts(self, scenario: Dict[str, Any]) -> Tuple[str, str]:
        case_name_th = _normalize_text(scenario.get("case_name_th"))
        case_name_en = _normalize_text(scenario.get("case_name_en"))
        keywords = _normalize_text(scenario.get("keywords"))
        instructions = _normalize_text(scenario.get("instructions"))[:1400]
        severity = _normalize_text(scenario.get("severity"))
        facility_type = _normalize_text(scenario.get("facility_type"))

        system_prompt = (
            "You write realistic Thai user messages for emergency first-aid assistants. "
            "Generate exactly 3 prompt variants for the same medical scenario.\n"
            "Output STRICT JSON only with keys: calm, misspelled, panic.\n"
            "Rules:\n"
            "- calm: polite, concise, stable tone.\n"
            "- misspelled: understandable Thai with common human typos/misspellings.\n"
            "- panic: urgent and distressed tone, short bursts, still understandable.\n"
            "- Each prompt must be a user asking for help (not giving medical instructions).\n"
            "- Keep each prompt <= 220 Thai characters.\n"
            "- Keep all 3 prompts about the same scenario intent."
        )
        user_prompt = (
            "Scenario source data:\n"
            f"- case_name_th: {case_name_th}\n"
            f"- case_name_en: {case_name_en}\n"
            f"- severity: {severity}\n"
            f"- expected_facility_type: {facility_type}\n"
            f"- reference_instructions: {instructions}\n\n"
            "Return strict JSON only:\n"
            "{\"calm\":\"...\",\"misspelled\":\"...\",\"panic\":\"...\"}"
        )
        return system_prompt, user_prompt

    def _call_openai(self, system_prompt: str, user_prompt: str) -> Tuple[str, str]:
        if not self.enabled or self.client is None:
            return "", "openai_unavailable"

        # Preferred path: Responses API.
        try:
            response = self.client.responses.create(
                model=self.model,
                reasoning={"effort": "medium"},
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=self.temperature,
                max_output_tokens=500,
                timeout=self.timeout_s,
            )
            text = _normalize_text(getattr(response, "output_text", ""))
            if not text:
                text = _normalize_text(str(response))
            return text, ""
        except Exception as exc:
            responses_error = str(exc)

        # Compatibility path: Chat Completions.
        try:
            chat = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=self.temperature,
                timeout=self.timeout_s,
            )
            text = ""
            if getattr(chat, "choices", None):
                text = _normalize_text(chat.choices[0].message.content)
            if not text:
                text = _normalize_text(str(chat))
            return text, ""
        except Exception as exc:
            return "", f"{responses_error}; {exc}"

    def generate_prompts(self, scenario: Dict[str, Any]) -> Tuple[Dict[str, str], Dict[str, Any]]:
        fallback = self._fallback_prompts(scenario)
        system_prompt, user_prompt = self._build_prompts(scenario)
        raw_text, call_error = self._call_openai(system_prompt=system_prompt, user_prompt=user_prompt)
        parsed = _parse_json_object(raw_text) if raw_text else None

        out = dict(fallback)
        parse_error = ""
        if parsed is None and raw_text:
            parse_error = "invalid_json"
        if isinstance(parsed, dict):
            for style in STYLE_KEYS:
                value = _normalize_text(parsed.get(style))
                if value:
                    out[style] = value

        return out, {
            "model": self.model,
            "openai_enabled": self.enabled,
            "used_fallback": not bool(parsed),
            "error": call_error or parse_error,
            "raw_response": raw_text,
        }


class MainWorkflowAgent:
    def __init__(
        self,
        workflow: ByStanderWorkflow,
        latitude: Optional[float],
        longitude: Optional[float],
        user_id: str,
    ) -> None:
        self.workflow = workflow
        self.latitude = latitude
        self.longitude = longitude
        self.user_id = _normalize_text(user_id)

    def run(self, prompt: str) -> Tuple[Dict[str, Any], int]:
        payload: Dict[str, Any] = {"scenario": prompt}
        if self.latitude is not None and self.longitude is not None:
            payload["latitude"] = self.latitude
            payload["longitude"] = self.longitude
        if self.user_id:
            payload["user_id"] = self.user_id

        started = time.perf_counter()
        result = self.workflow.run(payload)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return result, elapsed_ms


class FacilityLogWriter:
    def __init__(self) -> None:
        self._records_by_filekey: Dict[str, Dict[str, Any]] = {}

    def _ensure_bucket(self, filekey: str, facility_name: str) -> Dict[str, Any]:
        if filekey not in self._records_by_filekey:
            self._records_by_filekey[filekey] = {
                "facility_name": facility_name,
                "records": [],
            }
        return self._records_by_filekey[filekey]

    def add_run_record(self, run_record: Dict[str, Any]) -> None:
        facilities = ((run_record.get("workflow") or {}).get("facilities")) or []
        if not facilities:
            bucket = self._ensure_bucket("no_facility_found", "NO_FACILITY_FOUND")
            bucket["records"].append(
                {
                    "run_id": run_record.get("run_id"),
                    "scenario_case_name": ((run_record.get("scenario") or {}).get("case_name_th")),
                    "style": run_record.get("style"),
                    "prompt": run_record.get("prompt"),
                    "severity": ((run_record.get("workflow") or {}).get("severity")),
                    "facility_type": ((run_record.get("workflow") or {}).get("facility_type")),
                    "route": ((run_record.get("workflow") or {}).get("route")),
                    "judge_mode": run_record.get("judge_mode"),
                    "timestamp": run_record.get("timestamp"),
                }
            )
            return

        for facility in facilities:
            name = _normalize_text(facility.get("name")) or "UNKNOWN_FACILITY"
            filekey = _slugify_filename(name)
            bucket = self._ensure_bucket(filekey=filekey, facility_name=name)
            bucket["records"].append(
                {
                    "run_id": run_record.get("run_id"),
                    "scenario_case_name": ((run_record.get("scenario") or {}).get("case_name_th")),
                    "style": run_record.get("style"),
                    "prompt": run_record.get("prompt"),
                    "severity": ((run_record.get("workflow") or {}).get("severity")),
                    "facility_type": ((run_record.get("workflow") or {}).get("facility_type")),
                    "route": ((run_record.get("workflow") or {}).get("route")),
                    "judge_mode": run_record.get("judge_mode"),
                    "facility": facility,
                    "timestamp": run_record.get("timestamp"),
                }
            )

    def write(self, output_dir: Path) -> List[str]:
        output_dir.mkdir(parents=True, exist_ok=True)
        written: List[str] = []
        for filekey in sorted(self._records_by_filekey.keys()):
            payload = self._records_by_filekey[filekey]
            payload["total_records"] = len(payload["records"])
            path = output_dir / f"{filekey}.json"
            with path.open("w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            written.append(str(path))
        return written


def _load_catalog(catalog_path: Path) -> List[Dict[str, Any]]:
    with catalog_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    items = payload.get("items", [])
    if not isinstance(items, list):
        return []
    out: List[Dict[str, Any]] = []
    for row in items:
        if isinstance(row, dict):
            out.append(row)
    return out


def _select_scenarios(
    scenarios: List[Dict[str, Any]],
    start_index: int,
    max_scenarios: Optional[int],
    scenario_filter: str,
) -> List[Dict[str, Any]]:
    sliced = scenarios[max(0, start_index) :]
    if scenario_filter:
        needle = scenario_filter.lower()
        filtered: List[Dict[str, Any]] = []
        for row in sliced:
            hay = " ".join(
                [
                    _normalize_text(row.get("case_name_th")),
                    _normalize_text(row.get("case_name_en")),
                    _normalize_text(row.get("keywords")),
                ]
            ).lower()
            if needle in hay:
                filtered.append(row)
        sliced = filtered
    if max_scenarios is not None and max_scenarios >= 0:
        sliced = sliced[:max_scenarios]
    return sliced


def _build_summary(run_records: List[Dict[str, Any]]) -> Dict[str, Any]:
    style_counts: Dict[str, int] = {k: 0 for k in STYLE_KEYS}
    route_counts: Dict[str, int] = {}
    facility_type_counts: Dict[str, int] = {}
    failures = 0

    for record in run_records:
        style = _normalize_text(record.get("style"))
        workflow = record.get("workflow") or {}
        if record.get("error"):
            failures += 1

        route = _normalize_text(workflow.get("route")) or "unknown"
        route_counts[route] = route_counts.get(route, 0) + 1

        facility_type = _normalize_text(workflow.get("facility_type")) or "unknown"
        facility_type_counts[facility_type] = facility_type_counts.get(facility_type, 0) + 1

        if style in style_counts:
            style_counts[style] += 1

    total_runs = len(run_records)
    return {
        "total_runs": total_runs,
        "failed_runs": failures,
        "success_runs": max(0, total_runs - failures),
        "style_counts": style_counts,
        "route_counts": route_counts,
        "facility_type_counts": facility_type_counts,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate ByStander agent workflow with AI-generated prompt variants "
            "(calm, misspelled, panic) per scenario from general_first_aid_catalog.json."
        )
    )
    parser.add_argument(
        "--catalog",
        default=str(DEFAULT_CATALOG_PATH),
        help="Path to general_first_aid_catalog.json",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory where JSON outputs will be saved.",
    )
    parser.add_argument(
        "--output-prefix",
        default="agent_workflow_eval",
        help="Filename prefix for generated output files.",
    )
    parser.add_argument(
        "--start-index",
        type=int,
        default=0,
        help="Start index in catalog items list.",
    )
    parser.add_argument(
        "--max-scenarios",
        type=int,
        default=None,
        help="Maximum number of scenarios to evaluate (default: all).",
    )
    parser.add_argument(
        "--scenario-filter",
        default="",
        help="Optional keyword filter on case name/keywords.",
    )
    parser.add_argument(
        "--prompt-model",
        default=os.getenv("PROMPT_GENERATION_MODEL", DEFAULT_PROMPT_MODEL),
        help="OpenAI model for generating user prompts.",
    )
    parser.add_argument(
        "--openai-api-key",
        default=os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_KEY") or "",
        help="OpenAI API key for prompt generation and existing judge service.",
    )
    parser.add_argument(
        "--prompt-timeout",
        type=float,
        default=60.0,
        help="Timeout in seconds for prompt generation API call.",
    )
    parser.add_argument(
        "--prompt-temperature",
        type=float,
        default=0.6,
        help="Sampling temperature for prompt generation.",
    )
    parser.add_argument(
        "--latitude",
        type=float,
        default=None,
        help="Optional latitude for facility search in workflow runs.",
    )
    parser.add_argument(
        "--longitude",
        type=float,
        default=None,
        help="Optional longitude for facility search in workflow runs.",
    )
    parser.add_argument(
        "--user-id",
        default="",
        help="Optional user_id payload for profile-aware call scripts.",
    )
    parser.add_argument(
        "--strict-preflight",
        action="store_true",
        help="Fail fast if observability is not enabled.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_dotenv(PROJECT_ROOT / "bystander_backend" / ".env", override=True)
    observability_status = init_observability(service_name="bystander-evaluator")
    if args.strict_preflight and not bool(observability_status.get("enabled")):
        print("Preflight failed: observability is not enabled.", file=sys.stderr)
        if observability_status.get("error"):
            print(f"Observability error: {observability_status.get('error')}", file=sys.stderr)
        return 3

    catalog_path = Path(args.catalog).resolve()
    output_dir = Path(args.output_dir).resolve()
    if not catalog_path.exists():
        print(f"Catalog file not found: {catalog_path}", file=sys.stderr)
        return 2

    all_scenarios = _load_catalog(catalog_path)
    selected_scenarios = _select_scenarios(
        scenarios=all_scenarios,
        start_index=args.start_index,
        max_scenarios=args.max_scenarios,
        scenario_filter=_normalize_text(args.scenario_filter),
    )
    if not selected_scenarios:
        print("No scenarios selected. Adjust --start-index/--max-scenarios/--scenario-filter.")
        return 1

    workflow = ByStanderWorkflow()
    prompt_agent = PromptGenerationAgent(
        api_key=_normalize_text(args.openai_api_key),
        model=args.prompt_model,
        timeout_s=args.prompt_timeout,
        temperature=args.prompt_temperature,
    )
    workflow_agent = MainWorkflowAgent(
        workflow=workflow,
        latitude=_safe_float(args.latitude),
        longitude=_safe_float(args.longitude),
        user_id=args.user_id,
    )
    facility_writer = FacilityLogWriter()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir.mkdir(parents=True, exist_ok=True)
    run_records: List[Dict[str, Any]] = []
    run_id = 0

    run_started = time.perf_counter()
    total_runs = len(selected_scenarios) * len(STYLE_KEYS)
    print(f"Selected scenarios: {len(selected_scenarios)}")
    print(f"Planned prompt runs: {total_runs} (3 styles per scenario)")
    print(f"Prompt generation model: {prompt_agent.model}")
    print(f"Prompt generator API enabled: {prompt_agent.enabled}")
    print(f"Judge service enabled: {workflow.judge_service.enabled}")
    print(f"Observability enabled: {bool(observability_status.get('enabled'))}")
    if observability_status.get("error"):
        print(f"Observability error: {observability_status.get('error')}")
    print("Direct evaluator judging: disabled (workflow judge_service.py only)")

    for scenario_index, scenario in enumerate(selected_scenarios, start=1):
        prompts_by_style, prompt_meta = prompt_agent.generate_prompts(scenario)
        case_name = _normalize_text(scenario.get("case_name_th") or scenario.get("case_name_en"))
        print(f"[{scenario_index}/{len(selected_scenarios)}] scenario: {case_name}")

        for style in STYLE_KEYS:
            run_id += 1
            prompt_text = _normalize_text(prompts_by_style.get(style))
            if not prompt_text:
                prompt_text = f"ช่วยแนะนำปฐมพยาบาลกรณี{case_name}ให้หน่อยครับ"

            print(f"  - run {run_id}/{total_runs}: style={style}")
            run_record: Dict[str, Any] = {
                "run_id": run_id,
                "timestamp": datetime.now().isoformat(),
                "scenario": {
                    "scenario_index": scenario_index - 1,
                    "case_name_th": _normalize_text(scenario.get("case_name_th")),
                    "case_name_en": _normalize_text(scenario.get("case_name_en")),
                    "severity": _normalize_text(scenario.get("severity")),
                    "facility_type": _normalize_text(scenario.get("facility_type")),
                    "keywords": _normalize_text(scenario.get("keywords")),
                },
                "style": style,
                "prompt": prompt_text,
                "prompt_generation_meta": prompt_meta,
                "workflow_elapsed_ms": 0,
                "workflow": {},
                "judge_mode": "workflow_async_only",
                "error": "",
            }

            try:
                workflow_result, elapsed_ms = workflow_agent.run(prompt_text)
                run_record["workflow_elapsed_ms"] = elapsed_ms
                run_record["workflow"] = workflow_result
            except Exception as exc:
                run_record["error"] = f"workflow_error: {exc}"
                run_records.append(run_record)
                facility_writer.add_run_record(run_record)
                continue

            run_records.append(run_record)
            facility_writer.add_run_record(run_record)

    elapsed_total_ms = int((time.perf_counter() - run_started) * 1000)
    summary = _build_summary(run_records)

    result_payload = {
        "config": {
            "timestamp": timestamp,
            "catalog_path": str(catalog_path),
            "selected_scenarios": len(selected_scenarios),
            "styles_per_scenario": list(STYLE_KEYS),
            "prompt_model": prompt_agent.model,
            "prompt_api_enabled": prompt_agent.enabled,
            "judge_model": workflow.judge_service.model,
            "judge_enabled": workflow.judge_service.enabled,
            "judge_mode": "workflow_async_only",
            "latitude": _safe_float(args.latitude),
            "longitude": _safe_float(args.longitude),
            "user_id_provided": bool(_normalize_text(args.user_id)),
            "elapsed_total_ms": elapsed_total_ms,
        },
        "summary": summary,
        "runs": run_records,
    }

    main_output_path = output_dir / f"{args.output_prefix}_{timestamp}.json"
    with main_output_path.open("w", encoding="utf-8") as f:
        json.dump(result_payload, f, ensure_ascii=False, indent=2)

    facility_dir = output_dir / f"{args.output_prefix}_{timestamp}_facilities"
    facility_files = facility_writer.write(facility_dir)
    facility_index_payload = {
        "timestamp": timestamp,
        "main_output": str(main_output_path),
        "facility_log_dir": str(facility_dir),
        "facility_log_files": facility_files,
        "total_facility_files": len(facility_files),
    }
    facility_index_path = output_dir / f"{args.output_prefix}_{timestamp}_facility_index.json"
    with facility_index_path.open("w", encoding="utf-8") as f:
        json.dump(facility_index_payload, f, ensure_ascii=False, indent=2)

    print()
    print("Evaluation complete")
    print(f"Main result JSON: {main_output_path}")
    print(f"Facility logs dir: {facility_dir}")
    print(f"Facility index JSON: {facility_index_path}")
    print(f"Runs: {summary['total_runs']} | Failed: {summary['failed_runs']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
