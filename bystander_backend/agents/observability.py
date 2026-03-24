import base64
import os
import threading
from typing import Any, Callable, Dict
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError
import ssl

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

    VERTEX_INSTRUMENTOR_SOURCE = "openinference"
    VERTEX_INSTRUMENTOR_AVAILABLE = True
except Exception:  # pragma: no cover
    try:
        from opentelemetry.instrumentation.vertexai import VertexAIInstrumentor

        VERTEX_INSTRUMENTOR_SOURCE = "opentelemetry"
        VERTEX_INSTRUMENTOR_AVAILABLE = True
    except Exception:
        VertexAIInstrumentor = None
        VERTEX_INSTRUMENTOR_SOURCE = ""
        VERTEX_INSTRUMENTOR_AVAILABLE = False

try:
    import certifi
except Exception:  # pragma: no cover
    certifi = None


_LOCK = threading.Lock()
_INITIALIZED = False
_STATUS: Dict[str, Any] = {
    "enabled": False,
    "otel_available": OTEL_AVAILABLE,
    "vertex_instrumentor_available": VERTEX_INSTRUMENTOR_AVAILABLE,
    "vertex_instrumentor_source": VERTEX_INSTRUMENTOR_SOURCE,
    "langfuse_observe_available": bool(_langfuse_observe),
    "endpoint": "",
    "error": "",
    "auth_probe": "",
    "ca_bundle": "",
    "base_url": "",
    "host": "",
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
    token = base64.b64encode(f"{public_key}:{secret_key}".encode("utf-8")).decode(
        "utf-8"
    )
    return f"Basic {token}"


def _clean_env(value: str) -> str:
    v = (value or "").strip()
    if len(v) >= 2 and (
        (v[0] == '"' and v[-1] == '"') or (v[0] == "'" and v[-1] == "'")
    ):
        v = v[1:-1].strip()
    return v


def _resolve_ca_bundle() -> str:
    explicit = _clean_env(
        os.getenv("SSL_CERT_FILE") or os.getenv("REQUESTS_CA_BUNDLE") or ""
    )
    if explicit and os.path.exists(explicit):
        return explicit
    if certifi is not None:
        try:
            path = certifi.where()
            if path and os.path.exists(path):
                return path
        except Exception:
            pass
    return ""


def _probe_langfuse_auth(
    host: str,
    auth_header: str,
    timeout_sec: float = 5.0,
    ca_bundle: str = "",
    insecure_tls: bool = False,
) -> tuple[bool, str]:
    """
    Probe Langfuse public API auth to fail fast with clear diagnostics.
    """

    probe_url = f"{host.rstrip('/')}/api/public/projects"
    req = urllib_request.Request(
        probe_url,
        headers={"Authorization": auth_header},
        method="GET",
    )
    try:
        ssl_context = None
        if insecure_tls:
            ssl_context = ssl._create_unverified_context()
        elif ca_bundle:
            ssl_context = ssl.create_default_context(cafile=ca_bundle)

        with urllib_request.urlopen(
            req, timeout=timeout_sec, context=ssl_context
        ) as resp:
            code = int(getattr(resp, "status", 0) or 0)
            if 200 <= code < 300:
                return True, f"ok ({code})"
            return False, f"http_{code}"
    except HTTPError as exc:
        body = ""
        try:
            body = (exc.read() or b"").decode("utf-8", errors="ignore")[:300]
        except Exception:
            body = ""
        return False, f"http_{exc.code}: {body}".strip()
    except URLError as exc:
        return False, f"url_error: {exc}"
    except Exception as exc:
        return False, f"probe_error: {exc}"


def init_observability(
    service_name: str = "bystander-agent-workflow",
) -> Dict[str, Any]:
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

        public_key = _clean_env(os.getenv("LANGFUSE_PUBLIC_KEY") or "")
        secret_key = _clean_env(os.getenv("LANGFUSE_SECRET_KEY") or "")
        base_url = _clean_env(os.getenv("LANGFUSE_BASE_URL") or "")
        host = _clean_env(
            base_url or os.getenv("LANGFUSE_HOST") or "https://cloud.langfuse.com"
        ).rstrip("/")
        if not public_key or not secret_key:
            _STATUS["error"] = "LANGFUSE_PUBLIC_KEY or LANGFUSE_SECRET_KEY is missing"
            return dict(_STATUS)

        endpoint = f"{host}/api/public/otel/v1/traces"
        insecure_tls = _clean_env(
            os.getenv("LANGFUSE_OTEL_INSECURE_TLS") or ""
        ).lower() in {
            "1",
            "true",
            "yes",
        }
        ca_bundle = _resolve_ca_bundle()

        try:
            resource = Resource.create({"service.name": service_name})
            tracer_provider = TracerProvider(resource=resource)
            auth_header = _build_langfuse_auth_header(public_key, secret_key)
            ok, probe_detail = _probe_langfuse_auth(
                host=host,
                auth_header=auth_header,
                ca_bundle=ca_bundle,
                insecure_tls=insecure_tls,
            )
            _STATUS["auth_probe"] = probe_detail
            if not ok:
                _STATUS["error"] = (
                    "Langfuse auth probe failed (continuing with exporter init). "
                    "Check host/keys/TLS trust if exports still fail."
                )

            # Different OTLP exporter versions parse headers differently.
            # Try dict first (most robust), then fallback to string form.
            try:
                kwargs = {
                    "endpoint": endpoint,
                    "headers": {"Authorization": auth_header},
                }
                if ca_bundle:
                    kwargs["certificate_file"] = ca_bundle
                if insecure_tls:
                    kwargs["insecure"] = True
                exporter = OTLPSpanExporter(**kwargs)
            except Exception:
                kwargs = {
                    "endpoint": endpoint,
                    "headers": f"Authorization={auth_header}",
                }
                if ca_bundle:
                    kwargs["certificate_file"] = ca_bundle
                if insecure_tls:
                    kwargs["insecure"] = True
                exporter = OTLPSpanExporter(**kwargs)
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
                    "host": host,
                    "base_url": base_url or host,
                    "public_key_prefix": public_key[:8],
                    "ca_bundle": ca_bundle,
                }
            )
            _INITIALIZED = True
            return dict(_STATUS)
        except Exception as exc:
            _STATUS["error"] = f"Observability init failed: {exc}"
            return dict(_STATUS)
