#!/usr/bin/env python3
import argparse
import concurrent.futures
import csv
import json
import os
import re
import time
from typing import Any, Dict, List, Optional

from tqdm import tqdm

try:
    from google import genai
    from google.genai import types
except ImportError as exc:
    raise ImportError(
        "Missing dependency: google-genai. "
        "Install with: pip install -U google-genai tqdm"
    ) from exc


BASE_DIR = os.path.dirname(__file__)
DEFAULT_INPUT_CSV = os.path.join(BASE_DIR, "instructions_raw_final.csv")
DEFAULT_OUTPUT_JSONL = os.path.join(BASE_DIR, "bystander_augmented_gemini.jsonl")
DEFAULT_MODEL = "gemini-3-flash-preview"
DEFAULT_INSTRUCTION = "วิเคราะห์สถานการณ์ฉุกเฉินและให้คำแนะนำการปฐมพยาบาลเบื้องต้น"


SYSTEM_PROMPT = """
คุณคือผู้เชี่ยวชาญด้านการสร้างข้อมูลสังเคราะห์สำหรับเหตุฉุกเฉินของไทย (ByStander).
หน้าที่ของคุณคือสร้าง "ประโยคผู้ใช้" ที่สมจริงมากสำหรับสถานการณ์ฉุกเฉิน โดยยึดตามเคสทางการแพทย์ที่กำหนดเท่านั้น
ห้ามสร้างประโยคที่เปลี่ยนประเภทเหตุหรือทำให้ severity/facility ผิดจากเคส

ข้อกำหนดด้านความสอดคล้องของคำแนะนำ (Guidance Fidelity) ที่ต้องเข้มงวด:
- guidance ที่สร้างในแต่ละรายการต้อง "ใกล้เคียง" กับ Detailed Guidance ที่ได้รับ
- ต้องคงสาระสำคัญและลำดับการช่วยเหลือหลัก เช่น การประเมินความปลอดภัย, โทรฉุกเฉิน, ขั้นตอนปฐมพยาบาลที่สำคัญ, ข้อห้าม
- ห้ามเพิ่มขั้นตอนที่ขัดแย้งกับ guidance ต้นฉบับ หรือทำให้เกิดความเสี่ยงทางการแพทย์
- สามารถเรียบเรียงถ้อยคำใหม่ได้ แต่ความหมายทางการแพทย์ต้องตรงเดิม
- severity และ facility_type ของทุกตัวอย่างต้องตรงกับเคสเสมอ

แนวทางภาษา:
- เป็นภาษาไทยธรรมชาติแบบคนทั่วไปพูดจริงในเหตุฉุกเฉิน
- มีทั้งประโยคสั้นตื่นตระหนก, ประโยคถาม, ประโยคบรรยายเหตุการณ์
- มี linguistic noise ได้เล็กน้อย เช่น พิมพ์ตกคำ, เว้นวรรคผิด, อุทาน เช่น "ช่วยด้วย", "เร็วๆ"
- แต่ต้องยังอ่านเข้าใจชัดเจน

Few-shot ตัวอย่าง (ย่อ):
อินพุตเคส:
- case_name_th: เลือดออกรุนแรง
- keywords: เลือดพุ่ง, แผลใหญ่, โดนแทง
- severity: critical
- facility_type: hospital
ผลลัพธ์ที่ดี:
1) "ช่วยด้วยครับ! โดนมีดแทง เลือดพุ่งไม่หยุดเลย"
2) "ต้องทำยังไงก่อนครับ แผลใหญ่มาก ผ้าชุ่มเลือดหมดแล้ว"
3) "ตรงพื้นเลือดเยอะมาก คนเจ็บเริ่มซีด มือเย็นแล้ว"

กติกาบังคับ:
- ตอบเป็น JSON เท่านั้น
- รูปแบบ: {"items": [{"input":"...","guidance":"...","severity":"...","facility_type":"..."}]}
- ต้องมี items = 10 รายการพอดี
- input ต้องไม่ซ้ำกัน
- input ต้องเป็นประโยคคนพูดจริงเท่านั้น ห้ามส่ง token/คีย์ JSON เช่น "{", "}", "[", "]", "\"items\":", "\"input\":"
- guidance ต้องละเอียดพอและใกล้เคียงกับ Detailed Guidance ต้นฉบับ
""".strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate synthetic Thai emergency user inputs via Gemini."
    )
    parser.add_argument("--input-csv", default=DEFAULT_INPUT_CSV, help="Input CSV path")
    parser.add_argument("--output-jsonl", default=DEFAULT_OUTPUT_JSONL, help="Output JSONL path")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Gemini model name")
    parser.add_argument("--sleep-seconds", type=float, default=2.0, help="Rate-limit sleep per scenario")
    parser.add_argument("--max-retries", type=int, default=3, help="Max retries per API call")
    parser.add_argument(
        "--max-rounds",
        type=int,
        default=1,
        help="Generation rounds per scenario (1 is fastest; keep exactly-10 via fallback fill).",
    )
    parser.add_argument(
        "--api-timeout-seconds",
        type=float,
        default=45.0,
        help="Per-request timeout guard in seconds.",
    )
    parser.add_argument("--max-scenarios", type=int, default=0, help="Limit scenario count (0 = all)")
    parser.add_argument("--start-index", type=int, default=0, help="Start scenario index (for resume)")
    parser.add_argument(
        "--api-key-env",
        default="GEMINI_API_KEY",
        help="Environment variable for Gemini API key (fallback: GOOGLE_API_KEY)",
    )
    parser.add_argument(
        "--instruction-text",
        default=DEFAULT_INSTRUCTION,
        help="Instruction field value for output JSONL",
    )
    return parser.parse_args()


