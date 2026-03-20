#!/usr/bin/env python3
import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import anthropic
import requests
from dotenv import load_dotenv

JUDGE_SYSTEM_PROMPT = """
You are a Senior Emergency Physician and Thai Medical Communications Expert.
Your goal is to evaluate the quality of first-aid instructions provided by an AI assistant.
Prioritize medical safety, clarity for a layperson in panic, and Thai linguistic naturalness.
""".strip()

JUDGE_TASK_PROMPT_TEMPLATE = """
Evaluation Rubric (Score 0-2 for each category):

1) Medical Accuracy & Safety:
- 2: Fully aligned with international standards (AHA/Red Cross). No dangerous errors.
- 1: Mostly correct but missing a minor detail.
- 0: Contains a critical fail (dangerous advice or major omission).

2) Actionability & Urgency:
- 2: Clear, imperative verbs. Starts with high-priority actions (e.g., calling 1669).
- 1: Understandable but slightly wordy or passive.
- 0: Vague or confusing; hard to follow during a panic.

3) Thai Linguistic Flow:
- 2: Natural Street Thai with clear terms. Sounds like a helpful human.
- 1: Slightly robotic or translated.
- 0: Unnatural, confusing, or incorrect Thai medical terms.

Task:
Evaluate this pair:
[Input Query]: {input_query}
[Model Response]: {model_response}

Return STRICT JSON only with this schema:
{{
  "medical_safety": 0,
  "actionability": 0,
  "linguistic_flow": 0,
  "total_score": 0,
  "rationale_th": "",
  "formatted_output": "Medical Safety: X/2\\nActionability: X/2\\nLinguistic Flow: X/2\\nTotal Score: Y/6\\nRationale (Thai): ..."
}}

Rules:
- Scores must be integers.
- Each category must be within 0..2.
- total_score must equal medical_safety + actionability + linguistic_flow.
- rationale_th must be Thai.
- formatted_output must follow the exact labels shown above.
""".strip()

# Ordered by capability preference for judging with cost-aware fallbacks.
DEFAULT_CLAUDE_FALLBACK_MODELS = [
    "claude-3-5-sonnet-latest",
    "claude-3-5-haiku-latest",
    "claude-3-5-haiku-20241022",
    "claude-3-haiku-20240307",
]

JUDGE_REPAIR_SYSTEM_PROMPT = (
    "You are a strict JSON formatter. Return valid JSON only with no extra text."
)

PAIRWISE_JUDGE_TASK_PROMPT_TEMPLATE = """
You must compare TWO first-aid responses for the same input and score each one.
Use strict grading. Do not over-reward generic template answers.

Scoring rubric (0-2 each category):
1) medical_safety
2) actionability
3) linguistic_flow

Critical rules:
- A response that is generic and not scenario-specific cannot get full marks.
- If advice misses scenario-specific essential steps, cap medical_safety at 1.
- If instructions are too generic ("ประเมินความปลอดภัย/โทร 1669/รอ") without useful specifics, cap actionability at 1.
- Give 2 only when response is both safe and concretely useful for this exact scenario.
- Prefer the response with better scenario-specific safety detail. Use tie only if quality is genuinely equivalent.

Few-shot calibration examples:
Example 1:
Input: แจ้งเหตุ: ขาท่อนล่างหัก กระดูกแทงออกมา รถล้มขาหัก
Response A: โทร 1669 ห้ามเคลื่อนย้าย รอเจ้าหน้าที่
Response B: โทร 1669, ห้ามดึงกระดูกที่โผล่, ปิดแผลด้วยผ้าสะอาดแบบหลวม, ค้ำตรึงขาไม่ให้ขยับ, เฝ้าระวังช็อก
Expected: B should win. A should not receive full score.

Example 2:
Input: แจ้งเหตุ: อาหารติดคอ พูดไม่ได้ หน้าเขียว
Response A: ทำ Heimlich จนกว่าจะหลุด หากหมดสติเริ่ม CPR
Response B: โทร 1669, เช็คว่าพูด/ไอได้ไหม, ถ้าไอได้ให้ไอต่อ, ถ้าไอไม่ได้ให้ Heimlich 5 ครั้ง, หมดสติเริ่ม CPR
Expected: B should win due to decision points and safer branching.

Now evaluate this case:
[Input Query]: {input_query}
[Response DeepSeek]: {deepseek_response}
[Response Finetuned]: {finetuned_response}

Return STRICT JSON only:
{{
  "deepseek": {{
    "medical_safety": 0,
    "actionability": 0,
    "linguistic_flow": 0,
    "total_score": 0,
    "rationale_th": ""
  }},
  "finetuned": {{
    "medical_safety": 0,
    "actionability": 0,
    "linguistic_flow": 0,
    "total_score": 0,
    "rationale_th": ""
  }},
  "winner": "deepseek",
  "comparative_rationale_th": ""
}}
""".strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare DeepSeek API vs finetuned API using scenarios from bystander_chatml.jsonl, "
            "and score each response with Claude as LLM judge."
        )
    )
    parser.add_argument(
        "--dataset",
        default=os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "finetuning",
            "bystander_chatml.jsonl",
        ),
        help="Path to bystander_chatml.jsonl",
    )
    parser.add_argument(
        "--deepseek-url",
        default="http://127.0.0.1:5001",
        help="Base URL for the un-finetuned DeepSeek API.",
    )
    parser.add_argument(
        "--finetuned-url",
        default="http://127.0.0.1:5002",
        help="Base URL for the finetuned model API.",
    )
    parser.add_argument(
        "--endpoint",
        default="/generate_guidance_sentence_only",
        help="Shared guidance endpoint path on both APIs.",
    )
    parser.add_argument(
        "--judge-model",
        default="claude-3-5-sonnet-latest",
        help="Anthropic Claude model for judging.",
    )
    parser.add_argument(
        "--claude-api-key",
        default=os.getenv("CLAUDE_KEY"),
        help="Anthropic API key. If omitted, CLAUDE_KEY env var is used.",
    )
    parser.add_argument(
        "--max-cases",
        type=int,
        default=None,
        help="Limit number of scenarios from dataset (useful for quick tests).",
    )
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=45.0,
        help="Timeout (seconds) for model API calls.",
    )
    parser.add_argument(
        "--judge-timeout",
        type=float,
        default=90.0,
        help="Timeout (seconds) for Claude judge calls.",
    )
    parser.add_argument(
        "--output-dir",
        default=os.path.join(os.path.dirname(__file__), "outputs"),
        help="Directory where JSON and CSV results will be saved.",
    )
    parser.add_argument(
        "--output-prefix",
        default="deepseek_vs_finetuned",
        help="Prefix for output filenames.",
    )
    return parser.parse_args()


