"""Minimal OpenTelemetry SDK init for the worker service.

Sets up an OTLP/gRPC tracer provider with resource attribution. No
auto-instrumentors are wired in — Prefect flows can create manual spans
via ``opentelemetry.trace.get_tracer(__name__)`` if needed.

Idempotent: ``setup_telemetry`` is safe to call multiple times.
"""

from __future__ import annotations

import logging
import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

logger = logging.getLogger(__name__)
_initialized = False


_OTLP_INSECURE_TRUTHY = frozenset({"true", "1", "yes"})
_OTLP_INSECURE_FALSY = frozenset({"false", "0", "no"})


def _otlp_insecure_from_env() -> bool:
    """Resolve the OTLP exporter ``insecure`` flag from env.

    Reads ``OTEL_EXPORTER_OTLP_INSECURE``; defaults to ``True`` for
    backwards-compatibility with the previous hardcoded value. Operators
    deploying behind a TLS-terminating collector set the var to ``false``.

    Unrecognized values fall through to ``True`` and emit a
    ``logger.warning`` so an operator typo (e.g. ``"falze"``, ``"off"``)
    does not silently keep cleartext transport when TLS was intended.
    """
    raw = os.getenv("OTEL_EXPORTER_OTLP_INSECURE", "true").strip().lower()
    if raw in _OTLP_INSECURE_FALSY:
        return False
    if raw not in _OTLP_INSECURE_TRUTHY and raw != "":
        logger.warning(
            "OTEL_EXPORTER_OTLP_INSECURE unrecognized value %r; "
            "defaulting to insecure=True. Recognized: %s (truthy), %s (falsy).",
            raw,
            sorted(_OTLP_INSECURE_TRUTHY),
            sorted(_OTLP_INSECURE_FALSY),
        )
    return True


def setup_telemetry() -> None:
    """Configure OTLP tracing for the worker process.

    Reads OTEL_EXPORTER_OTLP_ENDPOINT and OTEL_SERVICE_NAME from env.
    A no-op if telemetry is disabled (env var unset) or already initialized.
    """
    global _initialized
    if _initialized:
        return

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    service_name = os.getenv("OTEL_SERVICE_NAME", "dprk-cti-worker")

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

    _initialized = True
    logger.info(
        "OTel telemetry initialized: service=%s endpoint=%s",
        service_name,
        endpoint,
    )