def normalize_text(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


def normalize_severity(v: str) -> str:
    s = normalize_text(v).lower()
    if s in {"critical", "mild", "none"}:
        return s
    if s in {"no need", "nan", "na", "n/a", "normal"}:
        return "none"
    return "none"


def normalize_facility(v: str) -> str:
    s = normalize_text(v).lower()
    if s in {"hospital", "clinic", "none"}:
        return s
    if s in {"nan", "na", "n/a", "no need"}:
        return "none"
    return "none"


def looks_like_json_fragment(text: str) -> bool:
    t = normalize_text(text)
    if not t:
        return True
    lowered = t.lower().strip()
    if lowered in {"{", "}", "[", "]", ",", ":"}:
        return True
    fragment_patterns = [
        r"^\{.*$",
        r"^\}.*$",
        r"^\[.*$",
        r"^\].*$",
        r'^".*":\s*.*$',
        r'^"items"\s*:\s*\[$',
        r'^"input"\s*:\s*.*$',
        r'^"guidance"\s*:\s*.*$',
        r'^"severity"\s*:\s*.*$',
        r'^"facility_type"\s*:\s*.*$',
    ]
    return any(re.match(p, lowered) for p in fragment_patterns)


def sanitize_user_input_candidate(v: Any) -> str:
    t = normalize_text(v)
    if not t:
        return ""
    t = t.strip().strip(",")
    if (t.startswith('"') and t.endswith('"')) or (t.startswith("'") and t.endswith("'")):
        t = t[1:-1].strip()
    t = re.sub(r"\s+", " ", t).strip()
    return t


def is_valid_user_input(text: str) -> bool:
    t = sanitize_user_input_candidate(text)
    if not t:
        return False
    if len(t) < 8:
        return False
    if looks_like_json_fragment(t):
        return False
    if t.count("{") + t.count("}") + t.count("[") + t.count("]") >= 2:
        return False
    if re.search(r'"\s*:\s*', t):
        return False
    return True


def sanitize_guidance_candidate(v: Any) -> str:
    t = normalize_text(v)
    if not t:
        return ""
    if looks_like_json_fragment(t):
        return ""
    return t


def load_scenarios(csv_path: str) -> List[Dict[str, str]]:
    scenarios: List[Dict[str, str]] = []
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            case_name_en = normalize_text(row.get("Case Name (EN)", ""))
            case_name_th = normalize_text(row.get("Case Name (TH)", ""))
            keywords = normalize_text(row.get("Keywords", ""))
            instructions = normalize_text(row.get("Instructions", ""))
            severity = normalize_severity(row.get("severity", ""))
            facility_type = normalize_facility(row.get("facility_type", ""))

            if not instructions:
                continue

            scenarios.append(
                {
                    "case_name_en": case_name_en,
                    "case_name_th": case_name_th,
                    "keywords": keywords,
                    "instructions": instructions,
                    "severity": severity,
                    "facility_type": facility_type,
                }
            )
    return scenarios


def build_user_prompt(s: Dict[str, str], already_generated: Optional[List[str]] = None, needed: int = 10) -> str:
    existing_block = ""
    if already_generated:
        numbered = "\n".join([f"- {x}" for x in already_generated])
        existing_block = (
            "\nมีประโยคที่สร้างแล้ว (ห้ามซ้ำ):\n"
            f"{numbered}\n"
            f"โปรดสร้างเพิ่มอีก {needed} ประโยคใหม่ที่ไม่ซ้ำกับรายการด้านบน"
        )

    return f"""
สร้างประโยคผู้ใช้ภาษาไทยสำหรับเคสฉุกเฉินนี้

Case Name (TH): {s['case_name_th']}
Case Name (EN): {s['case_name_en']}
Keywords: {s['keywords']}
Detailed Guidance (ห้ามเปลี่ยนความหมายเคส):
{s['instructions']}
Severity: {s['severity']}
Facility Type: {s['facility_type']}

ข้อกำหนดรูปแบบและสไตล์:
1) ต้องสร้างประโยคทั้งหมด {needed} ประโยค
2) ประโยคต้องไม่ซ้ำกัน และต้องยังเป็นเคสเดียวกันทั้งหมด
3) ให้มีความหลากหลายตามนี้:
   - ประโยคที่ 1: สั้นมาก + ตื่นตระหนก
   - ประโยคที่ 2: เป็นคำถามขอวิธีช่วย
   - ประโยคที่ 3: บรรยายภาพที่เห็นเลือด/อาการชัดเจน
   - ประโยคที่ 4: ญาติหรือคนรอบตัวเล่าเหตุการณ์
   - ประโยคที่ 5: มีข้อมูลเวลา/สถานที่แบบบ้านๆ
   - ประโยคที่ 6: มี linguistic noise เล็กน้อย (พิมพ์ผิด/อุทาน)
   - ประโยคที่ 7: ภาษาพูดกึ่งสแลง
   - ประโยคที่ 8: เน้นอาการทรุดลง
   - ประโยคที่ 9: มีความเข้าใจผิดหรือกำลังจะทำผิด แล้วถามยืนยัน
   - ประโยคที่ 10: ยาวและละเอียดเหมือนเล่าเหตุการณ์ต่อเนื่อง
4) ทุกประโยคต้องสมจริงแบบคนไทยในภาวะเครียด
4.1) input ต้องเป็นประโยคพูดจริงเท่านั้น ห้ามใส่คีย์ JSON หรือวงเล็บโครงสร้าง
4.2) guidance ต่อรายการให้กระชับแต่ครบสาระสำคัญ ไม่เกิน ~700 อักขระ
5) ห้ามมี markdown
6) ตอบเป็น JSON เท่านั้น รูปแบบ:
{{
  "items": [
    {{
      "input": "ประโยคผู้ใช้",
      "guidance": "คำแนะนำที่สอดคล้องกับเคส (ละเอียด) บอกเป็นขั้นตอน หากเป็นเหตุฉุกเฉินให้เริ่มด้วย 'สถานการณ์นี้เป็นเหตุฉุกเฉิน' หากไม่ฉุกเฉินให้เริ่มด้วย 'สถานการณ์นี้ไม่ใช่เหตุฉุกเฉิน'",
      "severity": "critical|mild|none",
      "facility_type": "hospital|clinic|none"
    }}
  ]
}}
{existing_block}
""".strip()


def extract_json_block(text: str) -> Optional[str]:
    raw = normalize_text(text)
    if not raw:
        return None

    # Remove code fences if present.
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)

    if raw.startswith("{") and raw.endswith("}"):
        return raw

    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        return raw[start : end + 1]
    return None