def _strip_code_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def _extract_first_json_object(text: str) -> Optional[Dict[str, Any]]:
    cleaned = _strip_code_fences(text)
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        snippet = cleaned[start : end + 1]
        try:
            parsed = json.loads(snippet)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return None
    return None


def _coerce_score(value: Any, minimum: int, maximum: int, fallback: int = 0) -> int:
    try:
        score = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(maximum, score))


def _build_formatted_output(
    medical_safety: int, actionability: int, linguistic_flow: int, rationale_th: str
) -> str:
    total = medical_safety + actionability + linguistic_flow
    return (
        f"Medical Safety: {medical_safety}/2\n"
        f"Actionability: {actionability}/2\n"
        f"Linguistic Flow: {linguistic_flow}/2\n"
        f"Total Score: {total}/6\n"
        f"Rationale (Thai): {rationale_th}"
    )


def _call_claude_with_fallback(
    client: anthropic.Anthropic,
    candidate_models: List[str],
    system_prompt: str,
    user_prompt: str,
    timeout_s: float,
    max_tokens: int = 800,
    max_retries_per_model: int = 2,
) -> Tuple[str, str, str]:
    last_error = ""
    for model_name in candidate_models:
        for _ in range(max_retries_per_model):
            try:
                response = client.messages.create(
                    model=model_name,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}],
                    temperature=0,
                    max_tokens=max_tokens,
                    timeout=timeout_s,
                )
                text_parts: List[str] = []
                for block in response.content:
                    block_text = getattr(block, "text", None)
                    if isinstance(block_text, str):
                        text_parts.append(block_text)
                return "\n".join(text_parts).strip(), model_name, ""
            except Exception as exc:
                last_error = str(exc)
                continue
    return "", "", last_error or "Unknown Claude judge error"


def _extract_scores_from_text(judge_text: str) -> Optional[Dict[str, Any]]:
    text = _strip_code_fences(judge_text)

    def _first_score(patterns: List[str]) -> Optional[int]:
        for pattern in patterns:
            m = re.search(pattern, text, flags=re.IGNORECASE)
            if m:
                return _coerce_score(m.group(1), 0, 2, fallback=0)
        return None

    medical = _first_score(
        [
            r"medical(?:\s+safety)?\s*[:\-]\s*([0-2])(?:\s*/\s*2)?",
            r"ความปลอดภัย(?:ทางการแพทย์)?\s*[:\-]\s*([0-2])(?:\s*/\s*2)?",
        ]
    )
    action = _first_score(
        [
            r"actionability(?:\s*&\s*urgency)?\s*[:\-]\s*([0-2])(?:\s*/\s*2)?",
            r"ความเร่งด่วน(?:และการปฏิบัติได้จริง)?\s*[:\-]\s*([0-2])(?:\s*/\s*2)?",
        ]
    )
    linguistic = _first_score(
        [
            r"linguistic(?:\s+flow)?\s*[:\-]\s*([0-2])(?:\s*/\s*2)?",
            r"ความลื่นไหล(?:ของภาษาไทย)?\s*[:\-]\s*([0-2])(?:\s*/\s*2)?",
        ]
    )

    if medical is None or action is None or linguistic is None:
        return None

    total_match = re.search(
        r"total\s*score\s*[:\-]\s*([0-6])(?:\s*/\s*6)?", text, flags=re.IGNORECASE
    )
    total = (
        _coerce_score(total_match.group(1), 0, 6, fallback=medical + action + linguistic)
        if total_match
        else medical + action + linguistic
    )
    total = medical + action + linguistic if total != medical + action + linguistic else total

    rationale = ""
    rationale_match = re.search(
        r"rationale\s*\(thai\)\s*[:\-]\s*(.+)", text, flags=re.IGNORECASE | re.DOTALL
    )
    if rationale_match:
        rationale = rationale_match.group(1).strip()
    if not rationale:
        rationale = "สรุปผลจากข้อความประเมินที่ไม่ได้อยู่ในรูป JSON"

    return {
        "medical_safety": medical,
        "actionability": action,
        "linguistic_flow": linguistic,
        "total_score": total,
        "rationale_th": rationale,
    }


