#!/usr/bin/env python3
import argparse
import asyncio
import csv
import hashlib
import json
import os
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import requests
except Exception:  # pragma: no cover
    requests = None  # type: ignore[assignment]
from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_INSTRUCTIONS_CSV = ROOT_DIR / "ml" / "finetuning" / "instructions_raw_final.csv"
DEFAULT_PROMPTS_CSV = ROOT_DIR / "generated_prompts.csv"
DEFAULT_RESULTS_JSON = ROOT_DIR / "evaluation_results.json"
DEFAULT_BYSTANDER_BASE_URL = os.getenv("BYSTANDER_API_BASE_URL") or "http://127.0.0.1:5003"
PROMPT_STYLES = ("panic", "calm", "misspelled")
SCENARIO_TARGETS = {"critical": 36, "moderate": 36, "none": 3}
SEVERITY_MAP = {
    "critical": "critical",
    "moderate": "moderate",
    "mild": "moderate",
    "no need": "none",
    "none": "none",
    "non-emergency": "none",
    "non_emergency": "none",
}
DEFAULT_LATITUDE = 13.7563
DEFAULT_LONGITUDE = 100.5018
THAILAND_COORDINATE_POOL = [
    {"label": "Bangkok", "latitude": 13.7563, "longitude": 100.5018},
    {"label": "Chiang Mai", "latitude": 18.7883, "longitude": 98.9853},
    {"label": "Chiang Rai", "latitude": 19.9105, "longitude": 99.8406},
    {"label": "Phuket", "latitude": 7.8804, "longitude": 98.3923},
    {"label": "Pattaya", "latitude": 12.9236, "longitude": 100.8825},
    {"label": "Khon Kaen", "latitude": 16.4322, "longitude": 102.8236},
    {"label": "Nakhon Ratchasima", "latitude": 14.9799, "longitude": 102.0977},
    {"label": "Udon Thani", "latitude": 17.4138, "longitude": 102.7870},
    {"label": "Hat Yai", "latitude": 7.0084, "longitude": 100.4747},
    {"label": "Surat Thani", "latitude": 9.1382, "longitude": 99.3215},
    {"label": "Hua Hin", "latitude": 12.5684, "longitude": 99.9577},
    {"label": "Ayutthaya", "latitude": 14.3532, "longitude": 100.5689},
    {"label": "Kanchanaburi", "latitude": 14.0228, "longitude": 99.5328},
    {"label": "Sukhothai", "latitude": 17.0056, "longitude": 99.8264},
    {"label": "Nakhon Si Thammarat", "latitude": 8.4304, "longitude": 99.9631},
    {"label": "Ubon Ratchathani", "latitude": 15.2448, "longitude": 104.8473},
    {"label": "Mae Sot", "latitude": 16.7167, "longitude": 98.5741},
    {"label": "Lampang", "latitude": 18.2888, "longitude": 99.4908},
    {"label": "Trat", "latitude": 12.2436, "longitude": 102.5151},
    {"label": "Narathiwat", "latitude": 6.4264, "longitude": 101.8253},
]
GENERATOR_SYSTEM_PROMPT = (
    "You create Thai emergency-evaluation prompts for a first-aid assistant. "
    "Ground every prompt in the provided first-aid protocol summary. "
    "Keep the case clinically consistent with the reference and do not invent a different emergency. "
    "Return strict JSON only."
)
JUDGE_SYSTEM_PROMPT = (
    "You are a strict first-aid QA judge. Score conservatively. "
    "Use only the supplied scenario, reference protocol, facility list, and script text. "
    "If evidence is missing, do not give credit. Return strict JSON only."
)
OPENAI_GENERATION_MODEL = os.getenv("OPENAI_GENERATION_MODEL") or "gpt-5.2"
OPENAI_JUDGE_MODEL = os.getenv("OPENAI_JUDGE_MODEL") or "gpt-5.2"
ANTHROPIC_JUDGE_MODEL = os.getenv("ANTHROPIC_JUDGE_MODEL") or "claude-opus-4-1"


@dataclass(frozen=True)
class ScenarioSeed:
    severity: str
    topic: str
    topic_en: str
    instructions: str
    keywords: str
    facility_type: str


class RetryableError(RuntimeError):
    pass


def normalize_text(value: Any) -> str:
    return str(value or "").strip()


def dedupe_nonempty(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        item = normalize_text(value)
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def normalize_source_severity(value: Any) -> str:
    raw = normalize_text(value).lower()
    return SEVERITY_MAP.get(raw, "moderate")


def slugify(value: str) -> str:
    cleaned = []
    for char in normalize_text(value).lower():
        if char.isalnum():
            cleaned.append(char)
        elif cleaned and cleaned[-1] != "-":
            cleaned.append("-")
    return "".join(cleaned).strip("-") or "scenario"


def load_environment() -> None:
    for env_path in (
        ROOT_DIR / ".env",
        ROOT_DIR / "bystander_backend" / ".env",
        ROOT_DIR / "ml_evaluation" / ".env",
    ):
        if env_path.exists():
            load_dotenv(env_path, override=False)


def load_protocol_seeds(csv_path: Path) -> list[ScenarioSeed]:
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)

    deduped: dict[tuple[str, str], ScenarioSeed] = {}
    for row in rows:
        severity = normalize_source_severity(row.get("severity"))
        topic = normalize_text(row.get("Case Name (TH)")) or normalize_text(row.get("Case Name (EN)"))
        if not topic:
            continue
        instructions = normalize_text(row.get("Instructions"))
        if not instructions:
            continue
        seed = ScenarioSeed(
            severity=severity,
            topic=topic,
            topic_en=normalize_text(row.get("Case Name (EN)")),
            instructions=instructions,
            keywords=normalize_text(row.get("Keywords")),
            facility_type=normalize_text(row.get("facility_type")).lower() or "clinic",
        )
        key = (severity, topic.lower())
        if key not in deduped:
            deduped[key] = seed
    return list(deduped.values())


