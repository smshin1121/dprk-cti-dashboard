"""Unit tests for api.telemetry redaction hooks (H-2s) + OTLP insecure env reader.

These tests don't exercise the full OTel pipeline — they only verify that
``_redact_httpx_request`` / ``_redact_httpx_response`` replace sensitive
header attributes on a recording span with ``[REDACTED]``, and that
``_otlp_insecure_from_env`` parses the OTEL_EXPORTER_OTLP_INSECURE env
var as documented.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from api.telemetry import (
    _otlp_insecure_from_env,
    _redact_httpx_request,
    _redact_httpx_response,
)


def _recording_span() -> MagicMock:
    span = MagicMock()
    span.is_recording.return_value = True
    return span


def test_redact_httpx_request_replaces_sensitive_headers():
    span = _recording_span()

    _redact_httpx_request(span, request=MagicMock())

    recorded = {
        call.args[0]: call.args[1] for call in span.set_attribute.call_args_list
    }
    assert recorded.get("http.request.header.authorization") == "[REDACTED]"
    assert recorded.get("http.request.header.cookie") == "[REDACTED]"
    assert recorded.get("http.request.header.x-internal-token") == "[REDACTED]"


def test_redact_httpx_response_replaces_sensitive_headers():
    span = _recording_span()

    _redact_httpx_response(span, request=MagicMock(), response=MagicMock())

    recorded = {
        call.args[0]: call.args[1] for call in span.set_attribute.call_args_list
    }
    assert recorded.get("http.response.header.set-cookie") == "[REDACTED]"
    assert recorded.get("http.response.header.www-authenticate") == "[REDACTED]"


def test_redact_hooks_no_op_on_non_recording_span():
    span = MagicMock()
    span.is_recording.return_value = False

    _redact_httpx_request(span, request=MagicMock())
    _redact_httpx_response(span, request=MagicMock(), response=MagicMock())

    span.set_attribute.assert_not_called()


def test_redact_hooks_handle_none_span():
    # Must not raise on a None span — some instrumentation paths pass None.
    _redact_httpx_request(None, request=MagicMock())
    _redact_httpx_response(None, request=MagicMock(), response=MagicMock())


def test_otlp_insecure_default_is_true(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset env var defaults to True — preserves the previous hardcoded value."""
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_INSECURE", raising=False)
    assert _otlp_insecure_from_env() is True


@pytest.mark.parametrize("raw", ["false", "FALSE", "False", "0", "no", "NO", " false "])
def test_otlp_insecure_falsy_values_return_false(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    """Documented falsy spellings flip the flag to False (TLS-terminating collector)."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_INSECURE", raw)
    assert _otlp_insecure_from_env() is False


@pytest.mark.parametrize("raw", ["true", "TRUE", "1", "yes", ""])
def test_otlp_insecure_truthy_or_empty_values_return_true_quietly(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, raw: str
) -> None:
    """Truthy spellings + empty string return True (backwards-compat default).

    These are recognized values and must NOT emit the unrecognized-value
    warning — only operator typos should trigger that path.
    """
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_INSECURE", raw)
    with caplog.at_level("WARNING", logger="api.telemetry"):
        assert _otlp_insecure_from_env() is True
    assert all(
        "unrecognized value" not in record.message for record in caplog.records
    ), f"unexpected warning for recognized value {raw!r}"


@pytest.mark.parametrize("raw", ["off", "disable", "falze", "tru", "enabled", "junk"])
def test_otlp_insecure_unrecognized_value_returns_true_with_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, raw: str
) -> None:
    """Unrecognized values fall through to True AND emit a logger.warning.

    Pins the security-adjacent contract: an operator typo must not
    silently keep cleartext transport when TLS was the intent.
    """
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_INSECURE", raw)
    with caplog.at_level("WARNING", logger="api.telemetry"):
        assert _otlp_insecure_from_env() is True
    matching = [
        r for r in caplog.records if "unrecognized value" in r.message
    ]
    assert len(matching) == 1, (
        f"expected exactly one unrecognized-value warning for {raw!r}, "
        f"got {[r.message for r in caplog.records]}"
    )
    assert raw in matching[0].getMessage()