def _heuristic_judge_fallback(model_response: str) -> Dict[str, Any]:
    text = model_response.strip()

    medical = 1
    actionability = 1
    linguistic = 1

    if "1669" in text:
        actionability = 2
    if re.search(r"(^|\s)1[.)]", text) and re.search(r"(^|\s)2[.)]", text):
        actionability = max(actionability, 2)
    if any(k in text for k in ["CPR", "ปั๊มหัวใจ", "ไม่หายใจ", "หมดสติ", "ห้าม"]):
        medical = min(2, medical + 1)
    if len(text) < 40:
        actionability = max(0, actionability - 1)

    thai_chars = len(re.findall(r"[\u0E00-\u0E7F]", text))
    text_len = max(len(text), 1)
    thai_ratio = thai_chars / text_len
    if thai_ratio > 0.35:
        linguistic = 2
    if thai_chars == 0:
        linguistic = 0

    return {
        "medical_safety": medical,
        "actionability": actionability,
        "linguistic_flow": linguistic,
        "total_score": medical + actionability + linguistic,
        "rationale_th": "ใช้การประเมินสำรองอัตโนมัติ เนื่องจากผล judge ไม่อยู่ในรูป JSON ที่แปลงได้",
    }


def _normalize_judge_result(parsed: Dict[str, Any]) -> Dict[str, Any]:
    medical_safety = _coerce_score(parsed.get("medical_safety"), 0, 2, fallback=0)
    actionability = _coerce_score(parsed.get("actionability"), 0, 2, fallback=0)
    linguistic_flow = _coerce_score(parsed.get("linguistic_flow"), 0, 2, fallback=0)
    total_score = _coerce_score(
        parsed.get("total_score"),
        0,
        6,
        fallback=medical_safety + actionability + linguistic_flow,
    )
    expected_total = medical_safety + actionability + linguistic_flow
    if total_score != expected_total:
        total_score = expected_total

    rationale_th = str(parsed.get("rationale_th", "")).strip()
    if not rationale_th:
        rationale_th = "ไม่มีเหตุผลประกอบจากผู้ประเมิน"

    formatted_output = str(parsed.get("formatted_output", "")).strip()
    if not formatted_output:
        formatted_output = _build_formatted_output(
            medical_safety, actionability, linguistic_flow, rationale_th
        )

    return {
        "medical_safety": medical_safety,
        "actionability": actionability,
        "linguistic_flow": linguistic_flow,
        "total_score": total_score,
        "rationale_th": rationale_th,
        "formatted_output": formatted_output,
    }


def _specificity_score(input_query: str, response_text: str) -> int:
    if not input_query.strip() or not response_text.strip():
        return 0

    query = input_query
    if "แจ้งเหตุ:" in query:
        query = query.split("แจ้งเหตุ:", 1)[1]
    if "หรือมีอาการ" in query:
        query = query.split("หรือมีอาการ", 1)[0]

    terms = [t.strip() for t in re.split(r"[,/]", query) if t.strip()]
    score = 0
    lower_resp = response_text.lower()
    for term in terms[:6]:
        if len(term) < 2:
            continue
        if term.lower() in lower_resp:
            score += 1
    return score


def _winner_from_scores_and_specificity(
    deepseek_judge: Dict[str, Any],
    finetuned_judge: Dict[str, Any],
    deepseek_response: str,
    finetuned_response: str,
    input_query: str,
) -> str:
    ds_total = deepseek_judge.get("total_score", 0)
    ft_total = finetuned_judge.get("total_score", 0)
    if ds_total > ft_total:
        return "deepseek"
    if ft_total > ds_total:
        return "finetuned"

    ds_tuple = (
        deepseek_judge.get("medical_safety", 0),
        deepseek_judge.get("actionability", 0),
        deepseek_judge.get("linguistic_flow", 0),
    )
    ft_tuple = (
        finetuned_judge.get("medical_safety", 0),
        finetuned_judge.get("actionability", 0),
        finetuned_judge.get("linguistic_flow", 0),
    )
    if ds_tuple > ft_tuple:
        return "deepseek"
    if ft_tuple > ds_tuple:
        return "finetuned"

    ds_spec = _specificity_score(input_query, deepseek_response)
    ft_spec = _specificity_score(input_query, finetuned_response)
    if ds_spec > ft_spec:
        return "deepseek"
    if ft_spec > ds_spec:
        return "finetuned"
    return "tie"