def select_scenario_seeds(all_seeds: list[ScenarioSeed], seed_value: int) -> list[ScenarioSeed]:
    rng = random.Random(seed_value)
    buckets: dict[str, list[ScenarioSeed]] = {key: [] for key in SCENARIO_TARGETS}
    for item in all_seeds:
        if item.severity in buckets:
            buckets[item.severity].append(item)
    selected: list[ScenarioSeed] = []
    for severity, target_count in SCENARIO_TARGETS.items():
        bucket = list(buckets[severity])
        rng.shuffle(bucket)
        if len(bucket) < target_count:
            raise ValueError(
                f"Not enough protocol seeds for severity '{severity}': "
                f"need {target_count}, found {len(bucket)}"
            )
        selected.extend(bucket[:target_count])
    return selected


def batch_items(items: list[Any], batch_size: int) -> list[list[Any]]:
    return [items[index : index + batch_size] for index in range(0, len(items), batch_size)]


def build_generation_schema(batch_size: int) -> dict[str, Any]:
    item_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "scenario_topic": {"type": "string"},
            "severity": {"type": "string", "enum": ["critical", "moderate", "none"]},
            "panic": {"type": "string"},
            "calm": {"type": "string"},
            "misspelled": {"type": "string"},
        },
        "required": ["scenario_topic", "severity", "panic", "calm", "misspelled"],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "items": {
                "type": "array",
                "minItems": batch_size,
                "maxItems": batch_size,
                "items": item_schema,
            }
        },
        "required": ["items"],
    }


def build_generation_user_prompt(batch: list[ScenarioSeed]) -> str:
    lines = [
        "Generate one Thai scenario for each protocol seed below.",
        "For every seed, return exactly three variants:",
        "- panic: urgent, emotional, fragmented language",
        "- calm: clear, composed, structured language",
        "- misspelled: realistic Thai texting typos or phonetic misspellings while remaining understandable",
        "Do not mention severity labels in the prompt text.",
        "Keep each prompt to 1-3 sentences.",
        "Do not copy the protocol verbatim; describe the incident from the caller perspective.",
        "Seeds:",
    ]
    for index, item in enumerate(batch, start=1):
        lines.append(
            json.dumps(
                {
                    "index": index,
                    "scenario_topic": item.topic,
                    "topic_en": item.topic_en,
                    "severity": item.severity,
                    "facility_type": item.facility_type,
                    "keywords": item.keywords,
                    "reference_protocol": item.instructions,
                },
                ensure_ascii=False,
            )
        )
    return "\n".join(lines)


def extract_openai_message_content(payload: dict[str, Any]) -> str:
    try:
        message = payload["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Unexpected OpenAI response shape: {payload}") from exc
    refusal = normalize_text(message.get("refusal"))
    if refusal:
        raise RuntimeError(f"OpenAI refused structured output: {refusal}")
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(normalize_text(item.get("text")))
        text = "\n".join(part for part in parts if part)
        if text:
            return text
    raise RuntimeError(f"OpenAI returned empty structured content: {payload}")


def extract_json(text: str) -> dict[str, Any]:
    stripped = normalize_text(text)
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise RuntimeError(f"Response did not contain JSON: {text}")
    snippet = stripped[start : end + 1]
    parsed = json.loads(snippet)
    if not isinstance(parsed, dict):
        raise RuntimeError(f"Expected JSON object but got: {parsed}")
    return parsed


def build_openai_model_candidates(primary_model: str) -> list[str]:
    return dedupe_nonempty(
        [
            primary_model,
            "gpt-5.2",
            "gpt-5.2-chat-latest",
            "gpt-5-mini",
        ]
    )


def post_json_with_retry(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    payload: dict[str, Any],
    timeout_s: float,
    retries: int,
    retry_label: str,
) -> dict[str, Any]:
    if requests is None:
        raise RuntimeError("requests is unavailable in this Python environment")
    headers = headers or {}
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=timeout_s)
            body_preview = response.text[:500]
            if response.status_code >= 500 or response.status_code == 429:
                raise RetryableError(
                    f"{retry_label} failed with {response.status_code}: {body_preview}"
                )
            if response.status_code >= 400:
                raise RuntimeError(
                    f"{retry_label} failed with {response.status_code}: {body_preview}"
                )
            data = response.json()
            if not isinstance(data, dict):
                raise RuntimeError(f"{retry_label} returned non-object JSON: {data}")
            return data
        except (requests.RequestException, RetryableError, ValueError, RuntimeError) as exc:
            last_error = exc
            if isinstance(exc, RuntimeError) and not isinstance(exc, RetryableError):
                break
            if attempt == retries:
                break
            sleep_s = min(2 ** (attempt - 1), 8)
            print(f"[{retry_label}] retry {attempt}/{retries} after error: {exc}")
            time.sleep(sleep_s)
    raise RuntimeError(f"{retry_label} failed after {retries} attempts: {last_error}")


