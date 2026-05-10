"""Minimal OpenTelemetry setup for the LLM proxy service.

Sets up an OTLP/gRPC tracer provider and the FastAPI auto-instrumentor so
HTTP spans are emitted for every request. No SQLAlchemy / HTTPX
instrumentors — the proxy is a thin pass-through and we want minimal
overhead.

Idempotent: ``setup_telemetry`` is safe to call multiple times.
"""

from __future__ import annotations

import logging
import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

logger = logging.getLogger(__name__)
_initialized = False


def _otlp_insecure_from_env() -> bool:
    """Resolve the OTLP exporter ``insecure`` flag from env.

    Reads ``OTEL_EXPORTER_OTLP_INSECURE``; defaults to ``True`` for
    backwards-compatibility with the previous hardcoded value. Operators
    deploying behind a TLS-terminating collector set the var to ``false``.
    """
    raw = os.getenv("OTEL_EXPORTER_OTLP_INSECURE", "true").strip().lower()
    return raw not in ("false", "0", "no")


def setup_telemetry(app) -> None:
    """Configure OTLP tracing and FastAPI auto-instrumentation.

    Reads OTEL_EXPORTER_OTLP_ENDPOINT and OTEL_SERVICE_NAME from env.
    A no-op if telemetry is disabled (env var unset) or already initialized.
    """
    global _initialized
    if _initialized:
        return

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    service_name = os.getenv("OTEL_SERVICE_NAME", "dprk-cti-llm-proxy")

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

    FastAPIInstrumentor.instrument_app(app, excluded_urls="/healthz")

    _initialized = True
    logger.info(
        "OTel telemetry initialized: service=%s endpoint=%s",
        service_name,
        endpoint,
    )
