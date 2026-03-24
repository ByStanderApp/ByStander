import csv
import json
import math
import os
import re
import sys
import types
from typing import Any

from dotenv import load_dotenv

try:
    import requests
except Exception:  # pragma: no cover
    requests = types.SimpleNamespace()  # type: ignore[assignment]

    class _RequestException(Exception):
        pass

    def _missing_requests(*args, **kwargs):
        raise _RequestException("requests is unavailable")

    requests.RequestException = _RequestException  # type: ignore[attr-defined]
    requests.get = _missing_requests  # type: ignore[attr-defined]

if __package__:
    from .judge_service import AsyncJudgeService
    from .llm_agent import GeminiJSONAgent, GuidanceAgent, ScriptAgent, TriageAgent
    from .observability import observe, record_exception
else:  # pragma: no cover
    current_dir = os.path.dirname(os.path.abspath(__file__))
    if current_dir not in sys.path:
        sys.path.insert(0, current_dir)
    from judge_service import AsyncJudgeService
    from llm_agent import GeminiJSONAgent, GuidanceAgent, ScriptAgent, TriageAgent
    from observability import observe, record_exception

try:
    from google.adk.agents import LlmAgent  # type: ignore # noqa: F401

    ADK_AVAILABLE = True
except Exception:
    ADK_AVAILABLE = False

try:
    import vertexai
    from vertexai import rag

    VERTEX_RAG_AVAILABLE = True
except Exception:
    vertexai = None
    rag = None
    VERTEX_RAG_AVAILABLE = False


ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
load_dotenv(dotenv_path=ENV_PATH, override=True)


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


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


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c


def _split_csv_env(value: str) -> list[str]:
    raw = _normalize_text(value)
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


def _dedupe_nonempty(values: list[str]) -> list[str]:
    out: list[str] = []
    seen = set()
    for value in values:
        v = _normalize_text(value)
        if not v or v in seen:
            continue
        seen.add(v)
        out.append(v)
    return out