def call_openai_structured(
    *,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    schema_name: str,
    schema: dict[str, Any],
    timeout_s: float,
    retries: int,
    temperature: float,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for candidate_model in build_openai_model_candidates(model):
        payload = {
            "model": candidate_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": schema,
                },
            },
        }
        try:
            response = post_json_with_retry(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                payload=payload,
                timeout_s=timeout_s,
                retries=retries,
                retry_label=f"openai:{schema_name}:{candidate_model}",
            )
            return extract_json(extract_openai_message_content(response))
        except RuntimeError as exc:
            last_error = exc
            error_text = normalize_text(exc).lower()
            if candidate_model != model:
                print(f"[openai:{schema_name}] fallback model failed: {candidate_model}: {exc}")
            if (
                " 404" in error_text
                or "does not exist" in error_text
                or "not found" in error_text
                or "model_not_found" in error_text
                or "unsupported" in error_text
            ):
                print(f"[openai:{schema_name}] falling back from {candidate_model}")
                continue
            raise
    raise RuntimeError(f"OpenAI structured call failed for all models: {last_error}")


def call_claude_tool(
    *,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    tool_name: str,
    tool_schema: dict[str, Any],
    timeout_s: float,
    retries: int,
) -> dict[str, Any]:
    payload = {
        "model": model,
        "max_tokens": 4000,
        "temperature": 0,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}],
        "tools": [
            {
                "name": tool_name,
                "description": "Return the evaluation strictly as structured JSON.",
                "input_schema": tool_schema,
            }
        ],
        "tool_choice": {"type": "tool", "name": tool_name},
    }
    response = post_json_with_retry(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        payload=payload,
        timeout_s=timeout_s,
        retries=retries,
        retry_label=f"claude:{tool_name}",
    )
    content = response.get("content") or []
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                tool_input = block.get("input")
                if isinstance(tool_input, dict):
                    return tool_input
    raise RuntimeError(f"Claude did not return tool output: {response}")


def build_prompt_row_id(seed: ScenarioSeed, scenario_index: int, prompt_style: str) -> str:
    return f"{scenario_index:03d}-{slugify(seed.topic)}-{prompt_style}"


def materialize_prompt_rows(
    generation_output: list[dict[str, Any]],
    batch: list[ScenarioSeed],
    topic_order: dict[tuple[str, str], int],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for seed, generated in zip(batch, generation_output, strict=True):
        severity = normalize_text(generated.get("severity")).lower() or seed.severity
        topic = normalize_text(generated.get("scenario_topic")) or seed.topic
        scenario_index = topic_order[(seed.severity, seed.topic.lower())]
        for prompt_style in PROMPT_STYLES:
            rows.append(
                {
                    "id": build_prompt_row_id(seed, scenario_index, prompt_style),
                    "severity": severity,
                    "prompt_style": prompt_style,
                    "scenario_topic": topic,
                    "prompt_text": normalize_text(generated.get(prompt_style)),
                }
            )
    return rows


def write_generated_prompts(rows: list[dict[str, str]], output_path: Path) -> None:
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["id", "severity", "prompt_style", "scenario_topic", "prompt_text"],
        )
        writer.writeheader()
        writer.writerows(rows)


def read_generated_prompts(input_path: Path) -> list[dict[str, str]]:
    with input_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [
            {
                "id": normalize_text(row.get("id")),
                "severity": normalize_text(row.get("severity")).lower(),
                "prompt_style": normalize_text(row.get("prompt_style")).lower(),
                "scenario_topic": normalize_text(row.get("scenario_topic")),
                "prompt_text": normalize_text(row.get("prompt_text")),
            }
            for row in reader
        ]