def parse_items_from_response(text: str) -> List[Dict[str, str]]:
    block = extract_json_block(text)
    if not block:
        return []

    try:
        payload = json.loads(block)
    except json.JSONDecodeError:
        return []

    if not isinstance(payload, dict):
        return []

    parsed_items: List[Dict[str, str]] = []

    # Preferred format: {"items":[{"input","guidance","severity","facility_type"}, ...]}
    items = payload.get("items", [])
    if isinstance(items, list):
        for it in items:
            if not isinstance(it, dict):
                continue
            inp = sanitize_user_input_candidate(it.get("input", ""))
            if not is_valid_user_input(inp):
                continue
            parsed_items.append(
                {
                    "input": inp,
                    "guidance": sanitize_guidance_candidate(it.get("guidance", "")),
                    "severity": normalize_severity(it.get("severity", "")),
                    "facility_type": normalize_facility(it.get("facility_type", "")),
                }
            )
        if parsed_items:
            return parsed_items

    # Backward-compatible format: {"inputs":[...]}
    vals = payload.get("inputs", [])
    if isinstance(vals, list):
        for x in vals:
            inp = sanitize_user_input_candidate(x)
            if not is_valid_user_input(inp):
                continue
            parsed_items.append(
                {
                    "input": inp,
                    "guidance": "",
                    "severity": "none",
                    "facility_type": "none",
                }
            )
    return parsed_items


