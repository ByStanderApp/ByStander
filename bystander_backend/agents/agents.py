import csv
import math
import os
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from facility_finder.main import search_nearby_facilities

from .llm_agent import GeminiJSONAgent, GuidanceAgent, ScriptAgent, TriageAgent

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


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(d_lon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c


def _split_csv_env(value: str) -> List[str]:
    raw = _normalize_text(value)
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


def _dedupe_nonempty(values: List[str]) -> List[str]:
    out: List[str] = []
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

    def __init__(self, csv_path: Optional[str] = None) -> None:
        base_dir = os.path.dirname(os.path.dirname(__file__))
        self.csv_path = csv_path or os.path.join(base_dir, "finetuning", "instructions_raw_final.csv")
        self.rows = self._load_rows()
        self.vertex_project = _normalize_text(os.getenv("GOOGLE_CLOUD_PROJECT"))
        self.vertex_project_number = _normalize_text(os.getenv("VERTEX_PROJECT_NUMBER"))
        self.vertex_location = _normalize_text(os.getenv("VERTEX_LOCATION") or "global")
        self.rag_location = _normalize_text(os.getenv("VERTEX_RAG_LOCATION") or "us-east1")
        self.rag_corpus_display_name = _normalize_text(
            os.getenv("VERTEX_RAG_CORPUS_NAME") or "ByStander Rag Corpus"
        )
        self.rag_corpus_resource_override = _normalize_text(
            os.getenv("VERTEX_RAG_CORPUS_RESOURCE")
        )
        rag_top_k_raw = _normalize_text(os.getenv("VERTEX_RAG_TOP_K") or "8")
        try:
            self.rag_similarity_top_k_default = int(rag_top_k_raw)
        except Exception:
            self.rag_similarity_top_k_default = 8
        rag_threshold_raw = _normalize_text(os.getenv("VERTEX_RAG_VECTOR_DISTANCE_THRESHOLD"))
        self.rag_vector_distance_threshold = _safe_float(rag_threshold_raw)
        self.last_vertex_error: str = ""
        self.last_vertex_attempts: List[Dict[str, str]] = []
        self.adc_project = self._detect_adc_project()
        self.vertex_project_candidates = self._build_project_candidates()
        self.rag_project = self._select_rag_project()
        self.rag_initialized = self._init_rag()
        self.rag_corpus_resource = self._resolve_rag_corpus_resource()

    def _load_rows(self) -> List[Dict[str, str]]:
        if not os.path.exists(self.csv_path):
            return []
        out: List[Dict[str, str]] = []
        with open(self.csv_path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                out.append(
                    {
                        "case_name_th": _normalize_text(row.get("Case Name (TH)", "")),
                        "case_name_en": _normalize_text(row.get("Case Name (EN)", "")),
                        "keywords": _normalize_text(row.get("Keywords", "")),
                        "instructions": _normalize_text(row.get("Instructions", "")),
                        "severity": _normalize_text(row.get("severity", "")).lower(),
                        "facility_type": _normalize_text(row.get("facility_type", "")).lower(),
                    }
                )
        return out

    def _score_row(self, query: str, row: Dict[str, str], severity: str) -> int:
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

    def _build_project_candidates(self) -> List[str]:
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

        self.last_vertex_error = (
            f"RAG corpus '{self.rag_corpus_display_name}' not found in {self.rag_project}/{self.rag_location}"
        )
        return ""

    def _search_vertex(self, query: str, severity: str, top_k: int) -> List[Dict[str, str]]:
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

            query_top_k = top_k if isinstance(top_k, int) and top_k > 0 else self.rag_similarity_top_k_default
            final_top_k = max(1, min(query_top_k, 20))
            retrieval_config_kwargs: Dict[str, Any] = {"top_k": final_top_k}
            if self.rag_vector_distance_threshold is not None:
                retrieval_config_kwargs["filter"] = rag.Filter(
                    vector_distance_threshold=self.rag_vector_distance_threshold
                )

            response = rag.retrieval_query(
                rag_resources=[rag.RagResource(rag_corpus=self.rag_corpus_resource)],
                rag_retrieval_config=rag.RagRetrievalConfig(**retrieval_config_kwargs),
                text=scoped_query,
            )

            docs: List[Dict[str, str]] = []
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

    def _format_vertex_context(self, docs: List[Dict[str, str]]) -> str:
        chunks: List[str] = []
        for i, d in enumerate(docs, start=1):
            title = _normalize_text(d.get("title"))
            body = _normalize_text(d.get("body"))
            meta = _normalize_text(d.get("meta"))
            chunks.append(
                f"[Vertex Protocol {i}] {title}\n"
                f"{('- ' + meta) if meta else ''}\n"
                f"{body}".strip()
            )
        return "\n\n".join(chunks).strip()

    def retrieve(self, query: str, severity: str, top_k: int = 3) -> str:
        result = self.retrieve_with_meta(query=query, severity=severity, top_k=top_k)
        return result["context"]

    def retrieve_with_meta(self, query: str, severity: str, top_k: int = 3) -> Dict[str, Any]:
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
                "context": "ไม่มีบริบทจากฐานข้อมูลโปรโตคอล ให้ยึดหลักความปลอดภัยและโทร 1669 เมื่อสงสัยว่าเป็นเหตุฉุกเฉิน",
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

        chunks: List[str] = []
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

    def debug_vertex_status(self, scenario: str, severity: str, top_k: int = 3) -> Dict[str, Any]:
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

        diagnostics: Dict[str, Any] = {
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
                "vertex_attempts": result.get("vertex_attempts", self.last_vertex_attempts),
                "context_preview": _normalize_text(result.get("context", ""))[:1200],
            }
        )
        return diagnostics

    def debug_vertex_resources(self) -> Dict[str, Any]:
        details: Dict[str, Any] = {
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
                        "display_name": _normalize_text(getattr(corpus, "display_name", "")),
                    }
                )
        except Exception as exc:
            details["error"] = f"rag.list_corpora failed: {exc}"
        return details

    def catalog(self) -> List[Dict[str, str]]:
        return self.rows