def load_existing_results(results_path: Path) -> dict[str, dict[str, Any]]:
    if not results_path.exists():
        return {}
    payload = json.loads(results_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Expected JSON array in {results_path}")
    results: dict[str, dict[str, Any]] = {}
    for item in payload:
        if isinstance(item, dict) and normalize_text(item.get("id")):
            results[normalize_text(item["id"])] = item
    return results


def save_results(results: dict[str, dict[str, Any]], output_path: Path) -> None:
    ordered = [results[key] for key in sorted(results.keys())]
    output_path.write_text(json.dumps(ordered, ensure_ascii=False, indent=2), encoding="utf-8")


def build_reference_lookup(seeds: list[ScenarioSeed]) -> dict[tuple[str, str], ScenarioSeed]:
    return {(seed.severity, seed.topic.lower()): seed for seed in seeds}


def find_reference_seed(
    row: dict[str, str],
    lookup: dict[tuple[str, str], ScenarioSeed],
    all_seeds: list[ScenarioSeed],
) -> ScenarioSeed | None:
    key = (row["severity"], row["scenario_topic"].lower())
    if key in lookup:
        return lookup[key]
    for seed in all_seeds:
        if seed.topic.lower() == row["scenario_topic"].lower():
            return seed
    return None


def build_bystander_payload(row: dict[str, str], latitude: float | None, longitude: float | None) -> dict[str, Any]:
    payload: dict[str, Any] = {"scenario": row["prompt_text"]}
    if latitude is not None and longitude is not None:
        payload["latitude"] = latitude
        payload["longitude"] = longitude
    return payload


def coordinate_context_for_row(
    row_id: str,
    *,
    coordinate_mode: str,
    coordinate_seed: int,
    fixed_latitude: float | None,
    fixed_longitude: float | None,
) -> dict[str, Any]:
    if coordinate_mode != "random-thailand":
        return {
            "label": "fixed",
            "latitude": fixed_latitude,
            "longitude": fixed_longitude,
        }
    digest = hashlib.sha256(f"{coordinate_seed}:{row_id}".encode("utf-8")).hexdigest()
    pool_index = int(digest[:8], 16) % len(THAILAND_COORDINATE_POOL)
    selected = THAILAND_COORDINATE_POOL[pool_index]
    return dict(selected)


async def call_bystander_endpoint(
    base_url: str,
    endpoint: str,
    payload: dict[str, Any],
    timeout_s: float,
    retries: int,
) -> dict[str, Any]:
    return await asyncio.to_thread(
        post_json_with_retry,
        f"{base_url.rstrip('/')}{endpoint}",
        payload=payload,
        timeout_s=timeout_s,
        retries=retries,
        retry_label=f"bystander:{endpoint}",
    )


async def fetch_bystander_response(
    row: dict[str, str],
    *,
    base_url: str,
    latitude: float | None,
    longitude: float | None,
    timeout_s: float,
    retries: int,
    evaluation_scope: str,
) -> dict[str, Any]:
    workflow_payload = build_bystander_payload(row, latitude, longitude)
    workflow_result = await call_bystander_endpoint(
        base_url,
        "/agent_workflow",
        workflow_payload,
        timeout_s,
        retries,
    )
    severity = normalize_text(workflow_result.get("severity")).lower() or row["severity"]
    facility_type = normalize_text(workflow_result.get("facility_type")).lower()
    followup_payload = {
        **workflow_payload,
        "severity": severity,
        "facility_type": facility_type,
        "guidance": normalize_text(workflow_result.get("guidance")),
        "route": normalize_text(workflow_result.get("route")),
        "is_emergency": bool(workflow_result.get("is_emergency")),
    }
    facilities_task = asyncio.create_task(
        call_bystander_endpoint(base_url, "/find_facilities", followup_payload, timeout_s, retries)
    )
    if evaluation_scope == "facilities-only":
        facilities_result = await facilities_task
        script_result: dict[str, Any] = {}
    else:
        script_task = asyncio.create_task(
            call_bystander_endpoint(base_url, "/call_script", followup_payload, timeout_s, retries)
        )
        facilities_result, script_result = await asyncio.gather(facilities_task, script_task)
    facilities = facilities_result.get("facilities") if isinstance(facilities_result, dict) else []
    if not isinstance(facilities, list):
        facilities = []
    return {
        "guidance_text": normalize_text(workflow_result.get("guidance")),
        "facilities": facilities,
        "script_text": normalize_text(script_result.get("call_script")),
    }


def build_judge_schema() -> dict[str, Any]:
    facility_score = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "facility_name": {"type": "string"},
            "relevance_score": {"type": "number", "minimum": 0, "maximum": 1},
            "open_score": {"type": "number", "minimum": 0, "maximum": 1},
            "weighted_score_percent": {"type": "number", "minimum": 0, "maximum": 20},
        },
        "required": [
            "facility_name",
            "relevance_score",
            "open_score",
            "weighted_score_percent",
        ],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "guidance": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "compliance": {"type": "integer", "minimum": 1, "maximum": 5},
                    "correctness": {"type": "integer", "minimum": 1, "maximum": 5},
                    "readability": {"type": "integer", "minimum": 1, "maximum": 5},
                },
                "required": ["compliance", "correctness", "readability"],
            },
            "facilities": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "facility_scores": {
                        "type": "array",
                        "maxItems": 5,
                        "items": facility_score,
                    },
                    "total_score_percent": {"type": "number", "minimum": 0, "maximum": 100},
                },
                "required": ["facility_scores", "total_score_percent"],
            },
            "script": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "rule_scores": {
                        "type": "array",
                        "minItems": 9,
                        "maxItems": 9,
                        "items": {"type": "number", "minimum": 0, "maximum": 1},
                    },
                    "total_compliance": {"type": "number", "minimum": 0, "maximum": 9},
                },
                "required": ["rule_scores", "total_compliance"],
            },
        },
        "required": ["guidance", "facilities", "script"],
    }


def build_facilities_only_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "facilities": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "facility_scores": {
                        "type": "array",
                        "maxItems": 5,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "facility_name": {"type": "string"},
                                "relevance_score": {"type": "number", "minimum": 0, "maximum": 1},
                                "open_score": {"type": "number", "minimum": 0, "maximum": 1},
                                "weighted_score_percent": {"type": "number", "minimum": 0, "maximum": 20},
                            },
                            "required": [
                                "facility_name",
                                "relevance_score",
                                "open_score",
                                "weighted_score_percent",
                            ],
                        },
                    },
                    "total_score_percent": {"type": "number", "minimum": 0, "maximum": 100},
                },
                "required": ["facility_scores", "total_score_percent"],
            }
        },
        "required": ["facilities"],
    }


