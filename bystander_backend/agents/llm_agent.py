import json
import os
import re
import sys
import warnings
from typing import Any

from dotenv import load_dotenv

try:
    from google import genai
    from google.genai import types
except Exception:  # pragma: no cover
    genai = None
    types = None

try:
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None

try:
    import vertexai
    from vertexai.generative_models import GenerationConfig, GenerativeModel
except Exception:  # pragma: no cover
    vertexai = None
    GenerationConfig = None
    GenerativeModel = None

# Suppress Vertex AI deprecation warning spam in runtime logs.
warnings.filterwarnings(
    "ignore",
    message=r"This feature is deprecated as of June 24, 2025.*",
    category=UserWarning,
)

if __package__:
    from .observability import observe, record_exception
else:  # pragma: no cover
    current_dir = os.path.dirname(os.path.abspath(__file__))
    if current_dir not in sys.path:
        sys.path.insert(0, current_dir)
    from observability import observe, record_exception


ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
load_dotenv(dotenv_path=ENV_PATH, override=True)


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _extract_json_block(text: str) -> str | None:
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


def _parse_json_fallback(text: str, default: dict[str, Any]) -> dict[str, Any]:
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


def _canonical_model_name(model_name: str) -> str:
    name = _normalize_text(model_name)
    if not name:
        return "gemini-2.5-flash"
    aliases = {
        "gemini-3-flash": "gemini-2.5-flash",
        "gemini-3-flash-preview": "gemini-2.5-flash",
        "gemini-3.1-flash-lite-preview": "gemini-2.5-flash",
        "models/gemini-3-flash": "gemini-2.5-flash",
        "models/gemini-3-flash-preview": "gemini-2.5-flash",
        "models/gemini-3.1-flash-lite-preview": "gemini-2.5-flash",
        "models/gemini-2.5-flash": "gemini-2.5-flash",
        "models/gemini-2.5-pro": "gemini-2.5-pro",
        "gemini-2.5-flash-lite": "gemini-2.5-flash",
        "models/gemini-2.5-flash-lite": "gemini-2.5-flash",
    }
    return aliases.get(name, name)


def _model_candidates(model_name: str) -> list[str]:
    canonical = _canonical_model_name(model_name)
    if not canonical:
        return ["gemini-2.5-flash"]
    return [canonical]