def dedupe_items_keep_order(items: List[Dict[str, str]]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    seen = set()
    for item in items:
        raw_input = normalize_text(item.get("input", ""))
        key = re.sub(r"\s+", " ", raw_input.strip().lower())
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "input": raw_input,
                "guidance": normalize_text(item.get("guidance", "")),
                "severity": normalize_severity(item.get("severity", "")),
                "facility_type": normalize_facility(item.get("facility_type", "")),
            }
        )
    return out


def extract_keywords_list(text: str) -> List[str]:
    raw = normalize_text(text)
    if not raw:
        return []
    parts = [normalize_text(x) for x in re.split(r"[,|/]| หรือ | or ", raw, flags=re.IGNORECASE)]
    return [x for x in parts if x]


def build_fallback_inputs(
    scenario: Dict[str, str], existing: Optional[List[Dict[str, str]]] = None, needed: int = 10
) -> List[Dict[str, str]]:
    case_name = scenario.get("case_name_th", "") or scenario.get("case_name_en", "เหตุฉุกเฉิน")
    kws = extract_keywords_list(scenario.get("keywords", ""))
    kw1 = kws[0] if kws else case_name
    kw2 = kws[1] if len(kws) > 1 else case_name
    kw_text = " / ".join(kws[:2]) if kws else case_name
    kw_joined = " ".join(kws).lower()
    has_blood_signal = any(x in kw_joined for x in ["เลือด", "แผล", "แทง", "ฉีก", "ตัด"])
    scene_desc = (
        f"เห็นเลือดออกเยอะมากจากอาการ{kw2} ตอนนี้หน้าซีดแล้ว ทำยังไงดี"
        if has_blood_signal
        else f"เห็นอาการ{kw2}ชัดมาก ตอนนี้คนเจ็บเริ่มทรุดลง ทำยังไงดี"
    )

    templates = [
        f"ช่วยด้วย! มีคน{case_name} อาการหนักมากครับ",
        f"ตอนนี้คนเจ็บมีอาการ{kw_text} ต้องเริ่มช่วยยังไงก่อนครับ",
        scene_desc,
        f"หนูเป็นญาติค่ะ คนในบ้าน{case_name} ไม่ค่อยตอบสนองแล้ว ช่วยบอกขั้นตอนที",
        f"อยู่หน้าบ้านตอนนี้ คนเจ็บ{kw1} ผ่านไปประมาณ 5 นาทีแล้ว ต้องทำอะไรก่อน",
        f"ช่วยด้วยค่ะ มือสั่นมาก คนเจ็บ{case_name} เร็วๆต้องทำไง",
        f"โคตรแย่เลยครับ เห็นอาการ{kw2} ชัดมาก ผมควรทำอะไรก่อน",
        f"อาการแย่ลงเร็วมาก คนเจ็บเริ่มหมดแรงจาก{case_name} ต้องรีบทำอะไร",
        f"ถ้าจะขยับตัวคนเจ็บตอน{case_name}ได้ไหม หรือควรรอรถพยาบาลก่อน",
        f"ขอคำแนะนำละเอียดหน่อยค่ะ ตอนนี้มีคน{case_name} และคนรอบข้างเริ่มแตกตื่น",
        f"ช่วยทีครับ ผู้ป่วย{kw1} ตอนนี้หายใจไม่สม่ำเสมอ ผมต้องทำขั้นตอนไหนก่อน",
        f"มีเหตุ{case_name}กลางถนนครับ คนเจ็บร้องมาก แล้วเริ่มเงียบลง ผมควรช่วยยังไง",
    ]

    seen = set()
    if existing:
        for item in existing:
            key = re.sub(r"\s+", " ", normalize_text(item.get("input", "")).lower()).strip()
            if key:
                seen.add(key)

    out: List[Dict[str, str]] = []
    for t in templates:
        t = sanitize_user_input_candidate(t)
        key = re.sub(r"\s+", " ", t.lower()).strip()
        if not is_valid_user_input(t) or key in seen:
            continue
        seen.add(key)
        out.append({"input": t, "guidance": "", "severity": "none", "facility_type": "none"})
        if len(out) >= needed:
            return out

    idx = 1
    while len(out) < needed:
        t = sanitize_user_input_candidate(
            f"ช่วยด้วยครับ คนเจ็บ{case_name} อาการหนักมาก ตอนนี้ต้องทำอะไรเป็นขั้นตอน"
        )
        if idx > 1:
            t = f"{t} ({idx})"
        key = re.sub(r"\s+", " ", t.lower()).strip()
        idx += 1
        if key in seen or not is_valid_user_input(t):
            continue
        seen.add(key)
        out.append({"input": t, "guidance": "", "severity": "none", "facility_type": "none"})
    return out