def build_judge_prompt(
    row: dict[str, str],
    ai_response: dict[str, Any],
    reference_seed: ScenarioSeed | None,
    coordinate_context: dict[str, Any],
) -> str:
    reference_protocol = reference_seed.instructions if reference_seed else "No reference protocol found."
    reference_facility = reference_seed.facility_type if reference_seed else "unknown"
    latitude = coordinate_context.get("latitude")
    longitude = coordinate_context.get("longitude")
    location_label = normalize_text(coordinate_context.get("label"))
    location_note = (
        f"Evaluation coordinates supplied to the app: {latitude}, {longitude} ({location_label})."
        if latitude is not None and longitude is not None
        else "No coordinates were supplied to the app; facilities and precise location evidence may be missing."
    )
    facilities_note = (
        "Treat facility fields `is_open` or `open_now` as evidence for whether the facility is currently open. "
        "If neither field is present, give 0 for open_score for that facility."
    )
    return "\n".join(
        [
            "Evaluate the ByStander AI response using the provided rubric.",
            f"Scenario topic: {row['scenario_topic']}",
            f"Prompt severity label: {row['severity']}",
            f"Prompt style: {row['prompt_style']}",
            f"User prompt: {row['prompt_text']}",
            f"Reference protocol: {reference_protocol}",
            f"Reference facility type: {reference_facility}",
            location_note,
            facilities_note,
            "Guidance rubric: score compliance, correctness, readability from 1-5.",
            "Facilities rubric: up to 5 facilities. relevance_score and open_score are each 0-1. weighted_score_percent = (relevance_score * 10) + (open_score * 10). total_score_percent = sum of facility weighted scores.",
            "Script rubric: score these 9 protocol rules as 0-1 each, allow partial credit, and total_compliance must equal the sum:",
            "1) ตั้งสติ และโทรแจ้ง 1669",
            "2) ให้ข้อมูลว่าเกิดเหตุอะไร",
            "3) บอกสถานที่เกิดเหตุให้ชัดเจน",
            "4) บอกเพศ อายุ อาการ จำนวน",
            "5) บอกระดับความรู้สึกตัว",
            "6) บอกความเสี่ยงที่อาจเกิดซ้ำ",
            "7) บอกชื่อผู้แจ้ง + เบอร์โทรศัพท์",
            "8) ช่วยเหลือเบื้องต้น",
            "9) รอทีมกู้ชีพมารับเพื่อนำส่งโรงพยาบาล",
            "If location context is provided, judge the location line based on whether it was converted into a human place description rather than raw coordinates.",
            f"Guidance text: {ai_response['guidance_text']}",
            f"Facilities JSON: {json.dumps(ai_response['facilities'], ensure_ascii=False)}",
            f"Script text: {ai_response['script_text']}",
        ]
    )


def build_facilities_only_judge_prompt(
    row: dict[str, str],
    ai_response: dict[str, Any],
    reference_seed: ScenarioSeed | None,
    coordinate_context: dict[str, Any],
) -> str:
    reference_facility = reference_seed.facility_type if reference_seed else "unknown"
    latitude = coordinate_context.get("latitude")
    longitude = coordinate_context.get("longitude")
    location_label = normalize_text(coordinate_context.get("label"))
    location_note = (
        f"Evaluation coordinates supplied to the app: {latitude}, {longitude} ({location_label})."
        if latitude is not None and longitude is not None
        else "No coordinates were supplied to the app."
    )
    return "\n".join(
        [
            "Evaluate only the facility recommendations from the ByStander AI response.",
            f"Scenario topic: {row['scenario_topic']}",
            f"Prompt severity label: {row['severity']}",
            f"Prompt style: {row['prompt_style']}",
            f"User prompt: {row['prompt_text']}",
            f"Reference facility type: {reference_facility}",
            location_note,
            "Treat facility fields `is_open` or `open_now` as evidence for whether the facility is currently open.",
            "If neither field is present, give 0 for open_score for that facility.",
            "Score only the facilities section.",
            "Facilities rubric: up to 5 facilities. relevance_score and open_score are each 0-1. weighted_score_percent = (relevance_score * 10) + (open_score * 10). total_score_percent = sum of facility weighted scores.",
            f"Facilities JSON: {json.dumps(ai_response['facilities'], ensure_ascii=False)}",
        ]
    )


async def run_openai_judge(
    row: dict[str, str],
    ai_response: dict[str, Any],
    reference_seed: ScenarioSeed | None,
    *,
    api_key: str,
    model: str,
    timeout_s: float,
    retries: int,
    coordinate_context: dict[str, Any],
    evaluation_scope: str,
) -> dict[str, Any]:
    if evaluation_scope == "facilities-only":
        schema = build_facilities_only_schema()
        user_prompt = build_facilities_only_judge_prompt(
            row,
            ai_response,
            reference_seed,
            coordinate_context,
        )
    else:
        schema = build_judge_schema()
        user_prompt = build_judge_prompt(row, ai_response, reference_seed, coordinate_context)
    return await asyncio.to_thread(
        call_openai_structured,
        api_key=api_key,
        model=model,
        system_prompt=JUDGE_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        schema_name="bystander_eval",
        schema=schema,
        timeout_s=timeout_s,
        retries=retries,
        temperature=0.0,
    )


