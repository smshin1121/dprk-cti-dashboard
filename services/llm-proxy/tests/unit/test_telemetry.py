"""Unit tests for ``llm_proxy.telemetry._otlp_insecure_from_env``.

The llm-proxy's telemetry module exposes a tiny env-driven helper for
the OTLP exporter ``insecure`` flag (previously hardcoded ``True``).
These tests pin the parser contract documented in the env templates so
a future refactor cannot quietly flip the default or stop honoring an
operator override.
"""
from __future__ import annotations

import pytest

from llm_proxy.telemetry import _otlp_insecure_from_env


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
    with caplog.at_level("WARNING", logger="llm_proxy.telemetry"):
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
    with caplog.at_level("WARNING", logger="llm_proxy.telemetry"):
        assert _otlp_insecure_from_env() is True
    matching = [
        r for r in caplog.records if "unrecognized value" in r.message
    ]
    assert len(matching) == 1, (
        f"expected exactly one unrecognized-value warning for {raw!r}, "
        f"got {[r.message for r in caplog.records]}"
    )
    assert raw in matching[0].getMessage()
