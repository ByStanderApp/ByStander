import json
import os
import queue
import re
import threading
import time
from typing import Any

from dotenv import load_dotenv

try:
    from openai import OpenAI

    OPENAI_AVAILABLE = True
except Exception:  # pragma: no cover
    OpenAI = None
    OPENAI_AVAILABLE = False

try:
    from opentelemetry import trace as otel_trace
except Exception:  # pragma: no cover
    otel_trace = None

if __package__:
    from .observability import observe, record_exception
else:  # pragma: no cover
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
        return dict(default)
    try:
        payload = json.loads(block)
        if isinstance(payload, dict):
            out = dict(default)
            out.update(payload)
            return out
        return dict(default)
    except Exception:
        return dict(default)


def _to_int_in_range(value: Any, min_value: int, max_value: int, default: int) -> int:
    try:
        n = int(value)
    except Exception:
        return default
    if n < min_value:
        return min_value
    if n > max_value:
        return max_value
    return n


class AsyncJudgeService:
    """
    Fire-and-forget LLM judge.
    Runs in a background worker so app responses are not delayed.
    """

    def __init__(self) -> None:
        self.api_key = _normalize_text(os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_KEY"))
        self.model = _normalize_text(os.getenv("JUDGE_MODEL")) or "gpt-5.4-mini"
        self.enabled = bool(self.api_key and OPENAI_AVAILABLE)
        self.client = OpenAI(api_key=self.api_key) if self.enabled and OpenAI else None
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=256)
        self._worker: threading.Thread | None = None
        if self.enabled:
            self._worker = threading.Thread(target=self._worker_loop, daemon=True)
            self._worker.start()

    def submit(self, task: dict[str, Any]) -> bool:
        """
        Non-blocking submit. Returns False if queue is full or judge is disabled.
        """

        if not self.enabled:
            return False
        try:
            self._queue.put_nowait(task)
            return True
        except queue.Full:
            return False

    def _worker_loop(self) -> None:
        while True:
            task = self._queue.get()
            try:
                self._process_task(task)
            except Exception as exc:
                record_exception(exc)
            finally:
                self._queue.task_done()

    @observe()
    def _process_task(self, task: dict[str, Any]) -> None:
        started = time.perf_counter()

        guidance_judge = self._judge_guidance(
            scenario=_normalize_text(task.get("scenario")),
            guidance=_normalize_text(task.get("guidance")),
            rag_context=_normalize_text(task.get("rag_context")),
            severity=_normalize_text(task.get("severity")),
        )
        facility_judge = self._judge_facility(
            scenario=_normalize_text(task.get("scenario")),
            severity=_normalize_text(task.get("severity")),
            facilities=task.get("facilities") or [],
        )
        script_judge = self._judge_script(
            scenario=_normalize_text(task.get("scenario")),
            script=_normalize_text(task.get("call_script")),
        )

        elapsed_ms = int((time.perf_counter() - started) * 1000)

        if otel_trace is not None:
            try:
                span = otel_trace.get_current_span()
                if span is not None and hasattr(span, "set_attribute"):
                    span.set_attribute("judge.model", self.model)
                    span.set_attribute("judge.elapsed_ms", elapsed_ms)
                    span.set_attribute(
                        "judge.guidance.compliance",
                        _to_int_in_range(guidance_judge.get("compliance_score"), 1, 5, 1),
                    )
                    span.set_attribute(
                        "judge.guidance.correctness",
                        _to_int_in_range(guidance_judge.get("correctness_score"), 1, 5, 1),
                    )
                    span.set_attribute(
                        "judge.guidance.readability",
                        _to_int_in_range(guidance_judge.get("readability_score"), 1, 5, 1),
                    )
                    span.set_attribute(
                        "judge.facility.score",
                        _to_int_in_range(facility_judge.get("facility_score"), 1, 3, 1),
                    )
                    span.set_attribute(
                        "judge.script.score",
                        _to_int_in_range(script_judge.get("script_score"), 1, 3, 1),
                    )
            except Exception as exc:
                record_exception(exc)

    @observe()
    def _judge_guidance(
        self,
        scenario: str,
        guidance: str,
        rag_context: str,
        severity: str,
    ) -> dict[str, Any]:
        default = {
            "compliance_score": 1,
            "correctness_score": 1,
            "readability_score": 1,
            "chain_of_thought": "judge_unavailable",
        }
        system_prompt = (
            "You are a strict medical QA judge for Thai emergency guidance.\n"
            "Score each category from 1 (bad) to 5 (excellent):\n"
            "1) compliance_score: compliance with retrieved Vertex RAG protocol context\n"
            "2) correctness_score: first-aid correctness/safety\n"
            "3) readability_score: clarity for panicked layperson\n"
            "Return JSON only."
        )
        user_prompt = (
            f"Scenario: {scenario}\n"
            f"Severity: {severity}\n"
            f"Retrieved protocol context:\n{rag_context}\n\n"
            f"Guidance to evaluate:\n{guidance}\n\n"
            "Return strict JSON:\n"
            "{"
            '"compliance_score":1-5,'
            '"correctness_score":1-5,'
            '"readability_score":1-5,'
            '"chain_of_thought":"detailed reasoning"'
            "}"
        )
        out = self._judge_json(
            system_prompt=system_prompt, user_prompt=user_prompt, default=default
        )
        out["compliance_score"] = _to_int_in_range(out.get("compliance_score"), 1, 5, 1)
        out["correctness_score"] = _to_int_in_range(out.get("correctness_score"), 1, 5, 1)
        out["readability_score"] = _to_int_in_range(out.get("readability_score"), 1, 5, 1)
        out["chain_of_thought"] = (
            _normalize_text(out.get("chain_of_thought")) or default["chain_of_thought"]
        )
        return out

    @observe()
    def _judge_facility(
        self,
        scenario: str,
        severity: str,
        facilities: list[dict[str, Any]],
    ) -> dict[str, Any]:
        default = {
            "facility_score": 1,
            "chain_of_thought": "judge_unavailable",
        }
        system_prompt = (
            "You are a strict emergency dispatch QA judge.\n"
            "Evaluate whether selected facilities are correct and appropriate for the scenario.\n"
            "Score from 1 to 3 only (1 bad, 3 excellent). Return JSON only."
        )
        user_prompt = (
            f"Scenario: {scenario}\n"
            f"Severity: {severity}\n"
            f"Selected facilities JSON:\n{json.dumps(facilities, ensure_ascii=False)}\n\n"
            "Return strict JSON: "
            '{"facility_score":1-3,"chain_of_thought":"detailed reasoning"}'
        )
        out = self._judge_json(
            system_prompt=system_prompt, user_prompt=user_prompt, default=default
        )
        out["facility_score"] = _to_int_in_range(out.get("facility_score"), 1, 3, 1)
        out["chain_of_thought"] = (
            _normalize_text(out.get("chain_of_thought")) or default["chain_of_thought"]
        )
        return out

    @observe()
    def _judge_script(self, scenario: str, script: str) -> dict[str, Any]:
        default = {
            "script_score": 1,
            "chain_of_thought": "judge_unavailable",
        }
        system_prompt = (
            "You are a strict QA judge for emergency operator call scripts.\n"
            "Evaluate protocol compliance with this checklist:\n"
            "1) ตั้งสติ และโทรแจ้ง 1669\n"
            "2) ให้ข้อมูลว่าเกิดเหตุอะไร\n"
            "3) บอกสถานที่เกิดเหตุให้ชัดเจน\n"
            "4) บอกเพศ อายุ อาการ จำนวน\n"
            "5) บอกระดับความรู้สึกตัว\n"
            "6) บอกความเสี่ยงที่อาจเกิดซ้ำ\n"
            "7) บอกชื่อผู้แจ้ง + เบอร์โทรศัพท์\n"
            "8) ช่วยเหลือเบื้องต้น\n"
            "9) รอทีมกู้ชีพมารับเพื่อนำส่งโรงพยาบาล\n"
            "If location context is available in the script, it should be converted "
            "into a human place description rather than raw coordinates.\n"
            "Score from 1 to 3 only (1 bad, 3 excellent). Return JSON only."
        )
        user_prompt = (
            f"Scenario: {scenario}\n"
            f"Script:\n{script}\n\n"
            "Return strict JSON: "
            '{"script_score":1-3,"chain_of_thought":"detailed reasoning"}'
        )
        out = self._judge_json(
            system_prompt=system_prompt, user_prompt=user_prompt, default=default
        )
        out["script_score"] = _to_int_in_range(out.get("script_score"), 1, 3, 1)
        out["chain_of_thought"] = (
            _normalize_text(out.get("chain_of_thought")) or default["chain_of_thought"]
        )
        return out

    @observe()
    def _judge_json(
        self,
        system_prompt: str,
        user_prompt: str,
        default: dict[str, Any],
    ) -> dict[str, Any]:
        if not self.enabled or self.client is None:
            return dict(default)

        # Preferred path: Responses API (supports reasoning controls).
        try:
            response = self.client.responses.create(
                model=self.model,
                reasoning={"effort": "high"},
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            text = _normalize_text(getattr(response, "output_text", ""))
            if not text:
                text = _normalize_text(str(response))
            return _parse_json_fallback(text, default)
        except Exception as exc:
            record_exception(exc)

        # Compatibility path: Chat Completions.
        try:
            chat = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
            )
            text = ""
            if getattr(chat, "choices", None):
                msg = chat.choices[0].message
                text = _normalize_text(getattr(msg, "content", ""))
            if not text:
                text = _normalize_text(str(chat))
            return _parse_json_fallback(text, default)
        except Exception as exc:
            record_exception(exc)
            return dict(default)