class MapAgent:
    def run(
        self,
        scenario: str,
        severity: str,
        facility_type: str,
        latitude: Optional[float],
        longitude: Optional[float],
    ) -> List[Dict[str, Any]]:
        if latitude is None or longitude is None:
            return []

        map_severity = "critical" if severity == "critical" else "mild"
        fac_type = facility_type if facility_type in {"hospital", "clinic"} else "hospital"
        result = search_nearby_facilities(
            latitude=latitude,
            longitude=longitude,
            facility_type=fac_type,
            severity=map_severity,
        )
        if not isinstance(result, dict) or "error" in result:
            return []

        facilities = result.get("facilities", []) or []
        cleaned: List[Dict[str, Any]] = []
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
                service_account_path = _normalize_text(os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH"))
                if service_account_path and os.path.exists(service_account_path):
                    cred = credentials.Certificate(service_account_path)
                    firebase_admin.initialize_app(cred)
                else:
                    firebase_admin.initialize_app()
            self.firestore = firestore
            self.available = True
        except Exception:
            self.available = False

    def get_user_profile(self, user_id: str) -> Dict[str, Any]:
        if not self.available or not user_id:
            return {}
        db = self.firestore.client()
        profile: Dict[str, Any] = {}

        try:
            user_doc = db.collection("users").document(user_id).get()
            if user_doc.exists:
                data = user_doc.to_dict() or {}
                profile["firstName"] = data.get("firstName") or ""
                profile["lastName"] = data.get("lastName") or ""
                profile["gender"] = data.get("gender") or ""
                profile["birthdate"] = data.get("birthdate") or data.get("dateOfBirth") or ""
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
                db.collection("users")
                .document(user_id)
                .collection("relatives")
                .limit(3)
                .stream()
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

    def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        scenario = _normalize_text(payload.get("scenario") or payload.get("sentence"))
        if not scenario:
            raise ValueError("scenario is required")

        triage = self.triage_agent.run(scenario)
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

        rag_context = self.retriever.retrieve(query=scenario, severity=severity)
        guidance_result = self.guidance_agent.run(
            scenario=scenario,
            severity=severity,
            rag_context=rag_context,
        )
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

        user_id = _normalize_text(payload.get("user_id"))
        user_profile = self.profile_service.get_user_profile(user_id=user_id) if user_id else {}
        call_script = self.script_agent.run(
            scenario=scenario,
            guidance=guidance_text,
            user_profile=user_profile,
        )

        return {
            "route": "emergency_guidance",
            "is_emergency": True,
            "adk_available": ADK_AVAILABLE,
            "severity": severity,
            "facility_type": facility_type,
            "guidance": guidance_text,
            "general_info": "",
            "call_script": call_script,
            "facilities": facilities,
            "triage_reason": triage.get("reason_th", ""),
        }
