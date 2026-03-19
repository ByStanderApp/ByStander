import base64
import os
import threading
from typing import Any, Callable, Dict

try:
    from langfuse import observe as _langfuse_observe  # type: ignore
except Exception:  # pragma: no cover
    _langfuse_observe = None

try:
    from opentelemetry import trace as otel_trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.trace.status import Status, StatusCode

    OTEL_AVAILABLE = True
except Exception:  # pragma: no cover
    otel_trace = None
    OTLPSpanExporter = None
    Resource = None
    TracerProvider = None
    BatchSpanProcessor = None
    Status = None
    StatusCode = None
    OTEL_AVAILABLE = False

try:
    from openinference.instrumentation.vertexai import VertexAIInstrumentor

    VERTEX_INSTRUMENTOR_AVAILABLE = True
except Exception:  # pragma: no cover
    VertexAIInstrumentor = None
    VERTEX_INSTRUMENTOR_AVAILABLE = False


_LOCK = threading.Lock()
_INITIALIZED = False
_STATUS: Dict[str, Any] = {
    "enabled": False,
    "otel_available": OTEL_AVAILABLE,
    "vertex_instrumentor_available": VERTEX_INSTRUMENTOR_AVAILABLE,
    "langfuse_observe_available": bool(_langfuse_observe),
    "endpoint": "",
    "error": "",
}


def observe(*args, **kwargs):
    """
    Safe wrapper around Langfuse @observe().
    Falls back to a no-op decorator when langfuse is not installed.
    """

    if _langfuse_observe is None:
        def _noop_decorator(func: Callable):
            return func

        if len(args) == 1 and callable(args[0]) and not kwargs:
            return args[0]
        return _noop_decorator
    return _langfuse_observe(*args, **kwargs)


def record_exception(exc: Exception) -> None:
    """
    Record an exception into the currently active OTel span if available.
    """

    if not OTEL_AVAILABLE or otel_trace is None:
        return
    try:
        span = otel_trace.get_current_span()
        if span is None:
            return
        if hasattr(span, "is_recording") and not span.is_recording():
            return
        span.record_exception(exc)
        if Status is not None and StatusCode is not None:
            span.set_status(Status(StatusCode.ERROR, str(exc)))
    except Exception:
        # Never fail app flow due to observability.
        return


def _build_langfuse_auth_header(public_key: str, secret_key: str) -> str:
    token = base64.b64encode(f"{public_key}:{secret_key}".encode("utf-8")).decode("utf-8")
    return f"Basic {token}"


def init_observability(service_name: str = "bystander-agent-workflow") -> Dict[str, Any]:
    """
    Initialize OpenTelemetry and export traces to Langfuse OTEL endpoint.
    Also instruments Vertex AI calls via OpenInference VertexAIInstrumentor.
    """

    global _INITIALIZED
    with _LOCK:
        if _INITIALIZED:
            return dict(_STATUS)

        if not OTEL_AVAILABLE:
            _STATUS["error"] = "OpenTelemetry SDK is not available"
            return dict(_STATUS)

        public_key = (os.getenv("LANGFUSE_PUBLIC_KEY") or "").strip()
        secret_key = (os.getenv("LANGFUSE_SECRET_KEY") or "").strip()
        host = (os.getenv("LANGFUSE_HOST") or "https://cloud.langfuse.com").strip().rstrip("/")
        if not public_key or not secret_key:
            _STATUS["error"] = "LANGFUSE_PUBLIC_KEY or LANGFUSE_SECRET_KEY is missing"
            return dict(_STATUS)

        endpoint = f"{host}/api/public/otel/v1/traces"

        try:
            resource = Resource.create({"service.name": service_name})
            tracer_provider = TracerProvider(resource=resource)
            exporter = OTLPSpanExporter(
                endpoint=endpoint,
                headers={"Authorization": _build_langfuse_auth_header(public_key, secret_key)},
            )
            tracer_provider.add_span_processor(BatchSpanProcessor(exporter))
            otel_trace.set_tracer_provider(tracer_provider)

            if VERTEX_INSTRUMENTOR_AVAILABLE and VertexAIInstrumentor is not None:
                try:
                    VertexAIInstrumentor().instrument(tracer_provider=tracer_provider)
                except Exception as exc:
                    _STATUS["error"] = f"VertexAI instrumentation failed: {exc}"

            _STATUS.update(
                {
                    "enabled": True,
                    "endpoint": endpoint,
                }
            )
            _INITIALIZED = True
            return dict(_STATUS)
        except Exception as exc:
            _STATUS["error"] = f"Observability init failed: {exc}"
            return dict(_STATUS)