def load_scenarios(dataset_path: str, max_cases: Optional[int] = None) -> List[Dict[str, Any]]:
    scenarios: List[Dict[str, Any]] = []
    with open(dataset_path, "r", encoding="utf-8") as f:
        for line_no, raw_line in enumerate(f, start=1):
            line = raw_line.strip()
            if not line:
                continue

            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                print(f"[WARN] Skip line {line_no}: invalid JSON ({exc})")
                continue

            messages = item.get("messages", [])
            if not isinstance(messages, list):
                continue

            user_query = ""
            reference_guidance = ""
            reference_facility_type = ""
            reference_severity = ""

            for msg in messages:
                if not isinstance(msg, dict):
                    continue
                role = msg.get("role")
                content = msg.get("content")
                if not isinstance(content, str):
                    continue

                normalized = content.strip()
                if role == "user" and not user_query:
                    user_query = normalized
                elif role == "assistant":
                    lower = normalized.lower()
                    if lower.startswith("facility type:"):
                        reference_facility_type = normalized.split(":", 1)[-1].strip()
                    elif lower.startswith("severity:"):
                        reference_severity = normalized.split(":", 1)[-1].strip()
                    elif not reference_guidance:
                        reference_guidance = normalized

            if not user_query:
                continue

            scenario_name = extract_scenario_name(user_query)
            scenarios.append(
                {
                    "scenario_id": f"scenario_{len(scenarios) + 1:03d}",
                    "line_no": line_no,
                    "scenario_name": scenario_name,
                    "input_query": user_query,
                    "reference_guidance": reference_guidance,
                    "reference_facility_type": reference_facility_type,
                    "reference_severity": reference_severity,
                }
            )

            if max_cases is not None and len(scenarios) >= max_cases:
                break

    return scenarios


def extract_scenario_name(input_query: str) -> str:
    text = input_query.strip()
    if "แจ้งเหตุ:" in text:
        text = text.split("แจ้งเหตุ:", 1)[1].strip()
    if "หรือมีอาการ" in text:
        text = text.split("หรือมีอาการ", 1)[0].strip()
    if "," in text and len(text) > 60:
        text = text.split(",", 1)[0].strip()
    return text[:120]


def call_guidance_api(
    base_url: str, endpoint: str, sentence: str, timeout_s: float
) -> Dict[str, Any]:
    url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"
    payload = {"sentence": sentence}
    result: Dict[str, Any] = {
        "url": url,
        "status_code": None,
        "raw_text": "",
        "raw_json": None,
        "guidance": "",
        "severity": "",
        "facility_type": "",
        "error": "",
    }

    try:
        response = requests.post(url, json=payload, timeout=timeout_s)
        result["status_code"] = response.status_code
        result["raw_text"] = response.text

        try:
            parsed = response.json()
            result["raw_json"] = parsed
        except ValueError:
            parsed = None

        if response.status_code >= 400:
            if isinstance(parsed, dict):
                err_msg = parsed.get("error") or parsed.get("message") or response.text
            else:
                err_msg = response.text
            result["error"] = f"HTTP {response.status_code}: {err_msg}"
            return result

        if isinstance(parsed, dict):
            result["guidance"] = str(parsed.get("guidance", "")).strip()
            result["severity"] = str(parsed.get("severity", "")).strip()
            result["facility_type"] = str(parsed.get("facility_type", "")).strip()
            if parsed.get("error"):
                result["error"] = str(parsed["error"])
        else:
            result["error"] = "Response is not JSON"
    except requests.RequestException as exc:
        result["error"] = f"Request error: {exc}"

    if not result["error"] and not result["guidance"]:
        result["error"] = "Empty guidance response"
    return result


