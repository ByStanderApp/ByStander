import os
import sys

from flask import Flask, jsonify, make_response, request
import requests

if __package__:
    from .agents import ByStanderWorkflow
    from .observability import init_observability
else:  # pragma: no cover
    current_dir = os.path.dirname(os.path.abspath(__file__))
    if current_dir not in sys.path:
        sys.path.insert(0, current_dir)
    from agents import ByStanderWorkflow
    from observability import init_observability


app = Flask(__name__)
OBSERVABILITY_STATUS = init_observability(service_name="bystander-agent-workflow")
workflow = ByStanderWorkflow()


def _build_cors_preflight_response():
    response = make_response()
    response.headers.add("Access-Control-Allow-Origin", "*")
    response.headers.add("Access-Control-Allow-Headers", "Content-Type,Authorization")
    response.headers.add("Access-Control-Allow-Methods", "POST,GET,OPTIONS")
    return response


def _corsify_actual_response(response):
    response.headers.add("Access-Control-Allow-Origin", "*")
    return response


def _safe_float(value):
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _google_tts_api_key() -> str:
    return (
        str(
            os.getenv("GOOGLE_TTS_API_KEY")
            or os.getenv("GOOGLE_API_KEY")
            or ""
        )
        .strip()
    )


def _synthesize_with_google_tts(text: str) -> dict:
    api_key = _google_tts_api_key()
    if not api_key:
        return {"error": "GOOGLE_TTS_API_KEY or GOOGLE_API_KEY is missing"}

    endpoint = "https://texttospeech.googleapis.com/v1/text:synthesize"
    params = {"key": api_key}
    payload = {
        "input": {"text": text},
        "voice": {"languageCode": "th-TH", "ssmlGender": "NEUTRAL"},
        "audioConfig": {"audioEncoding": "MP3", "speakingRate": 1.0, "pitch": 0.0},
    }

    try:
        response = requests.post(endpoint, params=params, json=payload, timeout=20)
        response.raise_for_status()
        data = response.json() if response.content else {}
        audio_content = str(data.get("audioContent") or "").strip()
        if not audio_content:
            return {"error": "Google TTS returned empty audioContent"}
        return {"audioContent": audio_content}
    except requests.RequestException as exc:
        detail = ""
        try:
            detail = response.text  # type: ignore[name-defined]
        except Exception:
            detail = ""
        if detail:
            return {"error": f"Google TTS request failed: {exc}", "detail": detail}
        return {"error": f"Google TTS request failed: {exc}"}
    except Exception as exc:
        return {"error": f"Google TTS failed: {exc}"}


@app.route("/agent_workflow", methods=["POST", "OPTIONS"])
def agent_workflow():
    if request.method == "OPTIONS":
        return _build_cors_preflight_response()

    try:
        data = request.get_json() or {}
        result = workflow.run(data)
        return _corsify_actual_response(jsonify(result))
    except ValueError as exc:
        return _corsify_actual_response(jsonify({"error": str(exc)})), 400
    except Exception as exc:
        return _corsify_actual_response(
            jsonify({"error": "agent workflow failed", "detail": str(exc)})
        ), 500


@app.route("/find_facilities", methods=["POST", "OPTIONS"])
def find_facilities():
    if request.method == "OPTIONS":
        return _build_cors_preflight_response()

    try:
        data = request.get_json() or {}
        latitude = _safe_float(data.get("latitude"))
        longitude = _safe_float(data.get("longitude"))
        if latitude is None or longitude is None:
            return _corsify_actual_response(
                jsonify({"error": "latitude and longitude are required"})
            ), 400

        if not (-90 <= latitude <= 90) or not (-180 <= longitude <= 180):
            return _corsify_actual_response(
                jsonify({"error": "Invalid latitude or longitude values"})
            ), 400

        facility_type = str(data.get("facility_type") or "hospital").strip().lower()
        severity = str(data.get("severity") or "none").strip().lower()
        scenario = str(data.get("scenario") or "").strip()
        result = workflow.map_agent.search_nearby_facilities(
            latitude=latitude,
            longitude=longitude,
            facility_type=facility_type,
            severity=severity,
            scenario=scenario,
        )
        status = 503 if isinstance(result, dict) and "error" in result else 200
        return _corsify_actual_response(jsonify(result)), status
    except Exception as exc:
        return _corsify_actual_response(
            jsonify({"error": "find facilities failed", "detail": str(exc)})
        ), 500