async def run_claude_judge(
    row: dict[str, str],
    ai_response: dict[str, Any],
    reference_seed: ScenarioSeed | None,
    *,
    api_key: str,
    model: str,
    timeout_s: float,
    retries: int,
    coordinate_context: dict[str, Any],
    evaluation_scope: str,
) -> dict[str, Any]:
    if evaluation_scope == "facilities-only":
        tool_schema = build_facilities_only_schema()
        user_prompt = build_facilities_only_judge_prompt(
            row,
            ai_response,
            reference_seed,
            coordinate_context,
        )
    else:
        tool_schema = build_judge_schema()
        user_prompt = build_judge_prompt(row, ai_response, reference_seed, coordinate_context)
    return await asyncio.to_thread(
        call_claude_tool,
        api_key=api_key,
        model=model,
        system_prompt=JUDGE_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        tool_name="record_bystander_eval",
        tool_schema=tool_schema,
        timeout_s=timeout_s,
        retries=retries,
    )


def coerce_judge_output(payload: dict[str, Any]) -> dict[str, Any]:
    guidance = payload.get("guidance") if isinstance(payload.get("guidance"), dict) else {}
    facilities = payload.get("facilities") if isinstance(payload.get("facilities"), dict) else {}
    script = payload.get("script") if isinstance(payload.get("script"), dict) else {}

    facility_scores = facilities.get("facility_scores")
    if not isinstance(facility_scores, list):
        facility_scores = []
    normalized_facilities = []
    total_score = 0.0
    for item in facility_scores[:5]:
        if not isinstance(item, dict):
            continue
        relevance_score = max(0.0, min(1.0, float(item.get("relevance_score", 0) or 0)))
        open_score = max(0.0, min(1.0, float(item.get("open_score", 0) or 0)))
        weighted_score = round(max(0.0, min(20.0, float(item.get("weighted_score_percent", 0) or 0))), 2)
        normalized_facilities.append(
            {
                "facility_name": normalize_text(item.get("facility_name")),
                "relevance_score": round(relevance_score, 2),
                "open_score": round(open_score, 2),
                "weighted_score_percent": weighted_score,
            }
        )
        total_score += weighted_score

    raw_rule_scores = script.get("rule_scores") if isinstance(script.get("rule_scores"), list) else []
    rule_scores = [round(max(0.0, min(1.0, float(value or 0))), 2) for value in raw_rule_scores[:9]]
    while len(rule_scores) < 9:
        rule_scores.append(0.0)

    return {
        "guidance": {
            "compliance": max(1, min(5, int(guidance.get("compliance", 1) or 1))),
            "correctness": max(1, min(5, int(guidance.get("correctness", 1) or 1))),
            "readability": max(1, min(5, int(guidance.get("readability", 1) or 1))),
        },
        "facilities": {
            "facility_scores": normalized_facilities,
            "total_score_percent": round(max(0.0, min(100.0, total_score)), 2),
        },
        "script": {
            "rule_scores": rule_scores,
            "total_compliance": round(sum(rule_scores), 2),
        },
    }


def merge_judge_output(
    existing_judge: dict[str, Any] | None,
    new_judge: dict[str, Any],
    evaluation_scope: str,
) -> dict[str, Any]:
    if evaluation_scope != "facilities-only":
        return new_judge
    merged = dict(existing_judge) if isinstance(existing_judge, dict) else {}
    merged["facilities"] = new_judge["facilities"]
    return merged