def judge_with_claude(
    client: anthropic.Anthropic,
    judge_model: str,
    input_query: str,
    model_response: str,
    timeout_s: float,
) -> Dict[str, Any]:
    if not model_response.strip():
        empty = _normalize_judge_result(
            {
                "medical_safety": 0,
                "actionability": 0,
                "linguistic_flow": 0,
                "total_score": 0,
                "rationale_th": "ไม่มีข้อความคำแนะนำให้ประเมิน",
            }
        )
        empty["judge_raw"] = ""
        empty["judge_error"] = "Empty model response"
        empty["judge_model_used"] = ""
        empty["judge_parse_mode"] = "empty_response"
        return empty

    user_prompt = JUDGE_TASK_PROMPT_TEMPLATE.format(
        input_query=input_query.strip(),
        model_response=model_response.strip(),
    )

    candidate_models: List[str] = []
    seen: set = set()
    for model_name in [judge_model, *DEFAULT_CLAUDE_FALLBACK_MODELS]:
        if model_name and model_name not in seen:
            candidate_models.append(model_name)
            seen.add(model_name)

    content, used_model, call_error = _call_claude_with_fallback(
        client=client,
        candidate_models=candidate_models,
        system_prompt=JUDGE_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        timeout_s=timeout_s,
        max_tokens=800,
        max_retries_per_model=2,
    )
    if call_error:
        failed = _normalize_judge_result(
            {
                "medical_safety": 0,
                "actionability": 0,
                "linguistic_flow": 0,
                "total_score": 0,
                "rationale_th": "การประเมินล้มเหลวจากข้อผิดพลาดระบบ",
            }
        )
        failed["judge_raw"] = ""
        failed["judge_error"] = call_error
        failed["judge_model_used"] = ""
        failed["judge_parse_mode"] = "judge_call_error"
        return failed

    parsed = _extract_first_json_object(content)
    parse_mode = "json"

    if not parsed:
        repair_prompt = (
            "Convert the following evaluation text into strict JSON using this schema exactly:\n"
            '{"medical_safety":0,"actionability":0,"linguistic_flow":0,"total_score":0,"rationale_th":"","formatted_output":"Medical Safety: X/2\\nActionability: X/2\\nLinguistic Flow: X/2\\nTotal Score: Y/6\\nRationale (Thai): ..."}\n'
            "Return JSON only, no markdown.\n\n"
            f"Evaluation text:\n{content}"
        )
        repair_models = [used_model] + [m for m in candidate_models if m != used_model]
        repaired_content, repaired_model, _ = _call_claude_with_fallback(
            client=client,
            candidate_models=repair_models,
            system_prompt=JUDGE_REPAIR_SYSTEM_PROMPT,
            user_prompt=repair_prompt,
            timeout_s=timeout_s,
            max_tokens=500,
            max_retries_per_model=1,
        )
        repaired_parsed = _extract_first_json_object(repaired_content) if repaired_content else None
        if repaired_parsed:
            parsed = repaired_parsed
            content = repaired_content
            used_model = repaired_model or used_model
            parse_mode = "json_repaired"

    if not parsed:
        extracted = _extract_scores_from_text(content)
        if extracted:
            parsed = extracted
            parse_mode = "score_extracted"

    if not parsed:
        parsed = _heuristic_judge_fallback(model_response)
        parse_mode = "heuristic_fallback"

    normalized = _normalize_judge_result(parsed)
    normalized["judge_raw"] = content
    normalized["judge_error"] = ""
    normalized["judge_model_used"] = used_model
    normalized["judge_parse_mode"] = parse_mode
    return normalized


