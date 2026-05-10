"""Unit tests for ``worker.telemetry._otlp_insecure_from_env``.

The worker's telemetry module exposes a tiny env-driven helper for the
OTLP exporter ``insecure`` flag (previously hardcoded ``True``). These
tests pin the parser contract documented in the env templates so a
future refactor cannot quietly flip the default or stop honoring an
operator override.
"""
from __future__ import annotations

import pytest

from worker.telemetry import _otlp_insecure_from_env


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
def test_otlp_insecure_truthy_or_unknown_values_return_true(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    """Truthy spellings + empty string return True (backwards-compat default)."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_INSECURE", raw)
    assert _otlp_insecure_from_env() is True