class GeminiJSONAgent:
    def __init__(self) -> None:
        self.api_key = _normalize_text(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
        self.client = genai.Client(api_key=self.api_key) if self.api_key and genai else None
        self.vertex_project = _normalize_text(os.getenv("GOOGLE_CLOUD_PROJECT"))
        self.vertex_location = _normalize_text(
            os.getenv("VERTEX_RAG_LOCATION") or os.getenv("VERTEX_LOCATION") or "us-central1"
        )
        self.vertex_enabled = False
        if vertexai and GenerativeModel and self.vertex_project:
            try:
                vertexai.init(project=self.vertex_project, location=self.vertex_location)
                self.vertex_enabled = True
            except Exception as exc:
                record_exception(exc)

    @staticmethod
    def _response_text(response: Any) -> str:
        text = _normalize_text(getattr(response, "text", ""))
        if text:
            return text
        candidates = getattr(response, "candidates", None) or []
        for candidate in candidates:
            content = getattr(candidate, "content", None)
            parts = getattr(content, "parts", None) or []
            for part in parts:
                maybe = _normalize_text(getattr(part, "text", ""))
                if maybe:
                    return maybe
        return _normalize_text(str(response))

    @observe()
    def _generate_json_with_vertex(
        self,
        model_name: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
    ) -> str:
        if not self.vertex_enabled or GenerativeModel is None or GenerationConfig is None:
            raise RuntimeError("Vertex AI Gemini SDK is not available")

        model = GenerativeModel(
            model_name=model_name,
            system_instruction=[system_prompt],
        )
        response = model.generate_content(
            user_prompt,
            generation_config=GenerationConfig(
                temperature=temperature,
                max_output_tokens=2048,
                response_mime_type="application/json",
            ),
        )
        return self._response_text(response)

    @observe()
    def _generate_json_with_google_genai(
        self,
        model_name: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
    ) -> str:
        if self.client is None or types is None:
            raise RuntimeError("google-genai client is unavailable")

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
        return self._response_text(response)

    @observe()
    def generate_json(
        self,
        model_name: str,
        system_prompt: str,
        user_prompt: str,
        default: dict[str, Any],
        temperature: float = 0.1,
    ) -> dict[str, Any]:
        # Primary path: Vertex AI SDK call (auto-instrumented by VertexAIInstrumentor).
        for candidate_model in _model_candidates(model_name):
            try:
                text = self._generate_json_with_vertex(
                    model_name=candidate_model,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=temperature,
                )
                return _parse_json_fallback(text, default)
            except Exception as exc:
                record_exception(exc)

        # Fallback path: existing google-genai API client.
        for candidate_model in _model_candidates(model_name):
            try:
                text = self._generate_json_with_google_genai(
                    model_name=candidate_model,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=temperature,
                )
                return _parse_json_fallback(text, default)
            except Exception as exc:
                record_exception(exc)
        return dict(default)


class TriageAgent:
    """llmAgent: Gemini 2.5 Flash triage agent."""

    def __init__(self, llm: GeminiJSONAgent) -> None:
        self.llm = llm
        self.model_name = _normalize_text(os.getenv("TRIAGE_MODEL")) or "gemini-2.5-flash"

    @observe()
    def run(self, scenario: str) -> dict[str, Any]:
        default = {
            "is_emergency": True,
            "severity": "moderate",
            "facility_type": "clinic",
            "reason_th": "ไม่สามารถประเมินได้ชัดเจน จึงแนะนำให้ถือเป็นเหตุฉุกเฉินระดับปานกลาง",
        }
        system_prompt = (
            "You are llmAgent for ByStander emergency triage. "
            "Return strict JSON only with fields: is_emergency (bool), "
            "severity (critical|moderate|none), facility_type (hospital|clinic|none), "
            "reason_th (Thai)."
        )
        user_prompt = (
            f"Scenario: {scenario}\n"
            "Rules:\n"
            "- If clearly non-emergency daily issue => is_emergency=false,"
            "severity=none, facility_type=none\n"
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
        default_guidance_model = "gemini-2.5-flash"
        self.critical_model = (
            _normalize_text(os.getenv("GUIDANCE_CRITICAL_MODEL")) or default_guidance_model
        )
        self.moderate_model = (
            _normalize_text(os.getenv("GUIDANCE_MODERATE_MODEL")) or default_guidance_model
        )
        self.deepseek_model = _normalize_text(os.getenv("DEEPSEEK_FAST_MODEL")) or "deepseek-chat"
        self.deepseek_key = _normalize_text(os.getenv("DEEPSEEK_KEY"))
        self.deepseek_client = None
        if self.deepseek_key and OpenAI is not None:
            try:
                self.deepseek_client = OpenAI(
                    api_key=self.deepseek_key, base_url="https://api.deepseek.com"
                )
            except Exception as exc:
                record_exception(exc)

    @staticmethod
    def _clean_rag_snippets(rag_context: str, max_snippets: int = 6, max_chars: int = 1600) -> str:
        text = _normalize_text(rag_context)
        if not text:
            return ""
        chunks = re.split(r"\n\s*\n", text)
        snippets = []
        seen = set()
        for chunk in chunks:
            lines = []
            for line in chunk.splitlines():
                ln = _normalize_text(line)
                if not ln:
                    continue
                lower = ln.lower()
                if lower.startswith("[protocol") or lower.startswith("[vertex protocol"):
                    continue
                if lower.startswith("- keywords:"):
                    continue
                if lower.startswith("- severity:") or lower.startswith("- facility:"):
                    continue
                if lower.startswith("- source="):
                    continue
                ln = re.sub(r"\s+", " ", ln)
                lines.append(ln)
            cleaned = " ".join(lines).strip()
            if len(cleaned) < 20:
                continue
            key = cleaned.lower()
            if key in seen:
                continue
            seen.add(key)
            snippets.append(cleaned)
            if len(snippets) >= max_snippets:
                break

        merged = "\n".join(f"- {s}" for s in snippets)
        if len(merged) > max_chars:
            merged = merged[:max_chars].rsplit(" ", 1)[0].strip()
        return merged

    @observe()
    def _run_noncritical_deepseek(self, scenario: str, rag_context: str) -> dict[str, Any]:
        default = {
            "guidance": (
                "สถานการณ์นี้เป็นเหตุฉุกเฉิน\n"
                "1. ตั้งสติและประเมินความปลอดภัยของพื้นที่\n"
                "2. โทร 1669 หากอาการแย่ลงหรือไม่มั่นใจ\n"
                "3. ปฐมพยาบาลตามอาการอย่างปลอดภัย\n"
                "4. เฝ้าระวังอาการและไปพบแพทย์โดยเร็ว"
            ),
            "facility_type": "clinic",
        }
        if self.deepseek_client is None:
            return dict(default)

        snippets = self._clean_rag_snippets(rag_context)
        system_prompt = (
            "You are a Thai emergency first-aid assistant. "
            "Use retrieved medical snippets as the highest-priority source. "
            'Return strict JSON only: {"guidance":"...","facility_type":'
            '"hospital|clinic|none"}. '
            "Guidance must be concise, numbered Thai steps, readable by layperson."
        )
        user_prompt = (
            f"Scenario: {scenario}\n\n"
            f"Retrieved contexts (cleaned):\n{snippets}\n\n"
            "Rules:\n"
            "- This is non-critical / moderate path.\n"
            "- Provide practical first-aid steps from retrieved contexts.\n"
            "- If symptoms escalate, explicitly instruct to call 1669.\n"
            "- Prefer facility_type='clinic' unless clearly severe.\n"
            "- Output JSON only."
        )
        try:
            resp = self.deepseek_client.chat.completions.create(
                model=self.deepseek_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,
                max_tokens=900,
            )
            content = ""
            if getattr(resp, "choices", None):
                content = _normalize_text(resp.choices[0].message.content)
            return _parse_json_fallback(content, default)
        except Exception as exc:
            record_exception(exc)
            return dict(default)

    @observe()
    def run(self, scenario: str, severity: str, rag_context: str) -> dict[str, Any]:
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
        # Moderate/non-critical: prefer DeepSeek when configured; otherwise Gemini
        # (same as critical).
        # Without this, missing DEEPSEEK_KEY caused only the static Thai default (generic 4 lines).
        if severity != "critical" and self.deepseek_client is not None:
            out = self._run_noncritical_deepseek(
                scenario=scenario,
                rag_context=rag_context,
            )
        else:
            out = self.llm.generate_json(
                model_name=model_name,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                default=default,
                temperature=0.15,
            )
        out["guidance"] = _normalize_text(out.get("guidance")) or default["guidance"]
        facility = _normalize_text(out.get("facility_type", default["facility_type"])).lower()
        out["facility_type"] = (
            facility if facility in {"hospital", "clinic", "none"} else default["facility_type"]
        )
        return out


class ScriptAgent:
    """ScriptAgent: generate call script using user medical profile."""

    def __init__(self, llm: GeminiJSONAgent) -> None:
        self.llm = llm
        self.model_name = _normalize_text(os.getenv("SCRIPT_MODEL")) or "gemini-2.5-flash"

    @observe()
    def run(
        self,
        scenario: str,
        guidance: str,
        user_profile: dict[str, Any],
        location_context: str = "",
        latitude: float | None = None,
        longitude: float | None = None,
        caller_profile: dict[str, Any] | None = None,
    ) -> str:
        default = {
            "call_script": (
                "สวัสดีค่ะ/ครับ แจ้งเหตุฉุกเฉิน โทร 1669\n"
                "1) ขณะนี้เกิดเหตุ: ...\n"
                "2) สถานที่เกิดเหตุชัดเจน: ... (จุดสังเกตใกล้เคียง: ...)\n"
                "3) ผู้ป่วยเพศ... อายุประมาณ... จำนวน... อาการหลัก...\n"
                "4) ระดับความรู้สึกตัว: รู้สึกตัว/ซึม/ไม่รู้สึกตัว\n"
                "5) ความเสี่ยงที่อาจเกิดซ้ำ: เช่น ไฟไหม้/ไฟฟ้ารั่ว/รถวิ่งผ่าน\n"
                "6) ชื่อผู้แจ้ง... เบอร์ติดต่อกลับ...\n"
                "7) ได้ช่วยเหลือเบื้องต้นแล้ว: ...\n"
                "8) ขอทีมกู้ชีพมารับเพื่อนำส่งโรงพยาบาลโดยด่วน"
            )
        }
        caller_note = ""
        if caller_profile:
            caller_note = (
                "The person currently using the app (reporter/caller) "
                "is NOT necessarily the patient. "
                "Use PATIENT profile for age/gender/medical details of the person needing help. "
                "Use CALLER profile only for reporter name/contact if different.\n"
            )

        system_prompt = (
            "You are ScriptAgent for emergency operator call assistance in Thai. "
            f"{caller_note}"
            "Generate concise speaking script following this exact call protocol in order:\n"
            "1) ตั้งสติ และโทรแจ้ง 1669\n"
            "2) ให้ข้อมูลว่าเกิดเหตุอะไร\n"
            "3) บอกสถานที่เกิดเหตุให้ชัดเจน\n"
            "4) บอกเพศ อายุ อาการ จำนวน\n"
            "5) บอกระดับความรู้สึกตัว\n"
            "6) บอกความเสี่ยงที่อาจเกิดซ้ำ\n"
            "7) บอกชื่อผู้แจ้ง + เบอร์โทรศัพท์\n"
            "8) ช่วยเหลือเบื้องต้น\n"
            "9) รอทีมกู้ชีพมารับเพื่อนำส่งโรงพยาบาล\n"
            "If location context is provided, convert it to human place description "
            "(address + landmarks). "
            "Do NOT tell operator raw latitude/longitude values. "
            "Output JSON only with key: call_script."
        )
        caller_json = ""
        if caller_profile:
            caller_json = (
                f"Caller/reporter profile (person using app): "
                f"{json.dumps(caller_profile, ensure_ascii=False)}\n\n"
            )
        user_prompt = (
            f"Scenario: {scenario}\n"
            f"Guidance: {guidance}\n"
            f"{caller_json}"
            f"PATIENT medical profile (person the emergency is about): "
            f"{json.dumps(user_profile, ensure_ascii=False)}\n\n"
            f"Latitude: {latitude}\n"
            f"Longitude: {longitude}\n"
            f"Location context from maps:\n{location_context}\n\n"
            "Build a Thai phone script the user can read to emergency operator.\n"
            "Requirements:\n"
            "- Follow protocol steps 1-9 in order.\n"
            "- Include a direct sentence about location using address/place names "
            "from map context.\n"
            "- If location context exists, mention at least 1-2 nearby landmarks/place names.\n"
            "- Never read out raw latitude/longitude numbers to operator.\n"
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
