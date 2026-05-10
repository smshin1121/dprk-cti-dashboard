"""OpenTelemetry tracing/metrics setup for the API service.

Initializes an OTLP/gRPC exporter pointed at the otel-collector and
auto-instruments FastAPI, SQLAlchemy (async), HTTPX, and Redis.

Idempotent: ``setup_telemetry`` is safe to call multiple times.
"""

from __future__ import annotations

import logging
import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

logger = logging.getLogger(__name__)
_initialized = False


# ---------------------------------------------------------------------------
# HTTPX span redaction hooks (H-2s)
# ---------------------------------------------------------------------------
# OTel's HTTPX instrumentation can be configured to capture request/response
# headers on spans. These hooks defensively replace any sensitive headers that
# might have been captured with ``[REDACTED]`` before the span is exported, so
# a leaked OTel backend cannot expose bearer tokens or session cookies.
_SENSITIVE_REQUEST_HEADER_KEYS = (
    "http.request.header.authorization",
    "http.request.header.cookie",
    "http.request.header.x-internal-token",
    "http.request.header.x_internal_token",
)
_SENSITIVE_RESPONSE_HEADER_KEYS = (
    "http.response.header.set-cookie",
    "http.response.header.set_cookie",
    "http.response.header.www-authenticate",
    "http.response.header.www_authenticate",
)


def _otlp_insecure_from_env() -> bool:
    """Resolve the OTLP exporter ``insecure`` flag from env.

    Reads ``OTEL_EXPORTER_OTLP_INSECURE``; defaults to ``True`` for
    backwards-compatibility with the previous hardcoded value. Operators
    deploying behind a TLS-terminating collector set the var to ``false``.
    """
    raw = os.getenv("OTEL_EXPORTER_OTLP_INSECURE", "true").strip().lower()
    return raw not in ("false", "0", "no")


def _redact_httpx_request(span, request) -> None:
    """Remove sensitive headers from outgoing HTTPX spans."""
    if span is None or not getattr(span, "is_recording", lambda: False)():
        return
    for key in _SENSITIVE_REQUEST_HEADER_KEYS:
        try:
            span.set_attribute(key, "[REDACTED]")
        except Exception:  # noqa: BLE001 — never let instrumentation raise
            pass


def _redact_httpx_response(span, request, response) -> None:
    """Remove sensitive headers from HTTPX response spans."""
    if span is None or not getattr(span, "is_recording", lambda: False)():
        return
    for key in _SENSITIVE_RESPONSE_HEADER_KEYS:
        try:
            span.set_attribute(key, "[REDACTED]")
        except Exception:  # noqa: BLE001
            pass


def setup_telemetry(app, *, engine=None) -> None:
    """Configure OTLP tracing for the FastAPI app and (optionally) the DB engine.

    Reads OTEL_EXPORTER_OTLP_ENDPOINT and OTEL_SERVICE_NAME from env.
    A no-op if telemetry is disabled (env var unset) or already initialized.
    """
    global _initialized
    if _initialized:
        return

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    service_name = os.getenv("OTEL_SERVICE_NAME", "dprk-cti-api")

    if not endpoint:
        logger.info("OTEL_EXPORTER_OTLP_ENDPOINT not set; telemetry disabled")
        return

    resource = Resource.create(
        {
            "service.name": service_name,
            "service.namespace": "dprk-cti",
            "deployment.environment": os.getenv("APP_ENV", "dev"),
        }
    )

    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=endpoint, insecure=_otlp_insecure_from_env())
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    FastAPIInstrumentor.instrument_app(app, excluded_urls="/healthz,/api/v1/meta")
    HTTPXClientInstrumentor().instrument(
        request_hook=_redact_httpx_request,
        response_hook=_redact_httpx_response,
    )
    if engine is not None:
        # SQLAlchemyInstrumentor takes the *sync* form of the engine. For
        # async engines, instrument the underlying sync engine via
        # ``engine.sync_engine``.
        SQLAlchemyInstrumentor().instrument(
            engine=getattr(engine, "sync_engine", engine),
            enable_commenter=True,
        )

    _initialized = True
    logger.info(
        "OTel telemetry initialized: service=%s endpoint=%s",
        service_name,
        endpoint,
    )