class ProtocolRetriever:
    """
    RAG retriever for protocol context.
    - Primary: Vertex AI RAG Engine corpus retrieval (from intro_rag_engine.ipynb pattern).
    - Current fallback: local keyword retrieval from instructions_raw_final.csv.
    """

    def __init__(self, csv_path: str | None = None) -> None:
        base_dir = os.path.dirname(os.path.dirname(__file__))
        self.csv_path = csv_path or os.path.join(
            base_dir, "finetuning", "instructions_raw_final.csv"
        )
        self.rows = self._load_rows()
        self.vertex_project = _normalize_text(os.getenv("GOOGLE_CLOUD_PROJECT"))
        self.vertex_project_number = _normalize_text(os.getenv("VERTEX_PROJECT_NUMBER"))
        self.vertex_location = _normalize_text(os.getenv("VERTEX_LOCATION") or "global")
        self.rag_location = _normalize_text(
            os.getenv("VERTEX_RAG_LOCATION") or "us-east1"
        )
        self.rag_corpus_display_name = _normalize_text(
            os.getenv("VERTEX_RAG_CORPUS_NAME") or "ByStander Rag Corpus"
        )
        self.rag_corpus_resource_override = _normalize_text(os.getenv("VERTEX_RAG_CORPUS_RESOURCE"))
        rag_top_k_raw = _normalize_text(os.getenv("VERTEX_RAG_TOP_K") or "8")
        try:
            self.rag_similarity_top_k_default = int(rag_top_k_raw)
        except Exception:
            self.rag_similarity_top_k_default = 8
        rag_threshold_raw = _normalize_text(
            os.getenv("VERTEX_RAG_VECTOR_DISTANCE_THRESHOLD")
        )
        self.rag_vector_distance_threshold = _safe_float(rag_threshold_raw)
        self.last_vertex_error: str = ""
        self.last_vertex_attempts: list[dict[str, str]] = []
        self.adc_project = self._detect_adc_project()
        self.vertex_project_candidates = self._build_project_candidates()
        self.rag_project = self._select_rag_project()
        self.rag_initialized = self._init_rag()
        self.rag_corpus_resource = self._resolve_rag_corpus_resource()

    def _load_rows(self) -> list[dict[str, str]]:
        if not os.path.exists(self.csv_path):
            return []
        out: list[dict[str, str]] = []
        with open(self.csv_path, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                out.append(
                    {
                        "case_name_th": _normalize_text(row.get("Case Name (TH)", "")),
                        "case_name_en": _normalize_text(row.get("Case Name (EN)", "")),
                        "keywords": _normalize_text(row.get("Keywords", "")),
                        "instructions": _normalize_text(row.get("Instructions", "")),
                        "severity": _normalize_text(row.get("severity", "")).lower(),
                        "facility_type": _normalize_text(
                            row.get("facility_type", "")
                        ).lower(),
                    }
                )
        return out

    def _score_row(self, query: str, row: dict[str, str], severity: str) -> int:
        q = query.lower()
        score = 0
        if row["case_name_th"] and row["case_name_th"].lower() in q:
            score += 5
        if row["case_name_en"] and row["case_name_en"].lower() in q:
            score += 3
        for kw in [x.strip() for x in row["keywords"].split(",") if x.strip()]:
            if kw.lower() in q:
                score += 2
        if severity and row["severity"] == severity:
            score += 1
        return score

    def _detect_adc_project(self) -> str:
        try:
            import google.auth

            _, project = google.auth.default()
            return _normalize_text(project)
        except Exception:
            return ""

    def _build_project_candidates(self) -> list[str]:
        return _dedupe_nonempty(
            [
                self.vertex_project,
                self.vertex_project_number,
                self.adc_project,
            ]
        )

    def _select_rag_project(self) -> str:
        if self.vertex_project_candidates:
            return self.vertex_project_candidates[0]
        return ""

    def _init_rag(self) -> bool:
        if not VERTEX_RAG_AVAILABLE:
            self.last_vertex_error = "vertexai SDK with RAG is not available"
            return False
        if not self.rag_project:
            self.last_vertex_error = "missing GOOGLE_CLOUD_PROJECT (and ADC project)"
            return False
        try:
            vertexai.init(project=self.rag_project, location=self.rag_location)
            return True
        except Exception as exc:
            self.last_vertex_error = f"vertexai.init failed: {exc}"
            return False

    def _resolve_rag_corpus_resource(self) -> str:
        if self.rag_corpus_resource_override:
            return self.rag_corpus_resource_override
        if not self.rag_initialized:
            return ""
        try:
            corpora = list(rag.list_corpora())
        except Exception as exc:
            self.last_vertex_error = f"rag.list_corpora failed: {exc}"
            return ""

        if not corpora:
            self.last_vertex_error = "no RAG corpora found in project/location"
            return ""

        target = self.rag_corpus_display_name.lower()
        for corpus in corpora:
            display = _normalize_text(getattr(corpus, "display_name", ""))
            if display.lower() == target:
                return _normalize_text(getattr(corpus, "name", ""))

        for corpus in corpora:
            display = _normalize_text(getattr(corpus, "display_name", ""))
            if target in display.lower():
                return _normalize_text(getattr(corpus, "name", ""))

        self.last_vertex_error = f"RAG corpus '{self.rag_corpus_display_name}'"
        "not found in {self.rag_project}/{self.rag_location}"
        return ""

    def _search_vertex(self, query: str, severity: str, top_k: int) -> list[dict[str, str]]:
        if not self.rag_initialized:
            if not self.last_vertex_error:
                self.last_vertex_error = "RAG engine is not initialized"
            self.last_vertex_attempts = []
            return []
        if not self.rag_corpus_resource:
            self.rag_corpus_resource = self._resolve_rag_corpus_resource()
        if not self.rag_corpus_resource:
            self.last_vertex_attempts = [
                {
                    "mode": "rag_retrieval_query",
                    "project": self.rag_project,
                    "location": self.rag_location,
                    "corpus": self.rag_corpus_display_name,
                    "status": "error",
                    "error": self.last_vertex_error or "missing RAG corpus resource",
                }
            ]
            return []

        try:
            self.last_vertex_error = ""
            self.last_vertex_attempts = []
            scoped_query = query.strip()
            if severity:
                scoped_query = f"{query}\nseverity:{severity}"

            query_top_k = (

                top_k
                if isinstance(top_k, int) and top_k > 0
                else self.rag_similarity_top_k_default
            )
            final_top_k = max(1, min(query_top_k, 20))
            retrieval_config_kwargs: dict[str, Any] = {"top_k": final_top_k}
            if self.rag_vector_distance_threshold is not None:
                retrieval_config_kwargs["filter"] = rag.Filter(
                    vector_distance_threshold=self.rag_vector_distance_threshold
                )

            response = rag.retrieval_query(
                rag_resources=[rag.RagResource(rag_corpus=self.rag_corpus_resource)],
                rag_retrieval_config=rag.RagRetrievalConfig(**retrieval_config_kwargs),
                text=scoped_query,
            )

            docs: list[dict[str, str]] = []
            contexts_container = getattr(response, "contexts", None)
            contexts = getattr(contexts_container, "contexts", None) or []
            for ctx in contexts:
                body = _normalize_text(
                    getattr(ctx, "text", "")
                    or getattr(ctx, "chunk_text", "")
                    or getattr(ctx, "content", "")
                )
                title = _normalize_text(
                    getattr(ctx, "title", "")
                    or getattr(ctx, "source_display_name", "")
                    or "Vertex RAG Protocol"
                )
                source_uri = _normalize_text(
                    getattr(ctx, "source_uri", "") or getattr(ctx, "uri", "")
                )
                if not body:
                    continue
                docs.append(
                    {
                        "title": title,
                        "body": body,
                        "meta": f"source={source_uri}" if source_uri else "",
                    }
                )

            self.last_vertex_attempts.append(
                {
                    "mode": "rag_retrieval_query",
                    "project": self.rag_project,
                    "location": self.rag_location,
                    "corpus": self.rag_corpus_resource,
                    "status": "ok" if docs else "no_results",
                    "error": "",
                }
            )
            if not docs:
                self.last_vertex_error = "rag retrieval returned no contexts"
            return docs
        except Exception as exc:
            self.last_vertex_error = f"rag retrieval failed: {exc}"
            self.last_vertex_attempts = [
                {
                    "mode": "rag_retrieval_query",
                    "project": self.rag_project,
                    "location": self.rag_location,
                    "corpus": self.rag_corpus_resource or self.rag_corpus_display_name,
                    "status": "error",
                    "error": str(exc),
                }
            ]
            return []

    def _format_vertex_context(self, docs: list[dict[str, str]]) -> str:
        chunks: list[str] = []
        for i, d in enumerate(docs, start=1):
            title = _normalize_text(d.get("title"))
            body = _normalize_text(d.get("body"))
            meta = _normalize_text(d.get("meta"))
            chunks.append(
                f"[Vertex Protocol {i}] {title}\n{('- ' + meta) if meta else ''}\n{body}".strip()
            )
        return "\n\n".join(chunks).strip()

    def retrieve(self, query: str, severity: str, top_k: int = 3) -> str:
        result = self.retrieve_with_meta(query=query, severity=severity, top_k=top_k)
        return result["context"]

    @observe()
    def retrieve_with_meta(
        self, query: str, severity: str, top_k: int = 3
    ) -> Dict[str, Any]:
        # Primary: Vertex AI RAG Engine retrieval (if configured and available).
        vertex_docs = self._search_vertex(query=query, severity=severity, top_k=top_k)
        if vertex_docs:
            context = self._format_vertex_context(vertex_docs)
            if context:
                return {
                    "source": "vertex",
                    "context": context,
                    "count": len(vertex_docs),
                    "vertex_error": "",
                    "vertex_attempts": self.last_vertex_attempts,
                }

        # Fallback: local CSV retrieval.
        if not self.rows:
            return {
                "source": "none",
                "context": "ไม่มีบริบทจากฐานข้อมูลโปรโตคอล ให้ยึดหลักความปลอดภัยและโทร 1669 "
                "เมื่อสงสัยว่าเป็นเหตุฉุกเฉิน",
                "count": 0,
                "vertex_error": self.last_vertex_error,
                "vertex_attempts": self.last_vertex_attempts,
            }

        ranked = sorted(
            self.rows,
            key=lambda row: self._score_row(query, row, severity),
            reverse=True,
        )
        top = [r for r in ranked if self._score_row(query, r, severity) > 0][:top_k]
        if not top:
            top = ranked[: min(top_k, len(ranked))]

        chunks: list[str] = []
        for i, item in enumerate(top, start=1):
            chunks.append(
                f"[Protocol {i}] {item['case_name_th']}\n"
                f"- Keywords: {item['keywords']}\n"
                f"- Guidance: {item['instructions']}\n"
                f"- Severity: {item['severity']}\n"
                f"- Facility: {item['facility_type']}"
            )
        return {
            "source": "csv",
            "context": "\n\n".join(chunks),
            "count": len(top),
            "vertex_error": self.last_vertex_error,
            "vertex_attempts": self.last_vertex_attempts,
        }

    def debug_vertex_status(
        self, scenario: str, severity: str, top_k: int = 3
    ) -> Dict[str, Any]:
        query = _normalize_text(scenario)
        sev = _normalize_text(severity).lower() or "moderate"
        if sev not in {"critical", "moderate", "none"}:
            sev = "moderate"

        env_status = {
            "GOOGLE_CLOUD_PROJECT": bool(self.vertex_project),
            "VERTEX_PROJECT_NUMBER": bool(self.vertex_project_number),
            "VERTEX_LOCATION": bool(self.vertex_location),
            "VERTEX_RAG_LOCATION": bool(self.rag_location),
            "VERTEX_RAG_CORPUS_NAME": bool(self.rag_corpus_display_name),
            "VERTEX_RAG_CORPUS_RESOURCE": bool(self.rag_corpus_resource_override),
            "GOOGLE_APPLICATION_CREDENTIALS": bool(
                _normalize_text(os.getenv("GOOGLE_APPLICATION_CREDENTIALS"))
            ),
        }

        diagnostics: dict[str, Any] = {
            "vertex_rag_library_available": VERTEX_RAG_AVAILABLE,
            "rag_initialized": self.rag_initialized,
            "configured_project": self.vertex_project,
            "configured_project_number": self.vertex_project_number,
            "adc_project": self.adc_project,
            "project_candidates": self.vertex_project_candidates,
            "rag_project": self.rag_project,
            "rag_location": self.rag_location,
            "rag_corpus_display_name": self.rag_corpus_display_name,
            "rag_corpus_resource": self.rag_corpus_resource,
            "env_status": env_status,
            "last_vertex_error": self.last_vertex_error,
        }

        if not query:
            diagnostics.update(
                {
                    "source": "none",
                    "count": 0,
                    "context_preview": "",
                    "error": "scenario is required",
                }
            )
            return diagnostics

        result = self.retrieve_with_meta(query=query, severity=sev, top_k=top_k)
        diagnostics.update(
            {
                "source": result.get("source", "none"),
                "count": int(result.get("count", 0) or 0),
                "vertex_error": result.get("vertex_error", self.last_vertex_error),
                "vertex_attempts": result.get(
                    "vertex_attempts", self.last_vertex_attempts
                ),
                "context_preview": _normalize_text(result.get("context", ""))[:1200],
            }
        )
        return diagnostics

    def debug_vertex_resources(self) -> dict[str, Any]:
        details: dict[str, Any] = {
            "vertex_rag_library_available": VERTEX_RAG_AVAILABLE,
            "project_candidates": self.vertex_project_candidates,
            "rag_project": self.rag_project,
            "rag_location": self.rag_location,
            "rag_corpus_display_name": self.rag_corpus_display_name,
            "rag_corpus_resource": self.rag_corpus_resource,
            "corpora": [],
        }
        if not VERTEX_RAG_AVAILABLE:
            details["error"] = "vertexai SDK with RAG is not available"
            return details
        if not self.rag_initialized:
            details["error"] = self.last_vertex_error or "RAG is not initialized"
            return details

        try:
            for corpus in rag.list_corpora():
                details["corpora"].append(
                    {
                        "name": _normalize_text(getattr(corpus, "name", "")),
                        "display_name": _normalize_text(
                            getattr(corpus, "display_name", "")
                        ),
                    }
                )
        except Exception as exc:
            details["error"] = f"rag.list_corpora failed: {exc}"
        return details

    def catalog(self) -> list[dict[str, str]]:
        return self.rows


class MapAgent:
    def __init__(self) -> None:
        self.validator_llm = GeminiJSONAgent()
        self.validator_model = (
            _normalize_text(os.getenv("MAP_VALIDATOR_MODEL")) or "gemini-2.0-flash-lite"
        )

    def _get_google_api_key(self) -> str | None:
        return _normalize_text(os.getenv("GOOGLE_API_KEY")) or None

    @staticmethod
    def _is_veterinary_place(place: dict[str, Any]) -> bool:
        name = _normalize_text(place.get("name")).lower()
        types_list = [str(t).lower() for t in place.get("types", [])]
        vet_tokens = {"veterinary_care", "veterinary", "vet", "animal hospital", "สัตว"}
        if any(t in vet_tokens for t in types_list):
            return True
        return any(tok in name for tok in vet_tokens)

    @staticmethod
    def _is_human_medical_signal(place: dict[str, Any]) -> bool:
        name = _normalize_text(place.get("name")).lower()
        types_list = [str(t).lower() for t in place.get("types", [])]
        name_tokens = {
            "hospital",
            "clinic",
            "medical",
            "emergency",
            "urgent care",
            "โรงพยาบาล",
            "คลินิก",
            "สถานพยาบาล",
            "ศูนย์การแพทย์",
            "การแพทย์",
        }
        type_signals = {"hospital", "doctor", "health"}
        return any(t in types_list for t in type_signals) or any(
            tok in name for tok in name_tokens
        )

    @staticmethod
    def _is_non_treatment_business(place: dict[str, Any]) -> bool:
        name = _normalize_text(place.get("name")).lower()
        types_list = [str(t).lower() for t in place.get("types", [])]
        bad_types = {
            "veterinary_care",
            "pet_store",
            "pharmacy",
            "drugstore",
            "insurance_agency",
            "car_repair",
        }
        if any(t in bad_types for t in types_list):
            return True
        bad_name_tokens = {
            "vet",
            "veterinary",
            "สัตว",
            "medical supply",
            "medical device",
            "insurance",
            "co., ltd",
            "corporation",
            "head office",
            "สำนักงานใหญ่",
            "บริษัท",
        }
        return any(tok in name for tok in bad_name_tokens)

    def _build_query_plan(
        self, facility_type: str, severity: str
    ) -> List[Dict[str, Any]]:
        fac = facility_type if facility_type in {"hospital", "clinic"} else "hospital"
        if fac == "hospital" or severity == "critical":
            return [
                {
                    "radius": 7000,
                    "type": "hospital",
                    "keyword": "hospital โรงพยาบาล emergency",
                }
            ]
        return [
            {
                "radius": 5000,
                "type": "doctor",
                "keyword": "clinic คลินิก primary care",
            },
            {
                "radius": 5000,
                "type": "hospital",
                "keyword": "clinic คลินิก outpatient",
            },
        ]

    def _nearby_search(
        self,
        latitude: float,
        longitude: float,
        radius: int,
        place_type: str,
        keyword: str,
    ) -> dict[str, Any]:
        api_key = self._get_google_api_key()
        if not api_key:
            return {"error": "Google API key not configured"}

        params = {
            "location": f"{latitude},{longitude}",
            "radius": radius,
            "type": place_type,
            "language": "th",
            "key": api_key,
        }
        if keyword:
            params["keyword"] = keyword

        try:
            response = requests.get(
                "https://maps.googleapis.com/maps/api/place/nearbysearch/json",
                params=params,
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            status = _normalize_text(data.get("status"))
            if status in {"OK", "ZERO_RESULTS"}:
                return {"results": data.get("results", [])}
            return {
                "error": (
                    f"Nearby Search failed: {status} {_normalize_text(data.get('error_message'))}"
                ).strip()
            }
        except requests.RequestException as exc:
            return {"error": f"Nearby Search request failed: {exc}"}

    def _get_place_details(self, place_id: str) -> dict[str, Any]:
        api_key = self._get_google_api_key()
        if not api_key:
            return {}
        params = {
            "place_id": place_id,
            "fields": "formatted_phone_number,website,opening_hours",
            "language": "th",
            "key": api_key,
        }
        try:
            response = requests.get(
                "https://maps.googleapis.com/maps/api/place/details/json",
                params=params,
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            if _normalize_text(data.get("status")) != "OK":
                return {}
            result = data.get("result", {}) or {}
            return {
                "phone_number": result.get("formatted_phone_number", ""),
                "website": result.get("website", ""),
                "opening_hours": result.get("opening_hours", {}),
            }
        except requests.RequestException:
            return {}

    def _reverse_geocode(self, latitude: float, longitude: float) -> str:
        api_key = self._get_google_api_key()
        if not api_key:
            return ""
        params = {
            "latlng": f"{latitude},{longitude}",
            "language": "th",
            "key": api_key,
        }
        try:
            response = requests.get(
                "https://maps.googleapis.com/maps/api/geocode/json",
                params=params,
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            if _normalize_text(data.get("status")) != "OK":
                return ""
            results = data.get("results", []) or []
            if not results:
                return ""
            return _normalize_text(results[0].get("formatted_address"))
        except requests.RequestException:
            return ""

    def _nearby_landmarks(self, latitude: float, longitude: float) -> list[str]:
        all_places: list[dict[str, Any]] = []
        queries = [
            {"radius": 800, "type": "point_of_interest", "keyword": ""},
            {"radius": 1200, "type": "transit_station", "keyword": ""},
        ]
        for query in queries:
            result = self._nearby_search(
                latitude=latitude,
                longitude=longitude,
                radius=int(query["radius"]),
                place_type=str(query["type"]),
                keyword=str(query["keyword"]),
            )
            if "error" in result:
                continue
            all_places.extend(result.get("results", []))

        seen = set()
        names: list[str] = []
        for place in all_places:
            name = _normalize_text(place.get("name"))
            if not name:
                continue
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            names.append(name)
            if len(names) >= 5:
                break
        return names

    def build_location_context(
        self,
        latitude: float | None,
        longitude: float | None,
        facilities: list[dict[str, Any]] | None = None,
    ) -> str:
        if latitude is None or longitude is None:
            return ""

        parts: list[str] = []
        address = self._reverse_geocode(latitude, longitude)
        if address:
            parts.append(f"ที่อยู่จากแผนที่: {address}")
        parts.append(f"พิกัดสำหรับระบบ (ไม่ต้องอ่านให้เจ้าหน้าที่): {latitude:.6f}, {longitude:.6f}")

        landmarks = self._nearby_landmarks(latitude, longitude)
        if landmarks:
            parts.append(f"จุดสังเกตใกล้เคียง: {', '.join(landmarks[:3])}")

        if facilities:
            nearby_refs: list[str] = []
            for facility in facilities[:2]:
                name = _normalize_text(facility.get("name"))
                dist = _safe_float(facility.get("distance_km"))
                if not name:
                    continue
                if dist is None:
                    nearby_refs.append(name)
                else:
                    nearby_refs.append(f"{name} (~{dist:.1f} กม.)")
            if nearby_refs:
                parts.append(f"สถานพยาบาลใกล้เคียง: {', '.join(nearby_refs)}")
        return "\n".join(parts)

    def _strict_filter(
        self, place: Dict[str, Any], requested_facility_type: str
    ) -> str:
        if self._is_veterinary_place(place):
            return "reject"
        if self._is_non_treatment_business(place):
            return "reject"

        types_list = {str(t).lower() for t in place.get("types", [])}
        if requested_facility_type == "hospital":
            if "hospital" in types_list and self._is_human_medical_signal(place):
                return "accept"
            if "doctor" in types_list and self._is_human_medical_signal(place):
                return "ambiguous"
            return "reject"

        if "doctor" in types_list and self._is_human_medical_signal(place):
            return "accept"
        if "hospital" in types_list and self._is_human_medical_signal(place):
            return "accept"
        if self._is_human_medical_signal(place):
            return "ambiguous"
        return "reject"

    def _parse_llm_validation(self, raw: Any) -> dict[str, dict[str, Any]]:
        if isinstance(raw, dict):
            payload = raw
        else:
            text = _normalize_text(raw)
            block = _extract_json_block(text)
            if not block:
                return {}
            try:
                payload = json.loads(block)
            except Exception:
                return {}
        items = payload.get("items", [])
        if not isinstance(items, list):
            return {}
        parsed: dict[str, dict[str, Any]] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            pid = _normalize_text(item.get("place_id"))
            if not pid:
                continue
            parsed[pid] = {
                "is_valid": bool(item.get("is_valid", False)),
                "facility_type": _normalize_text(item.get("facility_type")).lower(),
                "reason": _normalize_text(item.get("reason")),
            }
        return parsed

    def _llm_validate_candidates(
        self,
        scenario: str,
        requested_facility_type: str,
        severity: str,
        candidates: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        if not candidates:
            return {}

        def rule_fallback() -> dict[str, dict[str, Any]]:
            out: dict[str, dict[str, Any]] = {}
            for place in candidates:
                pid = _normalize_text(place.get("place_id"))
                if not pid:
                    continue
                out[pid] = {
                    "is_valid": (
                        self._is_human_medical_signal(place)
                        and not self._is_non_treatment_business(place)
                        and not self._is_veterinary_place(place)
                    ),
                    "facility_type": requested_facility_type,
                    "reason": "rule_fallback",
                }
            return out

        serialized_places: list[dict[str, Any]] = []
        for place in candidates:
            serialized_places.append(
                {
                    "place_id": _normalize_text(place.get("place_id")),
                    "name": _normalize_text(place.get("name")),
                    "address": _normalize_text(place.get("vicinity")),
                    "types": [str(t).lower() for t in place.get("types", [])],
                    "rating": place.get("rating", 0),
                }
            )

        default = {
            "items": [
                {
                    "place_id": p.get("place_id", ""),
                    "is_valid": False,
                    "facility_type": "other",
                    "reason": "default_reject",
                }
                for p in serialized_places
            ]
        }
        system_prompt = (
            "You are MapAgent validation model for an emergency app. "
            "Classify ONLY true human treatment facilities. "
            "Reject veterinary clinics/hospitals, pharmacies, medical companies, surgical centers and offices. "
            "Return strict JSON only."
        )
        user_prompt = (
            f"Scenario: {scenario}\n"
            f"Requested facility type: {requested_facility_type}\n"
            f"Severity: {severity}\n\n"
            "For requested type hospital, only hospitals are valid.\n"
            "For requested type clinic, hospitals and doctor/clinic facilities are valid.\n"
            "Return JSON schema exactly: "
            '{"items":[{"place_id":"...","is_valid":true|false,'
            '"facility_type":"hospital|clinic|other","reason":"short"}]}\n\n'
            f"Candidates:\n{json.dumps(serialized_places, ensure_ascii=False)}"
        )

        out = self.validator_llm.generate_json(
            model_name=self.validator_model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            default=default,
            temperature=0.0,
        )
        parsed = self._parse_llm_validation(out)
        if parsed:
            return parsed
        return rule_fallback()

    @observe()
    def search_nearby_facilities(
        self,
        latitude: float,
        longitude: float,
        facility_type: str,
        severity: str,
        scenario: str = "",
    ) -> Dict[str, Any]:
        requested = (
            facility_type if facility_type in {"hospital", "clinic"} else "hospital"
        )
        map_severity = (
            severity if severity in {"critical", "moderate", "mild", "none"} else "none"
        )

        all_candidates: list[dict[str, Any]] = []
        errors: list[str] = []
        for q in self._build_query_plan(requested, map_severity):
            result = self._nearby_search(
                latitude=latitude,
                longitude=longitude,
                radius=int(q["radius"]),
                place_type=str(q["type"]),
                keyword=str(q["keyword"]),
            )
            if "error" in result:
                errors.append(_normalize_text(result["error"]))
                continue
            all_candidates.extend(result.get("results", []))

        if not all_candidates:
            if errors:
                return {"error": errors[0]}
            return {"facilities": [], "total": 0}

        dedup: dict[str, dict[str, Any]] = {}
        for place in all_candidates:
            pid = _normalize_text(place.get("place_id"))
            if not pid:
                continue
            if pid not in dedup:
                dedup[pid] = place

        strict_accept: list[dict[str, Any]] = []
        ambiguous: list[dict[str, Any]] = []
        for place in dedup.values():
            decision = self._strict_filter(place, requested_facility_type=requested)
            if decision == "accept":
                strict_accept.append(place)
            elif decision == "ambiguous":
                ambiguous.append(place)

        validated: list[dict[str, Any]] = []
        if ambiguous:
            llm_map = self._llm_validate_candidates(
                scenario=scenario,
                requested_facility_type=requested,
                severity=map_severity,
                candidates=ambiguous,
            )
            for place in ambiguous:
                pid = _normalize_text(place.get("place_id"))
                if llm_map.get(pid, {}).get("is_valid") is True:
                    validated.append(place)

        selected = strict_accept + validated
        if not selected:
            return {"facilities": [], "total": 0}

        facilities: list[dict[str, Any]] = []
        for place in selected:
            location = (place.get("geometry") or {}).get("location") or {}
            f_lat = _safe_float(location.get("lat"))
            f_lon = _safe_float(location.get("lng"))
            if f_lat is None or f_lon is None:
                continue
            details = self._get_place_details(_normalize_text(place.get("place_id")))
            facilities.append(
                {
                    "place_id": _normalize_text(place.get("place_id")),
                    "name": _normalize_text(place.get("name")),
                    "address": _normalize_text(place.get("vicinity")),
                    "phone_number": _normalize_text(details.get("phone_number")),
                    "website": _normalize_text(details.get("website")),
                    "rating": float(place.get("rating", 0) or 0),
                    "user_ratings_total": int(place.get("user_ratings_total", 0) or 0),
                    "open_now": (place.get("opening_hours") or {}).get(
                        "open_now", None
                    ),
                    "latitude": f_lat,
                    "longitude": f_lon,
                    "types": place.get("types", []),
                }
            )
        return {"facilities": facilities, "total": len(facilities)}

    def run(
        self,
        scenario: str,
        severity: str,
        facility_type: str,
        latitude: float | None,
        longitude: float | None,
    ) -> list[dict[str, Any]]:
        if latitude is None or longitude is None:
            return []

        map_severity = "critical" if severity == "critical" else "mild"
        fac_type = (
            facility_type if facility_type in {"hospital", "clinic"} else "hospital"
        )
        result = self.search_nearby_facilities(
            latitude=latitude,
            longitude=longitude,
            facility_type=fac_type,
            severity=map_severity,
            scenario=scenario,
        )
        if not isinstance(result, dict) or "error" in result:
            return []

        facilities = result.get("facilities", []) or []
        cleaned: list[dict[str, Any]] = []
        for f in facilities:
            f_lat = _safe_float(f.get("latitude"))
            f_lon = _safe_float(f.get("longitude"))
            if f_lat is None or f_lon is None:
                continue
            distance_km = _haversine_km(latitude, longitude, f_lat, f_lon)
            cleaned.append(
                {
                    "name": _normalize_text(f.get("name")),
                    "address": _normalize_text(f.get("address")),
                    "phone_number": _normalize_text(f.get("phone_number")),
                    "rating": float(f.get("rating", 0) or 0),
                    "distance_km": round(distance_km, 2),
                    "latitude": f_lat,
                    "longitude": f_lon,
                }
            )

        if severity == "critical":
            cleaned.sort(key=lambda x: x["distance_km"])
            reason = "critical: sorted by shortest distance"
        else:
            cleaned.sort(key=lambda x: (-x["rating"], x["distance_km"]))
            reason = "moderate: sorted by rating then distance"

        for item in cleaned:
            item["selection_reason"] = reason
        return cleaned[:5]


class FirebaseProfileService:
    def __init__(self) -> None:
        self.available = False
        self.firestore = None
        self._init()

    def _init(self) -> None:
        try:
            import firebase_admin
            from firebase_admin import credentials, firestore
        except Exception:
            return

        try:
            if not firebase_admin._apps:
                service_account_path = _normalize_text(
                    os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH")
                )
                if service_account_path and os.path.exists(service_account_path):
                    cred = credentials.Certificate(service_account_path)
                    firebase_admin.initialize_app(cred)
                else:
                    firebase_admin.initialize_app()
            self.firestore = firestore
            self.available = True
        except Exception:
            self.available = False

    def get_user_profile(self, user_id: str) -> dict[str, Any]:
        if not self.available or not user_id:
            return {}
        db = self.firestore.client()
        profile: dict[str, Any] = {}

        try:
            user_doc = db.collection("users").document(user_id).get()
            if user_doc.exists:
                data = user_doc.to_dict() or {}
                profile["firstName"] = data.get("firstName") or ""
                profile["lastName"] = data.get("lastName") or ""
                profile["gender"] = data.get("gender") or ""
                profile["birthdate"] = (
                    data.get("birthdate") or data.get("dateOfBirth") or ""
                )
                profile["phone"] = data.get("tel") or data.get("phone") or ""
        except Exception:
            pass

        try:
            med_doc = (
                db.collection("users")
                .document(user_id)
                .collection("medical_histories")
                .document("current")
                .get()
            )
            if med_doc.exists:
                med = med_doc.to_dict() or {}
                profile["bloodType"] = med.get("bloodType") or ""
                profile["medicalCondition"] = med.get("medicalCondition") or []
                profile["allergies"] = med.get("allergies") or []
                profile["immunizations"] = med.get("immunizations") or []
        except Exception:
            pass

        try:
            rel_docs = (
                db.collection("users").document(user_id).collection("relatives").limit(3).stream()
            )
            relatives = []
            for d in rel_docs:
                item = d.to_dict() or {}
                relatives.append(
                    {
                        "firstName": item.get("firstName", ""),
                        "lastName": item.get("lastName", ""),
                        "tel": item.get("tel", ""),
                        "relationship": item.get("relationship", ""),
                    }
                )
            profile["relatives"] = relatives
        except Exception:
            pass
        return profile


class ByStanderWorkflow:
    def __init__(self) -> None:
        llm = GeminiJSONAgent()
        self.triage_agent = TriageAgent(llm)
        self.guidance_agent = GuidanceAgent(llm)
        self.script_agent = ScriptAgent(llm)
        self.map_agent = MapAgent()
        self.retriever = ProtocolRetriever()
        self.profile_service = FirebaseProfileService()
        self.judge_service = AsyncJudgeService()

    @observe()
    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        scenario = _normalize_text(payload.get("scenario") or payload.get("sentence"))
        if not scenario:
            raise ValueError("scenario is required")

        try:
            triage = self.triage_agent.run(scenario)
        except Exception as exc:
            record_exception(exc)
            triage = {
                "is_emergency": True,
                "severity": "moderate",
                "facility_type": "clinic",
                "reason_th": "ระบบวิเคราะห์ฉุกเฉินขัดข้องชั่วคราว ใช้ค่าเริ่มต้นเพื่อความปลอดภัย",
            }
        is_emergency = bool(triage.get("is_emergency"))
        severity = _normalize_text(triage.get("severity", "none")).lower()
        if severity not in {"critical", "moderate", "none"}:
            severity = "none"

        if not is_emergency or severity == "none":
            return {
                "route": "general_info",
                "is_emergency": False,
                "adk_available": ADK_AVAILABLE,
                "severity": "none",
                "facility_type": "none",
                "guidance": "",
                "general_info": (
                    "สถานการณ์ที่คุณแจ้งเข้ามาไม่ถูกจัดเป็นเหตุฉุกเฉินเร่งด่วน\n"
                    "หากอาการแย่ลงอย่างรวดเร็ว เช่น หมดสติ หายใจลำบาก เจ็บหน้าอกรุนแรง "
                    "หรือมีเลือดออกมาก ให้โทร 1669 ทันที"
                ),
                "call_script": "",
                "facilities": [],
                "triage_reason": triage.get("reason_th", ""),
            }

        try:
            rag_result = self.retriever.retrieve_with_meta(
                query=scenario, severity=severity
            )
            rag_context = _normalize_text(rag_result.get("context"))
        except Exception as exc:
            record_exception(exc)
            rag_result = {"source": "none", "count": 0}
            rag_context = "ไม่มีบริบทจาก RAG ชั่วคราว ให้ยึดหลักความปลอดภัย ประเมินพื้นที่ และโทร 1669 เมื่อเป็นเหตุฉุกเฉิน"
        try:
            guidance_result = self.guidance_agent.run(
                scenario=scenario,
                severity=severity,
                rag_context=rag_context,
            )
        except Exception as exc:
            record_exception(exc)
            guidance_result = {
                "guidance": (
                    "สถานการณ์นี้เป็นเหตุฉุกเฉิน\n"
                    "1. ประเมินความปลอดภัยของพื้นที่\n"
                    "2. โทร 1669 ทันที\n"
                    "3. ปฐมพยาบาลตามอาการเท่าที่ปลอดภัย\n"
                    "4. เฝ้าระวังอาการจนกว่าทีมแพทย์มาถึง"
                ),
                "facility_type": "hospital" if severity == "critical" else "clinic",
            }
        guidance_text = _normalize_text(guidance_result.get("guidance"))
        facility_type = _normalize_text(guidance_result.get("facility_type")).lower()
        if facility_type not in {"hospital", "clinic", "none"}:
            facility_type = "hospital" if severity == "critical" else "clinic"

        latitude = _safe_float(payload.get("latitude"))
        longitude = _safe_float(payload.get("longitude"))
        facilities = self.map_agent.run(
            scenario=scenario,
            severity=severity,
            facility_type=facility_type,
            latitude=latitude,
            longitude=longitude,
        )

        legacy_user_id = _normalize_text(payload.get("user_id"))
        target_user_id = (
            _normalize_text(payload.get("target_user_id")) or legacy_user_id
        )
        caller_user_id = (
            _normalize_text(payload.get("caller_user_id")) or legacy_user_id
        )
        if not target_user_id:
            target_user_id = caller_user_id
        if not caller_user_id:
            caller_user_id = target_user_id

        patient_profile = (
            self.profile_service.get_user_profile(user_id=target_user_id)
            if target_user_id
            else {}
        )
        caller_profile: dict[str, Any] = {}
        if caller_user_id and caller_user_id != target_user_id:
            caller_profile = self.profile_service.get_user_profile(
                user_id=caller_user_id
            )

        location_context = self.map_agent.build_location_context(
            latitude=latitude,
            longitude=longitude,
            facilities=facilities,
        )
        try:
            call_script = self.script_agent.run(
                scenario=scenario,
                guidance=guidance_text,
                user_profile=patient_profile,
                caller_profile=caller_profile if caller_profile else None,
                location_context=location_context,
                latitude=latitude,
                longitude=longitude,
            )
        except Exception as exc:
            record_exception(exc)
            call_script = (
                "สวัสดีค่ะ/ครับ แจ้งเหตุฉุกเฉิน มีผู้ป่วยต้องการความช่วยเหลือด่วน\n"
                "จุดเกิดเหตุ: โปรดระบุที่อยู่หรือจุดสังเกตใกล้เคียง\n"
                "ขอรถพยาบาลด่วนครับ/ค่ะ"
            )

        response_payload = {
            "route": "emergency_guidance",
            "is_emergency": True,
            "adk_available": ADK_AVAILABLE,
            "severity": severity,
            "facility_type": facility_type,
            "guidance": guidance_text,
            "general_info": "",
            "call_script": call_script,
            "location_context": location_context,
            "facilities": facilities,
            "triage_reason": triage.get("reason_th", ""),
        }
        try:
            self.judge_service.submit(
                {
                    "scenario": scenario,
                    "severity": severity,
                    "rag_source": rag_result.get("source", "none"),
                    "rag_count": int(rag_result.get("count", 0) or 0),
                    "rag_context": rag_context,
                    "guidance": guidance_text,
                    "facilities": facilities,
                    "call_script": call_script,
                }
            )
        except Exception as exc:
            record_exception(exc)
        return response_payload