def call_gemini_json_inputs(
    client: Any,
    model_name: str,
    scenario: Dict[str, str],
    max_retries: int,
    max_rounds: int,
    api_timeout_seconds: float,
) -> List[Dict[str, str]]:
    # First call should generate 10 in one go.
    prompt = build_user_prompt(scenario, already_generated=None, needed=10)
    all_items: List[Dict[str, str]] = []

    for _ in range(max(1, max_rounds)):
        text = ""
        for attempt in range(1, max_retries + 1):
            try:
                def _invoke() -> Any:
                    return client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=SYSTEM_PROMPT,
                            temperature=0.25,
                            response_mime_type="application/json",
                            max_output_tokens=2200,
                        ),
                    )

                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(_invoke)
                    response = future.result(timeout=api_timeout_seconds)
                text = normalize_text(getattr(response, "text", ""))
                if not text:
                    # Some Gemini SDK responses store content in candidates.
                    text = normalize_text(str(response))
                break
            except Exception as exc:
                if isinstance(exc, concurrent.futures.TimeoutError):
                    if attempt >= max_retries:
                        raise TimeoutError(
                            f"Gemini request timed out after {api_timeout_seconds}s"
                        ) from exc
                    time.sleep(2 * attempt)
                    continue
                if is_non_retryable_gemini_error(exc):
                    raise
                if attempt >= max_retries:
                    raise
                time.sleep(2 * attempt)

        got = dedupe_items_keep_order(parse_items_from_response(text))
        if got:
            all_items.extend(got)
            all_items = dedupe_items_keep_order(all_items)

        if len(all_items) >= 10:
            return all_items[:10]

        missing = 10 - len(all_items)
        prompt = build_user_prompt(
            scenario,
            already_generated=[x["input"] for x in all_items],
            needed=missing,
        )

    # Final fallback: fill with scenario-aware panic sentences to keep exactly 10.
    all_items = dedupe_items_keep_order(all_items)
    if len(all_items) >= 10:
        return all_items[:10]
    all_items.extend(build_fallback_inputs(scenario, existing=all_items, needed=10 - len(all_items)))
    all_items = dedupe_items_keep_order(all_items)
    return all_items[:10]