async def evaluate_row(
    row: dict[str, str],
    *,
    base_url: str,
    openai_api_key: str,
    anthropic_api_key: str,
    openai_judge_model: str,
    anthropic_judge_model: str,
    request_timeout_s: float,
    judge_timeout_s: float,
    retries: int,
    reference_lookup: dict[tuple[str, str], ScenarioSeed],
    all_seeds: list[ScenarioSeed],
    coordinate_context: dict[str, Any],
    evaluation_scope: str,
    existing_result: dict[str, Any] | None,
) -> dict[str, Any]:
    print(f"Evaluating {row['id']}")
    latitude = coordinate_context.get("latitude")
    longitude = coordinate_context.get("longitude")
    bystander_ai_response = await fetch_bystander_response(
        row,
        base_url=base_url,
        latitude=latitude,
        longitude=longitude,
        timeout_s=request_timeout_s,
        retries=retries,
        evaluation_scope=evaluation_scope,
    )
    reference_seed = find_reference_seed(row, reference_lookup, all_seeds)
    existing_evaluation = (
        existing_result.get("evaluation")
        if isinstance(existing_result, dict) and isinstance(existing_result.get("evaluation"), dict)
        else {}
    )
    gpt_task = asyncio.create_task(
        run_openai_judge(
            row,
            bystander_ai_response,
            reference_seed,
            api_key=openai_api_key,
            model=openai_judge_model,
            timeout_s=judge_timeout_s,
            retries=retries,
            coordinate_context=coordinate_context,
            evaluation_scope=evaluation_scope,
        )
    )
    claude_task = asyncio.create_task(
        run_claude_judge(
            row,
            bystander_ai_response,
            reference_seed,
            api_key=anthropic_api_key,
            model=anthropic_judge_model,
            timeout_s=judge_timeout_s,
            retries=retries,
            coordinate_context=coordinate_context,
            evaluation_scope=evaluation_scope,
        )
    )
    gpt_judge_raw, claude_judge_raw = await asyncio.gather(
        gpt_task,
        claude_task,
        return_exceptions=True,
    )
    print(f"Finished {row['id']}")
    evaluation: dict[str, Any] = {}
    if isinstance(gpt_judge_raw, Exception):
        evaluation["gpt_judge"] = existing_evaluation.get("gpt_judge")
        evaluation["gpt_judge_error"] = str(gpt_judge_raw)
    else:
        evaluation["gpt_judge"] = merge_judge_output(
            existing_evaluation.get("gpt_judge")
            if isinstance(existing_evaluation.get("gpt_judge"), dict)
            else None,
            coerce_judge_output(gpt_judge_raw),
            evaluation_scope,
        )
    if isinstance(claude_judge_raw, Exception):
        evaluation["claude_judge"] = existing_evaluation.get("claude_judge")
        evaluation["claude_judge_error"] = str(claude_judge_raw)
    else:
        evaluation["claude_judge"] = merge_judge_output(
            existing_evaluation.get("claude_judge")
            if isinstance(existing_evaluation.get("claude_judge"), dict)
            else None,
            coerce_judge_output(claude_judge_raw),
            evaluation_scope,
        )
    return {
        **row,
        "evaluation_coordinates": coordinate_context,
        "bystander_ai_response": bystander_ai_response,
        "evaluation": evaluation,
        "evaluation_scope": evaluation_scope,
    }


async def generate_prompts_async(args: argparse.Namespace) -> list[dict[str, str]]:
    if not args.openai_api_key:
        raise ValueError("OPENAI_API_KEY is required for prompt generation")
    all_seeds = load_protocol_seeds(Path(args.instructions_csv))
    selected_seeds = select_scenario_seeds(all_seeds, args.seed)
    topic_order = {
        (seed.severity, seed.topic.lower()): index
        for index, seed in enumerate(selected_seeds, start=1)
    }
    rows: list[dict[str, str]] = []
    for batch_index, batch in enumerate(batch_items(selected_seeds, args.generation_batch_size), start=1):
        print(f"Generating prompt batch {batch_index}")
        payload = await asyncio.to_thread(
            call_openai_structured,
            api_key=args.openai_api_key,
            model=args.openai_generation_model,
            system_prompt=GENERATOR_SYSTEM_PROMPT,
            user_prompt=build_generation_user_prompt(batch),
            schema_name="generated_prompt_batch",
            schema=build_generation_schema(len(batch)),
            timeout_s=args.generation_timeout_s,
            retries=args.retries,
            temperature=0.6,
        )
        items = payload.get("items") if isinstance(payload.get("items"), list) else []
        if len(items) != len(batch):
            raise RuntimeError(
                f"Prompt batch {batch_index} returned {len(items)} items for {len(batch)} seeds"
            )
        rows.extend(materialize_prompt_rows(items, batch, topic_order))
    write_generated_prompts(rows, Path(args.prompts_csv))
    print(f"Saved {len(rows)} prompts to {args.prompts_csv}")
    return rows