def judge_pair_with_claude(
    client: anthropic.Anthropic,
    judge_model: str,
    input_query: str,
    deepseek_response: str,
    finetuned_response: str,
    timeout_s: float,
) -> Dict[str, Any]:
    if not deepseek_response.strip() and not finetuned_response.strip():
        return {
            "deepseek": _normalize_judge_result(
                {
                    "medical_safety": 0,
                    "actionability": 0,
                    "linguistic_flow": 0,
                    "total_score": 0,
                    "rationale_th": "ไม่มีข้อความคำแนะนำให้ประเมิน",
                }
            ),
            "finetuned": _normalize_judge_result(
                {
                    "medical_safety": 0,
                    "actionability": 0,
                    "linguistic_flow": 0,
                    "total_score": 0,
                    "rationale_th": "ไม่มีข้อความคำแนะนำให้ประเมิน",
                }
            ),
            "winner": "tie_both_failed",
            "comparative_rationale_th": "ไม่มีผลลัพธ์จากทั้งสองโมเดล",
            "judge_model_used": "",
            "judge_parse_mode": "pair_empty",
            "judge_error": "Empty responses from both models",
            "judge_raw": "",
        }

    candidate_models: List[str] = []
    seen: set = set()
    for model_name in [judge_model, *DEFAULT_CLAUDE_FALLBACK_MODELS]:
        if model_name and model_name not in seen:
            candidate_models.append(model_name)
            seen.add(model_name)

    pair_prompt = PAIRWISE_JUDGE_TASK_PROMPT_TEMPLATE.format(
        input_query=input_query.strip(),
        deepseek_response=deepseek_response.strip(),
        finetuned_response=finetuned_response.strip(),
    )

    content, used_model, call_error = _call_claude_with_fallback(
        client=client,
        candidate_models=candidate_models,
        system_prompt=JUDGE_SYSTEM_PROMPT,
        user_prompt=pair_prompt,
        timeout_s=timeout_s,
        max_tokens=1200,
        max_retries_per_model=2,
    )

    parse_mode = "pair_json"
    parsed = _extract_first_json_object(content) if not call_error else None
    if not parsed and not call_error:
        repair_prompt = (
            "Convert the following pairwise evaluation into strict JSON only.\n"
            "Required schema:\n"
            '{"deepseek":{"medical_safety":0,"actionability":0,"linguistic_flow":0,"total_score":0,"rationale_th":""},'
            '"finetuned":{"medical_safety":0,"actionability":0,"linguistic_flow":0,"total_score":0,"rationale_th":""},'
            '"winner":"deepseek","comparative_rationale_th":""}\n\n'
            f"Evaluation text:\n{content}"
        )
        repair_models = [used_model] + [m for m in candidate_models if m != used_model]
        repaired_content, repaired_model, _ = _call_claude_with_fallback(
            client=client,
            candidate_models=repair_models,
            system_prompt=JUDGE_REPAIR_SYSTEM_PROMPT,
            user_prompt=repair_prompt,
            timeout_s=timeout_s,
            max_tokens=700,
            max_retries_per_model=1,
        )
        repaired_parsed = _extract_first_json_object(repaired_content) if repaired_content else None
        if repaired_parsed:
            parsed = repaired_parsed
            content = repaired_content
            used_model = repaired_model or used_model
            parse_mode = "pair_json_repaired"

    if call_error or not parsed:
        deepseek_ind = judge_with_claude(
            client=client,
            judge_model=judge_model,
            input_query=input_query,
            model_response=deepseek_response,
            timeout_s=timeout_s,
        )
        finetuned_ind = judge_with_claude(
            client=client,
            judge_model=judge_model,
            input_query=input_query,
            model_response=finetuned_response,
            timeout_s=timeout_s,
        )
        winner = _winner_from_scores_and_specificity(
            deepseek_ind, finetuned_ind, deepseek_response, finetuned_response, input_query
        )
        return {
            "deepseek": deepseek_ind,
            "finetuned": finetuned_ind,
            "winner": winner,
            "comparative_rationale_th": (
                "ใช้การตัดสินสำรองจากการให้คะแนนรายโมเดล เนื่องจาก pairwise judge parse ไม่สำเร็จ"
            ),
            "judge_model_used": used_model,
            "judge_parse_mode": "pair_fallback_individual",
            "judge_error": call_error or "",
            "judge_raw": content,
        }

    deepseek_judge = _normalize_judge_result(parsed.get("deepseek", {}))
    finetuned_judge = _normalize_judge_result(parsed.get("finetuned", {}))

    winner = str(parsed.get("winner", "")).strip().lower()
    if winner not in {"deepseek", "finetuned", "tie"}:
        winner = _winner_from_scores_and_specificity(
            deepseek_judge, finetuned_judge, deepseek_response, finetuned_response, input_query
        )
    elif winner == "tie":
        winner = _winner_from_scores_and_specificity(
            deepseek_judge, finetuned_judge, deepseek_response, finetuned_response, input_query
        )

    comparative_rationale = str(parsed.get("comparative_rationale_th", "")).strip()
    if not comparative_rationale:
        comparative_rationale = "เปรียบเทียบจากความครบถ้วน ความเฉพาะเจาะจง และความปลอดภัยของคำแนะนำ"

    deepseek_judge["judge_raw"] = content
    deepseek_judge["judge_error"] = ""
    deepseek_judge["judge_model_used"] = used_model
    deepseek_judge["judge_parse_mode"] = parse_mode

    finetuned_judge["judge_raw"] = content
    finetuned_judge["judge_error"] = ""
    finetuned_judge["judge_model_used"] = used_model
    finetuned_judge["judge_parse_mode"] = parse_mode

    return {
        "deepseek": deepseek_judge,
        "finetuned": finetuned_judge,
        "winner": winner,
        "comparative_rationale_th": comparative_rationale,
        "judge_model_used": used_model,
        "judge_parse_mode": parse_mode,
        "judge_error": "",
        "judge_raw": content,
    }


def choose_winner(
    deepseek_result: Dict[str, Any], finetuned_result: Dict[str, Any], input_query: str = ""
) -> str:
    ds_error = bool(deepseek_result.get("api_error"))
    ft_error = bool(finetuned_result.get("api_error"))
    if ds_error and ft_error:
        return "tie_both_failed"
    if ds_error and not ft_error:
        return "finetuned"
    if ft_error and not ds_error:
        return "deepseek"

    return _winner_from_scores_and_specificity(
        deepseek_result.get("judge", {}),
        finetuned_result.get("judge", {}),
        deepseek_result.get("guidance", ""),
        finetuned_result.get("guidance", ""),
        input_query,
    )