def format_output_text(guidance: str, severity: str, facility_type: str) -> str:
    sev_map = {"critical": "Critical", "mild": "Mild", "none": "None"}
    fac_map = {"hospital": "Hospital (ER)", "clinic": "Clinic", "none": "None"}
    sev = sev_map.get(normalize_severity(severity), "None")
    fac = fac_map.get(normalize_facility(facility_type), "None")
    return f"{guidance} | ความรุนแรง: {sev} | สถานพยาบาล: {fac}"


def get_api_key(env_name: str) -> str:
    key = os.getenv(env_name, "").strip()
    if not key:
        key = os.getenv("GOOGLE_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            f"Gemini API key not found. Set {env_name} or GOOGLE_API_KEY in environment."
        )
    return key


def is_non_retryable_gemini_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    hard_signals = [
        "not found",
        "unsupported for generatecontent",
        "permission denied",
        "api key not valid",
        "invalid argument",
    ]
    return any(x in msg for x in hard_signals)


def normalize_model_name(name: str) -> str:
    n = normalize_text(name)
    if n.startswith("models/"):
        return n.split("/", 1)[1]
    # Compatibility alias: some docs/examples say gemini-3-flash, but API serves preview id.
    if n == "gemini-3-flash":
        return "gemini-3-flash-preview"
    return n


def split_guidance_steps(text: str) -> List[str]:
    raw = normalize_text(text)
    if not raw:
        return []

    rows = []
    for line in raw.splitlines():
        l = normalize_text(line)
        if l:
            rows.append(l)
    if not rows:
        rows = [raw]

    steps: List[str] = []
    for line in rows:
        line = re.sub(r"^\d+[\)\.\-:\s]+", "", line).strip()
        line = re.sub(r"\s+", " ", line)
        if not line:
            continue
        steps.append(line)
    return steps


def merge_unique_steps(primary: List[str], secondary: List[str], max_steps: int) -> List[str]:
    out: List[str] = []
    seen = set()
    for src in (primary, secondary):
        for s in src:
            key = re.sub(r"\s+", " ", s.lower()).strip()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(s)
            if len(out) >= max_steps:
                return out
    return out


def build_enriched_guidance(scenario: Dict[str, str], model_guidance: str) -> str:
    severity = scenario.get("severity", "none")
    facility = scenario.get("facility_type", "none")
    scenario_steps = split_guidance_steps(scenario.get("instructions", ""))
    model_steps = split_guidance_steps(sanitize_guidance_candidate(model_guidance))
    merged_core = merge_unique_steps(model_steps, scenario_steps, max_steps=6)

    extra: List[str] = []
    if severity == "critical":
        extra.append("โทร 1669 ทันทีและเปิดลำโพง เพื่อทำตามคำแนะนำของเจ้าหน้าที่ระหว่างช่วยเหลือ")
        extra.append("เฝ้าดูการหายใจ ระดับความรู้สึกตัว และอาการทรุดลงอย่างต่อเนื่องจนกว่าทีมแพทย์มาถึง")
    elif severity == "mild":
        extra.append("หากอาการแย่ลง เช่น ปวดมากขึ้น ซึมลง หรือหายใจลำบาก ให้ยกระดับเป็นเหตุฉุกเฉินและโทร 1669")
    else:
        extra.append("ติดตามอาการอย่างใกล้ชิด หากมีอาการผิดปกติรุนแรงให้โทร 1669 ทันที")

    if facility == "hospital":
        extra.append("เตรียมข้อมูลสำคัญ เช่น เวลาเริ่มอาการ โรคประจำตัว ยาที่ใช้ และสิ่งที่ได้ปฐมพยาบาลไปแล้ว เพื่อส่งต่อทีม ER")
    elif facility == "clinic":
        extra.append("เมื่ออาการคงที่ให้ไปคลินิกหรือสถานพยาบาลใกล้บ้านเพื่อประเมินเพิ่มเติม")

    all_steps = merge_unique_steps(merged_core, extra, max_steps=8)
    if not all_steps:
        all_steps = [
            "ประเมินความปลอดภัยของพื้นที่และผู้ช่วยเหลือก่อนเข้าใกล้ผู้ป่วย",
            "โทร 1669 เพื่อขอคำแนะนำและเรียกรถพยาบาลเมื่อมีอาการรุนแรง",
            "เฝ้าดูอาการจนกว่าผู้เชี่ยวชาญจะมาถึง",
        ]

    header = "สถานการณ์นี้เป็นเหตุฉุกเฉิน" if severity == "critical" else "สถานการณ์นี้ไม่ใช่เหตุฉุกเฉิน"
    numbered = "\n".join([f"{i}. {step}" for i, step in enumerate(all_steps, start=1)])
    return f"{header}\n{numbered}"


