from flask import Flask, jsonify, make_response, request

try:
    from .agents import ByStanderWorkflow
except ImportError:  # pragma: no cover
    from agents import ByStanderWorkflow


app = Flask(__name__)
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
    return jsonify({"status": "ok", "service": "bystander_agent_workflow"})


if __name__ == "__main__":
    print("Starting ByStander Google ADK-style workflow service on port 5003...")
    app.run(debug=True, host="0.0.0.0", port=5003)