def print_scenario_result(result: Dict[str, Any]) -> None:
    print("=" * 100)
    print(f"{result['scenario_id']} | {result['scenario_name']}")
    print(f"Input Query: {result['input_query']}")
    if result.get("reference_guidance"):
        print(f"Reference Guidance (dataset): {result['reference_guidance'][:220]}")
    print("-" * 100)

    for model_key, label in [("deepseek", "DeepSeek (un-finetuned)"), ("finetuned", "Finetuned model")]:
        model_block = result[model_key]
        print(f"[{label}]")
        print(f"API URL: {model_block.get('url')}")
        print(f"Predicted severity/facility: {model_block.get('severity', '')} / {model_block.get('facility_type', '')}")
        if model_block.get("api_error"):
            print(f"API Error: {model_block['api_error']}")
        else:
            print(f"Model Guidance: {model_block.get('guidance', '')}")
        print()
        print(model_block.get("judge", {}).get("formatted_output", "No judge output"))
        model_used = model_block.get("judge", {}).get("judge_model_used", "")
        if model_used:
            print(f"Judge Model Used: {model_used}")
        parse_mode = model_block.get("judge", {}).get("judge_parse_mode", "")
        if parse_mode:
            print(f"Judge Parse Mode: {parse_mode}")
        if model_block.get("judge", {}).get("judge_error"):
            print(f"Judge Error: {model_block['judge']['judge_error']}")
        print("-" * 100)

    print(f"Winner: {result['winner']}")
    comparative_rationale = result.get("comparative_rationale_th", "")
    if comparative_rationale:
        print(f"Comparative Rationale (Thai): {comparative_rationale}")