async def evaluate_prompts_async(args: argparse.Namespace) -> dict[str, dict[str, Any]]:
    prompts = read_generated_prompts(Path(args.prompts_csv))
    coordinate_plan = {
        row["id"]: coordinate_context_for_row(
            row["id"],
            coordinate_mode=args.coordinate_mode,
            coordinate_seed=args.coordinate_seed,
            fixed_latitude=args.latitude,
            fixed_longitude=args.longitude,
        )
        for row in prompts
    }
    all_seeds = load_protocol_seeds(Path(args.instructions_csv))
    selected_seeds = select_scenario_seeds(all_seeds, args.seed)
    reference_lookup = build_reference_lookup(selected_seeds)
    existing_results = {} if args.overwrite_results else load_existing_results(Path(args.results_json))
    if args.evaluation_scope == "facilities-only":
        pending_rows = list(prompts)
    else:
        pending_rows = [row for row in prompts if row["id"] not in existing_results]
    if not pending_rows:
        print("All prompts are already evaluated.")
        return existing_results
    print(f"Resuming with {len(existing_results)} existing results; {len(pending_rows)} pending")

    semaphore = asyncio.Semaphore(args.max_concurrency)
    results = dict(existing_results)
    results_lock = asyncio.Lock()
    completed_since_flush = 0

    async def worker(row: dict[str, str]) -> None:
        nonlocal completed_since_flush
        try:
            async with semaphore:
                result = await evaluate_row(
                    row,
                    base_url=args.bystander_base_url,
                    openai_api_key=args.openai_api_key,
                    anthropic_api_key=args.anthropic_api_key,
                    openai_judge_model=args.openai_judge_model,
                    anthropic_judge_model=args.anthropic_judge_model,
                    request_timeout_s=args.request_timeout_s,
                    judge_timeout_s=args.judge_timeout_s,
                    retries=args.retries,
                    reference_lookup=reference_lookup,
                    all_seeds=selected_seeds,
                    coordinate_context=coordinate_plan[row["id"]],
                    evaluation_scope=args.evaluation_scope,
                    existing_result=results.get(row["id"]),
                )
        except Exception as exc:
            print(f"Failed {row['id']}: {exc}")
            result = {
                **row,
                "bystander_ai_response": {
                    "guidance_text": "",
                    "facilities": [],
                    "script_text": "",
                },
                "evaluation": {
                    "gpt_judge": None,
                    "claude_judge": None,
                },
                "error": str(exc),
            }
        async with results_lock:
            results[row["id"]] = result
            completed_since_flush += 1
            if completed_since_flush >= 10:
                save_results(results, Path(args.results_json))
                print(f"Checkpoint saved at {len(results)} evaluated prompts")
                completed_since_flush = 0

    await asyncio.gather(*(worker(row) for row in pending_rows))
    save_results(results, Path(args.results_json))
    print(f"Saved {len(results)} results to {args.results_json}")
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ByStander AI evaluation pipeline")
    parser.add_argument(
        "command",
        choices=["generate-prompts", "evaluate", "full"],
        nargs="?",
        default="full",
    )
    parser.add_argument(
        "--instructions-csv",
        default=str(DEFAULT_INSTRUCTIONS_CSV),
        help="Protocol instruction CSV used for prompt generation and reference lookup.",
    )
    parser.add_argument(
        "--prompts-csv",
        default=str(DEFAULT_PROMPTS_CSV),
        help="Path to generated_prompts.csv",
    )
    parser.add_argument(
        "--results-json",
        default=str(DEFAULT_RESULTS_JSON),
        help="Path to evaluation_results.json",
    )
    parser.add_argument(
        "--bystander-base-url",
        default=DEFAULT_BYSTANDER_BASE_URL,
        help="Base URL for the ByStander backend.",
    )
    parser.add_argument(
        "--openai-generation-model",
        default=OPENAI_GENERATION_MODEL,
        help="OpenAI model used to generate prompts.",
    )
    parser.add_argument(
        "--openai-judge-model",
        default=OPENAI_JUDGE_MODEL,
        help="OpenAI model used as the GPT judge.",
    )
    parser.add_argument(
        "--anthropic-judge-model",
        default=ANTHROPIC_JUDGE_MODEL,
        help="Anthropic model used as the Claude judge.",
    )
    parser.add_argument("--seed", type=int, default=42, help="Deterministic sampling seed.")
    parser.add_argument(
        "--generation-batch-size",
        type=int,
        default=6,
        help="How many scenario seeds to generate per OpenAI call.",
    )
    parser.add_argument(
        "--max-concurrency",
        type=int,
        default=4,
        help="Concurrent scenario evaluations.",
    )
    parser.add_argument(
        "--request-timeout-s",
        type=float,
        default=45.0,
        help="Timeout for ByStander backend calls.",
    )
    parser.add_argument(
        "--judge-timeout-s",
        type=float,
        default=90.0,
        help="Timeout for judge model calls.",
    )
    parser.add_argument(
        "--generation-timeout-s",
        type=float,
        default=90.0,
        help="Timeout for prompt generation calls.",
    )
    parser.add_argument("--retries", type=int, default=3, help="Retry attempts for API failures.")
    parser.add_argument(
        "--latitude",
        type=float,
        default=DEFAULT_LATITUDE,
        help="Latitude supplied to the ByStander backend during evaluation.",
    )
    parser.add_argument(
        "--longitude",
        type=float,
        default=DEFAULT_LONGITUDE,
        help="Longitude supplied to the ByStander backend during evaluation.",
    )
    parser.add_argument(
        "--coordinate-mode",
        choices=["fixed", "random-thailand"],
        default="fixed",
        help="Use a single fixed coordinate for all rows or deterministic random Thailand coordinates per row.",
    )
    parser.add_argument(
        "--coordinate-seed",
        type=int,
        default=42,
        help="Seed used when coordinate-mode is random-thailand.",
    )
    parser.add_argument(
        "--evaluation-scope",
        choices=["full", "facilities-only"],
        default="full",
        help="Judge the full response or only the facilities section.",
    )
    parser.add_argument(
        "--overwrite-results",
        action="store_true",
        help="Ignore existing evaluation_results.json and start fresh.",
    )
    parser.add_argument(
        "--openai-api-key",
        default=os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_KEY") or "",
        help="OpenAI API key. Defaults to OPENAI_API_KEY / OPENAI_KEY.",
    )
    parser.add_argument(
        "--anthropic-api-key",
        default=os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_KEY") or "",
        help="Anthropic API key. Defaults to ANTHROPIC_API_KEY / CLAUDE_KEY.",
    )
    return parser.parse_args()


async def async_main(args: argparse.Namespace) -> None:
    if args.command in {"generate-prompts", "full"}:
        await generate_prompts_async(args)
    if args.command in {"evaluate", "full"}:
        if not args.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required for GPT judging")
        if not args.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY or CLAUDE_KEY is required for Claude judging")
        await evaluate_prompts_async(args)


def main() -> None:
    load_environment()
    args = parse_args()
    asyncio.run(async_main(args))


if __name__ == "__main__":
    main()
