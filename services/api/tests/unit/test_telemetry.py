"""Unit tests for api.telemetry redaction hooks (H-2s).

These tests don't exercise the full OTel pipeline — they only verify that
``_redact_httpx_request`` / ``_redact_httpx_response`` replace sensitive
header attributes on a recording span with ``[REDACTED]``.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from api.telemetry import _redact_httpx_request, _redact_httpx_response


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