def _mean(values: List[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def build_summary(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    deepseek_scores: List[float] = []
    finetuned_scores: List[float] = []
    deepseek_errors = 0
    finetuned_errors = 0
    winner_counts = {
        "deepseek": 0,
        "finetuned": 0,
        "tie": 0,
        "tie_both_failed": 0,
    }

    for row in results:
        ds = row["deepseek"]
        ft = row["finetuned"]
        if ds.get("api_error"):
            deepseek_errors += 1
        else:
            deepseek_scores.append(float(ds["judge"]["total_score"]))
        if ft.get("api_error"):
            finetuned_errors += 1
        else:
            finetuned_scores.append(float(ft["judge"]["total_score"]))

        winner = row.get("winner", "tie")
        if winner in winner_counts:
            winner_counts[winner] += 1
        else:
            winner_counts["tie"] += 1

    return {
        "total_scenarios": len(results),
        "deepseek": {
            "successful_calls": len(results) - deepseek_errors,
            "failed_calls": deepseek_errors,
            "average_total_score": round(_mean(deepseek_scores), 4),
        },
        "finetuned": {
            "successful_calls": len(results) - finetuned_errors,
            "failed_calls": finetuned_errors,
            "average_total_score": round(_mean(finetuned_scores), 4),
        },
        "winner_counts": winner_counts,
    }


def save_outputs(
    output_dir: str,
    output_prefix: str,
    run_payload: Dict[str, Any],
    per_model_rows: List[Dict[str, Any]],
) -> Tuple[str, str]:
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = os.path.join(output_dir, f"{output_prefix}_{timestamp}.json")
    csv_path = os.path.join(output_dir, f"{output_prefix}_{timestamp}.csv")

    with open(json_path, "w", encoding="utf-8") as jf:
        json.dump(run_payload, jf, ensure_ascii=False, indent=2)

    csv_columns = [
        "scenario_id",
        "scenario_name",
        "input_query",
        "reference_severity",
        "reference_facility_type",
        "model_name",
        "winner",
        "comparative_rationale_th",
        "api_url",
        "api_status_code",
        "api_error",
        "predicted_severity",
        "predicted_facility_type",
        "model_guidance",
        "medical_safety",
        "actionability",
        "linguistic_flow",
        "total_score",
        "rationale_th",
        "formatted_output",
        "judge_model_used",
        "judge_parse_mode",
        "judge_error",
    ]

    with open(csv_path, "w", encoding="utf-8", newline="") as cf:
        writer = csv.DictWriter(cf, fieldnames=csv_columns)
        writer.writeheader()
        for row in per_model_rows:
            writer.writerow(row)

    return json_path, csv_path


def main() -> int:
    args = parse_args()

    backend_root = os.path.dirname(os.path.dirname(__file__))
    load_dotenv(os.path.join(backend_root, ".env"), override=False)
    load_dotenv(override=False)

    api_key = args.claude_api_key or os.getenv("CLAUDE_KEY")
    if not api_key:
        print("ERROR: CLAUDE_KEY is required for Claude judging.")
        return 1

    if not os.path.exists(args.dataset):
        print(f"ERROR: Dataset not found: {args.dataset}")
        return 1

    scenarios = load_scenarios(args.dataset, args.max_cases)
    if not scenarios:
        print("ERROR: No valid scenarios found in dataset.")
        return 1

    print(f"Loaded {len(scenarios)} scenario(s) from {args.dataset}")
    print(
        f"Comparing APIs: deepseek={args.deepseek_url} vs finetuned={args.finetuned_url}, endpoint={args.endpoint}"
    )
    print(f"Judge model: {args.judge_model}")

    client = anthropic.Anthropic(api_key=api_key)

    all_results: List[Dict[str, Any]] = []
    per_model_rows: List[Dict[str, Any]] = []

    for scenario in scenarios:
        input_query = scenario["input_query"]

        deepseek_api = call_guidance_api(
            base_url=args.deepseek_url,
            endpoint=args.endpoint,
            sentence=input_query,
            timeout_s=args.request_timeout,
        )
        finetuned_api = call_guidance_api(
            base_url=args.finetuned_url,
            endpoint=args.endpoint,
            sentence=input_query,
            timeout_s=args.request_timeout,
        )

        pair_judge = judge_pair_with_claude(
            client=client,
            judge_model=args.judge_model,
            input_query=input_query,
            deepseek_response=deepseek_api.get("guidance", ""),
            finetuned_response=finetuned_api.get("guidance", ""),
            timeout_s=args.judge_timeout,
        )
        deepseek_judge = pair_judge["deepseek"]
        finetuned_judge = pair_judge["finetuned"]

        deepseek_block = {
            "url": deepseek_api["url"],
            "status_code": deepseek_api["status_code"],
            "api_error": deepseek_api["error"],
            "guidance": deepseek_api["guidance"],
            "severity": deepseek_api["severity"],
            "facility_type": deepseek_api["facility_type"],
            "raw_json": deepseek_api["raw_json"],
            "raw_text": deepseek_api["raw_text"],
            "judge": deepseek_judge,
        }
        finetuned_block = {
            "url": finetuned_api["url"],
            "status_code": finetuned_api["status_code"],
            "api_error": finetuned_api["error"],
            "guidance": finetuned_api["guidance"],
            "severity": finetuned_api["severity"],
            "facility_type": finetuned_api["facility_type"],
            "raw_json": finetuned_api["raw_json"],
            "raw_text": finetuned_api["raw_text"],
            "judge": finetuned_judge,
        }

        winner = pair_judge.get("winner") or choose_winner(
            deepseek_block, finetuned_block, input_query=input_query
        )

        scenario_result = {
            **scenario,
            "deepseek": deepseek_block,
            "finetuned": finetuned_block,
            "winner": winner,
            "comparative_rationale_th": pair_judge.get("comparative_rationale_th", ""),
            "pair_judge_meta": {
                "judge_model_used": pair_judge.get("judge_model_used", ""),
                "judge_parse_mode": pair_judge.get("judge_parse_mode", ""),
                "judge_error": pair_judge.get("judge_error", ""),
            },
        }
        all_results.append(scenario_result)
        print_scenario_result(scenario_result)

        for model_name, model_data in [("deepseek", deepseek_block), ("finetuned", finetuned_block)]:
            per_model_rows.append(
                {
                    "scenario_id": scenario["scenario_id"],
                    "scenario_name": scenario["scenario_name"],
                    "input_query": scenario["input_query"],
                    "reference_severity": scenario.get("reference_severity", ""),
                    "reference_facility_type": scenario.get("reference_facility_type", ""),
                    "model_name": model_name,
                    "winner": winner,
                    "comparative_rationale_th": scenario_result.get("comparative_rationale_th", ""),
                    "api_url": model_data.get("url", ""),
                    "api_status_code": model_data.get("status_code", ""),
                    "api_error": model_data.get("api_error", ""),
                    "predicted_severity": model_data.get("severity", ""),
                    "predicted_facility_type": model_data.get("facility_type", ""),
                    "model_guidance": model_data.get("guidance", ""),
                    "medical_safety": model_data["judge"].get("medical_safety", ""),
                    "actionability": model_data["judge"].get("actionability", ""),
                    "linguistic_flow": model_data["judge"].get("linguistic_flow", ""),
                    "total_score": model_data["judge"].get("total_score", ""),
                    "rationale_th": model_data["judge"].get("rationale_th", ""),
                    "formatted_output": model_data["judge"].get("formatted_output", ""),
                    "judge_model_used": model_data["judge"].get("judge_model_used", ""),
                    "judge_parse_mode": model_data["judge"].get("judge_parse_mode", ""),
                    "judge_error": model_data["judge"].get("judge_error", ""),
                }
            )

    summary = build_summary(all_results)
    print("=" * 100)
    print("SUMMARY")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    run_payload = {
        "run_at": datetime.now().isoformat(),
        "config": {
            "dataset": args.dataset,
            "deepseek_url": args.deepseek_url,
            "finetuned_url": args.finetuned_url,
            "endpoint": args.endpoint,
            "judge_model": args.judge_model,
            "max_cases": args.max_cases,
            "request_timeout": args.request_timeout,
            "judge_timeout": args.judge_timeout,
        },
        "summary": summary,
        "results": all_results,
    }

    json_path, csv_path = save_outputs(
        output_dir=args.output_dir,
        output_prefix=args.output_prefix,
        run_payload=run_payload,
        per_model_rows=per_model_rows,
    )
    print(f"Saved JSON: {json_path}")
    print(f"Saved CSV : {csv_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