@app.route("/synthesize_speech", methods=["POST", "OPTIONS"])
def synthesize_speech():
    if request.method == "OPTIONS":
        return _build_cors_preflight_response()

    try:
        data = request.get_json() or {}
        text = str(data.get("text") or "").strip()
        if not text:
            return _corsify_actual_response(jsonify({"error": "text is required"})), 400
        result = _synthesize_with_google_tts(text)
        if "error" in result:
            status = 502 if "request failed" in str(result.get("error")).lower() else 500
            return _corsify_actual_response(jsonify(result)), status
        return _corsify_actual_response(jsonify(result))
    except Exception as exc:
        return _corsify_actual_response(
            jsonify({"error": "synthesize speech failed", "detail": str(exc)})
        ), 500


@app.route("/general_first_aid_catalog", methods=["GET"])
def general_first_aid_catalog():
    return _corsify_actual_response(jsonify({"items": workflow.retriever.catalog()}))


@app.route("/debug_retrieval", methods=["POST", "OPTIONS"])
def debug_retrieval():
    if request.method == "OPTIONS":
        return _build_cors_preflight_response()

    try:
        data = request.get_json() or {}
        scenario = str(data.get("scenario") or data.get("query") or "").strip()
        if not scenario:
            return _corsify_actual_response(jsonify({"error": "scenario is required"})), 400
        severity = str(data.get("severity") or "moderate").strip().lower()
        if severity not in {"critical", "moderate", "none"}:
            severity = "moderate"
        top_k = int(data.get("top_k") or 3)
        if top_k < 1:
            top_k = 1
        if top_k > 10:
            top_k = 10

        result = workflow.retriever.retrieve_with_meta(
            query=scenario,
            severity=severity,
            top_k=top_k,
        )
        context = str(result.get("context") or "")
        return _corsify_actual_response(
            jsonify(
                {
                    "source": result.get("source", "none"),
                    "count": int(result.get("count", 0) or 0),
                    "severity": severity,
                    "top_k": top_k,
                    "vertex_error": result.get("vertex_error", ""),
                    "vertex_attempts": result.get("vertex_attempts", []),
                    "context_preview": context[:1200],
                    "context": context,
                }
            )
        )
    except Exception as exc:
        return _corsify_actual_response(
            jsonify({"error": "debug retrieval failed", "detail": str(exc)})
        ), 500


@app.route("/debug_vertex", methods=["POST", "OPTIONS"])
def debug_vertex():
    if request.method == "OPTIONS":
        return _build_cors_preflight_response()

    try:
        data = request.get_json() or {}
        scenario = str(data.get("scenario") or data.get("query") or "").strip()
        severity = str(data.get("severity") or "moderate").strip().lower()
        top_k = int(data.get("top_k") or 3)
        if top_k < 1:
            top_k = 1
        if top_k > 10:
            top_k = 10

        result = workflow.retriever.debug_vertex_status(
            scenario=scenario,
            severity=severity,
            top_k=top_k,
        )
        return _corsify_actual_response(jsonify(result))
    except Exception as exc:
        return _corsify_actual_response(
            jsonify({"error": "debug vertex failed", "detail": str(exc)})
        ), 500


@app.route("/debug_vertex_resources", methods=["GET"])
def debug_vertex_resources():
    try:
        result = workflow.retriever.debug_vertex_resources()
        return _corsify_actual_response(jsonify(result))
    except Exception as exc:
        return _corsify_actual_response(
            jsonify({"error": "debug vertex resources failed", "detail": str(exc)})
        ), 500


@app.route("/health", methods=["GET"])
def health():
    return jsonify(
        {
            "status": "ok",
            "service": "bystander_agent_workflow",
            "observability": OBSERVABILITY_STATUS,
        }
    )


if __name__ == "__main__":
    print("Starting ByStander Google ADK-style workflow service on port 5003...")
    app.run(debug=True, host="0.0.0.0", port=5003)