def main() -> None:
    args = parse_args()

    if not os.path.exists(args.input_csv):
        raise FileNotFoundError(f"Input CSV not found: {args.input_csv}")

    api_key = get_api_key(args.api_key_env)
    client = genai.Client(api_key=api_key)
    selected_model = normalize_model_name(args.model or DEFAULT_MODEL)
    print(f"Using Gemini model: {selected_model}")

    scenarios = load_scenarios(args.input_csv)
    if args.start_index > 0:
        scenarios = scenarios[args.start_index :]
    if args.max_scenarios > 0:
        scenarios = scenarios[: args.max_scenarios]

    os.makedirs(os.path.dirname(args.output_jsonl), exist_ok=True)

    generated_rows = 0
    with open(args.output_jsonl, "w", encoding="utf-8") as f_out:
        for scenario in tqdm(scenarios, desc="Augmenting scenarios", unit="scenario"):
            try:
                synthetic_items = call_gemini_json_inputs(
                    client=client,
                    model_name=selected_model,
                    scenario=scenario,
                    max_retries=args.max_retries,
                    max_rounds=args.max_rounds,
                    api_timeout_seconds=args.api_timeout_seconds,
                )
            except Exception as exc:
                print(
                    f"[WARN] Failed scenario '{scenario.get('case_name_th', '')}': {exc}"
                )
                time.sleep(args.sleep_seconds)
                continue

            for item in synthetic_items[:10]:
                user_input = sanitize_user_input_candidate(item.get("input", ""))
                if not is_valid_user_input(user_input):
                    continue
                item_guidance = build_enriched_guidance(
                    scenario=scenario,
                    model_guidance=normalize_text(item.get("guidance", "")),
                )
                item_severity = normalize_severity(item.get("severity", "")) or scenario["severity"]
                item_facility = normalize_facility(item.get("facility_type", "")) or scenario["facility_type"]

                # Force mapping consistency to original scenario when model drifts.
                if item_severity != scenario["severity"]:
                    item_severity = scenario["severity"]
                if item_facility != scenario["facility_type"]:
                    item_facility = scenario["facility_type"]

                record = {
                    "instruction": args.instruction_text,
                    "input": user_input,
                    "guidance": item_guidance,
                    "severity": item_severity,
                    "facility_type": item_facility,
                    "output": format_output_text(
                        guidance=item_guidance,
                        severity=item_severity,
                        facility_type=item_facility,
                    ),
                }
                f_out.write(json.dumps(record, ensure_ascii=False) + "\n")
                generated_rows += 1

            time.sleep(args.sleep_seconds)

    print(f"Done. Generated {generated_rows} augmented rows.")
    print(f"Saved JSONL: {args.output_jsonl}")


if __name__ == "__main__":
    main()
