import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

# Use paths relative to this script so it works from repo root or this folder.
BASE_DIR = os.path.dirname(__file__)
INPUT_FILE = os.path.join(BASE_DIR, "bystander_chatml.jsonl")
OUTPUT_FILE = os.path.join(BASE_DIR, "bystander_chatml_ready.jsonl")

# Keep prompts aligned with bystander_backend/guidance_generation/main.py
SYSTEM_PROMPT = (
    "You are the ByStander Emergency Intelligence Engine, a professional medical dispatcher "
    "specializing in Thai emergency protocols. Your goal is to provide immediate, "
    "stress-resistant, and factually perfect first-aid guidance.\n"
    "OPERATIONAL RULES:\n"
    "1. LANGUAGE: Use professional yet easy-to-understand Thai (Central dialect).\n"
    "2. TONE: Calm, authoritative, and instructional to minimize user panic.\n"
    "3. LOGIC:\n"
    "   - If the input is a medical/accidental emergency, categorize it as critical or mild.\n"
    "   - If the input is not an emergency, categorize it as none and provide brief advisory guidance.\n"
    "4. SAFETY: Never provide instructions requiring professional equipment unless explicitly available.\n"
    "5. FORMAT: Output strictly valid JSON. No markdown, no asterisks, no extra commentary."
)

USER_PROMPT_TEMPLATE = (
    'สถานการณ์: "{prompt_text}"\n'
    "ตอบเป็น JSON ที่มีฟิลด์: guidance, severity, facility_type.\n"
    "guidance:\n"
    "- หากเป็นเหตุฉุกเฉิน: เริ่มต้นด้วย 'สถานการณ์นี้เป็นเหตุฉุกเฉิน' และให้คำแนะนำปฐมพยาบาลแบบลำดับขั้นตอนที่ชัดเจน\n"
    "- หากไม่ใช่เหตุฉุกเฉิน: เริ่มต้นด้วย 'สถานการณ์นี้ไม่ใช่เหตุฉุกเฉิน' และให้คำแนะนำเบื้องต้นที่เหมาะสม\n"
    "- ห้ามใช้เครื่องหมายดอกจัน (*) และห้ามใช้ markdown\n"
    "severity: เลือกเพียงหนึ่งค่าใน [\"critical\", \"mild\", \"none\"]\n"
    "facility_type: เลือกเพียงหนึ่งค่าใน [\"hospital\", \"clinic\", \"none\"]\n"
    "ห้ามใส่คำอธิบายอื่นนอกเหนือจาก JSON."
)


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = value if isinstance(value, str) else str(value)
    return text.strip()


def _normalize_severity(raw: str) -> str:
    value = _normalize_text(raw).lower()
    if value in {"critical", "mild", "none"}:
        return value
    if value in {"no need", "no_need", "normal", "nan", "na", "n/a"}:
        return "none"
    return "none"


def _normalize_facility_type(raw: str) -> str:
    value = _normalize_text(raw).lower()
    if value in {"hospital", "clinic", "none"}:
        return value
    if value in {"nan", "na", "n/a", "no need", "no_need"}:
        return "none"
    return "none"


def _extract_from_system(system_content: str) -> Tuple[str, str]:
    """
    Extract fallback facility/severity from source system text, e.g.:
    "You are an emergency assistant. Category: Hospital, Severity: critical."
    """
    text = _normalize_text(system_content)
    if not text:
        return "none", "none"

    category_match = re.search(r"category\s*:\s*([a-zA-Z ]+)", text, flags=re.IGNORECASE)
    severity_match = re.search(r"severity\s*:\s*([a-zA-Z ]+)", text, flags=re.IGNORECASE)

    category_raw = category_match.group(1).strip() if category_match else "none"
    severity_raw = severity_match.group(1).strip() if severity_match else "none"

    return _normalize_facility_type(category_raw), _normalize_severity(severity_raw)


def _extract_record_fields(messages: List[Dict[str, Any]]) -> Optional[Dict[str, str]]:
    user_content = ""
    guidance_candidates: List[str] = []
    facility_type = ""
    severity = ""
    system_content = ""

    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        content = _normalize_text(msg.get("content"))
        if not content:
            continue

        if role == "system" and not system_content:
            system_content = content
        elif role == "user" and not user_content:
            user_content = content
        elif role == "assistant":
            lower = content.lower()
            if lower.startswith("facility type:"):
                facility_type = _normalize_text(content.split(":", 1)[-1])
            elif lower.startswith("severity:"):
                severity = _normalize_text(content.split(":", 1)[-1])
            else:
                guidance_candidates.append(content)

    if not user_content:
        return None

    # Keep the richest guidance text instead of accidentally keeping label lines.
    guidance = max(guidance_candidates, key=len).strip() if guidance_candidates else ""
    if not guidance:
        return None

    sys_facility, sys_severity = _extract_from_system(system_content)
    facility_type = _normalize_facility_type(facility_type or sys_facility)
    severity = _normalize_severity(severity or sys_severity)

    return {
        "user_content": user_content,
        "guidance": guidance,
        "facility_type": facility_type,
        "severity": severity,
    }


def convert_to_chatml(input_path: str, output_path: str) -> None:
    total = 0
    written = 0
    skipped = 0

    with open(input_path, "r", encoding="utf-8") as f_in, open(
        output_path, "w", encoding="utf-8"
    ) as f_out:
        for line_no, line in enumerate(f_in, start=1):
            total += 1
            raw = line.strip()
            if not raw:
                skipped += 1
                continue

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                skipped += 1
                continue

            messages = data.get("messages", [])
            if not isinstance(messages, list):
                skipped += 1
                continue

            fields = _extract_record_fields(messages)
            if not fields:
                skipped += 1
                continue

            user_prompt = USER_PROMPT_TEMPLATE.format(prompt_text=fields["user_content"])
            assistant_payload = {
                "guidance": fields["guidance"],
                "severity": fields["severity"],
                "facility_type": fields["facility_type"],
            }
            assistant_json = json.dumps(assistant_payload, ensure_ascii=False)

            chatml_text = (
                f"<|im_start|>system\n{SYSTEM_PROMPT}<|im_end|>\n"
                f"<|im_start|>user\n{user_prompt}<|im_end|>\n"
                f"<|im_start|>assistant\n{assistant_json}<|im_end|>"
            )

            json.dump({"text": chatml_text}, f_out, ensure_ascii=False)
            f_out.write("\n")
            written += 1

    print(f"Processed: {total} lines")
    print(f"Written  : {written} examples")
    print(f"Skipped  : {skipped} lines")
    print(f"File saved to {output_path}")


if __name__ == "__main__":
    convert_to_chatml(INPUT_FILE, OUTPUT_FILE)
