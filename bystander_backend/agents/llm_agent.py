import json
import os
import re
from typing import Any, Dict, Optional

from dotenv import load_dotenv

try:
    from google import genai
    from google.genai import types
except Exception:  # pragma: no cover
    genai = None
    types = None


ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
load_dotenv(dotenv_path=ENV_PATH, override=True)


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


def _parse_json_fallback(text: str, default: Dict[str, Any]) -> Dict[str, Any]:
    block = _extract_json_block(text)
    if not block:
        return default
    try:
        payload = json.loads(block)
        if isinstance(payload, dict):
            out = dict(default)
            out.update(payload)
            return out
        return default
    except Exception:
        return default


class GeminiJSONAgent:
    def __init__(self) -> None:
        self.api_key = _normalize_text(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
        self.client = genai.Client(api_key=self.api_key) if self.api_key and genai else None

    def generate_json(
        self,
        model_name: str,
        system_prompt: str,
        user_prompt: str,
        default: Dict[str, Any],
        temperature: float = 0.1,
    ) -> Dict[str, Any]:
        if self.client is None or types is None:
            return dict(default)

        try:
            response = self.client.models.generate_content(
                model=model_name,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=temperature,
                    response_mime_type="application/json",
                    max_output_tokens=2048,
                ),
            )
            text = _normalize_text(getattr(response, "text", ""))
            if not text:
                text = _normalize_text(str(response))
            return _parse_json_fallback(text, default)
        except Exception:
            return dict(default)


class TriageAgent:
    """llmAgent: Gemini 2.5 Flash triage agent."""

    def __init__(self, llm: GeminiJSONAgent) -> None:
        self.llm = llm
        self.model_name = _normalize_text(os.getenv("TRIAGE_MODEL")) or "gemini-2.5-flash"

    def run(self, scenario: str) -> Dict[str, Any]:
        default = {
            "is_emergency": True,
            "severity": "moderate",
            "facility_type": "clinic",
            "reason_th": "ไม่สามารถประเมินได้ชัดเจน จึงแนะนำให้ถือเป็นเหตุฉุกเฉินระดับปานกลาง",
        }
        system_prompt = (
            "You are llmAgent for ByStander emergency triage. "
            "Return strict JSON only with fields: is_emergency (bool), "
            "severity (critical|moderate|none), facility_type (hospital|clinic|none), reason_th (Thai)."
        )
        user_prompt = (
            f"Scenario: {scenario}\n"
            "Rules:\n"
            "- If clearly non-emergency daily issue => is_emergency=false, severity=none, facility_type=none\n"
            "- If life-threatening => critical + hospital\n"
            "- If emergency but not immediately life-threatening => moderate + clinic\n"
            "Output JSON only."
        )
        out = self.llm.generate_json(
            model_name=self.model_name,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            default=default,
            temperature=0.0,
        )
        out["is_emergency"] = bool(out.get("is_emergency", True))
        sev = _normalize_text(out.get("severity", "moderate")).lower()
        out["severity"] = sev if sev in {"critical", "moderate", "none"} else "moderate"
        fac = _normalize_text(out.get("facility_type", "clinic")).lower()
        out["facility_type"] = fac if fac in {"hospital", "clinic", "none"} else "clinic"
        out["reason_th"] = _normalize_text(out.get("reason_th")) or default["reason_th"]
        return out


class GuidanceAgent:
    """GuidanceAgent: model switch by severity + RAG context."""

    def __init__(self, llm: GeminiJSONAgent) -> None:
        self.llm = llm
        self.critical_model = _normalize_text(os.getenv("GUIDANCE_CRITICAL_MODEL")) or "gemini-3-flash-preview"
        self.moderate_model = _normalize_text(os.getenv("GUIDANCE_MODERATE_MODEL")) or "gemini-2.5-pro"

    def run(self, scenario: str, severity: str, rag_context: str) -> Dict[str, Any]:
        model_name = self.critical_model if severity == "critical" else self.moderate_model
        default = {
            "guidance": (
                "สถานการณ์นี้เป็นเหตุฉุกเฉิน\n"
                "1. ประเมินความปลอดภัยของพื้นที่\n"
                "2. โทร 1669 ทันที\n"
                "3. ปฐมพยาบาลตามอาการเท่าที่ปลอดภัย\n"
                "4. เฝ้าระวังอาการจนกว่าทีมแพทย์มาถึง"
            ),
            "facility_type": "hospital" if severity == "critical" else "clinic",
        }
        system_prompt = (
            "You are GuidanceAgent for emergency first-aid in Thai. "
            "Use retrieved protocol context as primary source. "
            "Output strict JSON only with fields: guidance, facility_type. "
            "Guidance must be step-by-step, no markdown."
        )
        user_prompt = (
            f"Scenario: {scenario}\n"
            f"Severity: {severity}\n"
            f"Retrieved medical protocol context:\n{rag_context}\n\n"
            "Constraints:\n"
            "- If severe emergency, guidance should start with: สถานการณ์นี้เป็นเหตุฉุกเฉิน\n"
            "- Use concise numbered Thai steps\n"
            "- Include immediate call to 1669 when emergency\n"
            "- facility_type must be one of hospital|clinic|none\n"
            "Output JSON only."
        )
        out = self.llm.generate_json(
            model_name=model_name,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            default=default,
            temperature=0.15,
        )
        out["guidance"] = _normalize_text(out.get("guidance")) or default["guidance"]
        facility = _normalize_text(out.get("facility_type", default["facility_type"])).lower()
        out["facility_type"] = facility if facility in {"hospital", "clinic", "none"} else default["facility_type"]
        return out


class ScriptAgent:
    """ScriptAgent: generate call script using user medical profile."""

    def __init__(self, llm: GeminiJSONAgent) -> None:
        self.llm = llm
        self.model_name = _normalize_text(os.getenv("SCRIPT_MODEL")) or "gemini-2.5-flash"

    def run(
        self,
        scenario: str,
        guidance: str,
        user_profile: Dict[str, Any],
        location_context: str = "",
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
    ) -> str:
        default = {
            "call_script": (
                "สวัสดีค่ะ/ครับ ต้องการแจ้งเหตุฉุกเฉิน\n"
                "1) สถานการณ์: ...\n"
                "2) จุดเกิดเหตุ: ...\n"
                "3) อาการผู้ป่วย: ...\n"
                "4) ข้อมูลโรคประจำตัว/ยาที่แพ้ (ถ้ามี): ...\n"
                "5) เบอร์ติดต่อกลับ: ..."
            )
        }
        system_prompt = (
            "You are ScriptAgent for emergency operator call assistance in Thai. "
            "Generate concise speaking script. "
            "If location context is provided, include exact location cues (address/nearby landmarks) clearly. "
            "Output JSON only with key: call_script."
        )
        user_prompt = (
            f"Scenario: {scenario}\n"
            f"Guidance: {guidance}\n"
            f"User medical profile: {json.dumps(user_profile, ensure_ascii=False)}\n\n"
            f"Latitude: {latitude}\n"
            f"Longitude: {longitude}\n"
            f"Location context from maps:\n{location_context}\n\n"
            "Build a Thai phone script the user can read to emergency operator.\n"
            "Requirements:\n"
            "- Include a direct sentence the user can say about location.\n"
            "- If location context exists, mention at least 1-2 nearby landmarks/place names.\n"
            "- Keep it short, urgent, and easy to read out loud."
        )
        out = self.llm.generate_json(
            model_name=self.model_name,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            default=default,
            temperature=0.2,
        )
        return _normalize_text(out.get("call_script")) or default["call_script"]
