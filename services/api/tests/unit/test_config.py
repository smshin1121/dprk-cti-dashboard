"""Unit tests for api.config hybrid-search settings — PR #19b Group A.

Pins the 3 net-new ``Settings`` fields added for PR #19b hybrid
``/search``:

- ``hybrid_search_coverage_threshold`` (plan D5)
- ``hybrid_search_vector_k`` (plan D2 / OI1 = B)
- ``hybrid_search_coverage_refresh_seconds`` (plan D5 / OI4 = B)

Each field has an accompanying ``@field_validator`` enforcing bounds
documented in the plan. These tests exercise the default values, env
override path, and every out-of-range rejection case so Group B can
rely on the Settings object producing valid values or failing fast.

Also pins the ``session_cookie_secure`` secure-by-default contract
(default ``True`` since the Phase 0 deferral was closed) so a future
config refactor cannot quietly regress production cookies to
``Secure=False``.

Other ``Settings`` fields stay out of scope — their coverage lives in
the env-injection setup in ``services/api/tests/conftest.py`` plus
whatever production behaviour tests already exercise.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from api.config import Settings


class TestHybridSearchSettingsDefaults:
    def test_defaults_match_plan(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When the 3 env vars are unset, defaults match the plan."""
        monkeypatch.delenv("HYBRID_SEARCH_COVERAGE_THRESHOLD", raising=False)
        monkeypatch.delenv("HYBRID_SEARCH_VECTOR_K", raising=False)
        monkeypatch.delenv("HYBRID_SEARCH_COVERAGE_REFRESH_SECONDS", raising=False)

        settings = Settings()

        assert settings.hybrid_search_coverage_threshold == 0.5
        assert settings.hybrid_search_vector_k == 50
        assert settings.hybrid_search_coverage_refresh_seconds == 600


class TestHybridSearchSettingsEnvOverride:
    def test_vector_k_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``HYBRID_SEARCH_VECTOR_K=25`` overrides the default."""
        monkeypatch.setenv("HYBRID_SEARCH_VECTOR_K", "25")

        settings = Settings()

        assert settings.hybrid_search_vector_k == 25


class TestHybridSearchSettingsBounds:
    def test_coverage_threshold_above_one_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Threshold > 1.0 fails at Settings construction."""
        monkeypatch.setenv("HYBRID_SEARCH_COVERAGE_THRESHOLD", "1.5")

        with pytest.raises(ValidationError) as exc_info:
            Settings()

        assert "hybrid_search_coverage_threshold" in str(exc_info.value)

    def test_coverage_threshold_negative_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Threshold < 0.0 fails at Settings construction."""
        monkeypatch.setenv("HYBRID_SEARCH_COVERAGE_THRESHOLD", "-0.1")

        with pytest.raises(ValidationError) as exc_info:
            Settings()

        assert "hybrid_search_coverage_threshold" in str(exc_info.value)

    def test_vector_k_zero_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``vector_k`` = 0 fails at Settings construction."""
        monkeypatch.setenv("HYBRID_SEARCH_VECTOR_K", "0")

        with pytest.raises(ValidationError) as exc_info:
            Settings()

        assert "hybrid_search_vector_k" in str(exc_info.value)

    def test_refresh_seconds_zero_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``refresh_seconds`` = 0 fails at Settings construction."""
        monkeypatch.setenv("HYBRID_SEARCH_COVERAGE_REFRESH_SECONDS", "0")

        with pytest.raises(ValidationError) as exc_info:
            Settings()

        assert "hybrid_search_coverage_refresh_seconds" in str(exc_info.value)


class TestSessionCookieSecureDefault:
    """Pin the secure-by-default contract for ``session_cookie_secure``.

    The Phase 0 deferral was closed by flipping the default from ``False``
    to ``True``. These tests pin the new default + the env override path
    so a future refactor cannot quietly regress production cookies to
    ``Secure=False``.

    Dev / test / CI continue to override to ``False`` explicitly via
    ``envs/api.env.example`` and ``services/api/tests/conftest.py`` because
    the dev compose serves HTTP — the override path is exercised below.
    """

    def test_default_is_true_when_env_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unset ``SESSION_COOKIE_SECURE`` → default ``True`` (secure-by-default).

        conftest.py uses ``os.environ.setdefault`` to seed test envs, so the
        var is in ``os.environ`` by the time any test runs; ``delenv`` removes
        it so ``Settings()`` falls through to the class-level default.
        """
        monkeypatch.delenv("SESSION_COOKIE_SECURE", raising=False)

        settings = Settings()

        assert settings.session_cookie_secure is True

    def test_env_override_to_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``SESSION_COOKIE_SECURE=false`` flips the flag for dev/CI HTTP."""
        monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")

        settings = Settings()

        assert settings.session_cookie_secure is False

    def test_env_override_to_true_explicit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Explicit ``SESSION_COOKIE_SECURE=true`` keeps the secure default."""
        monkeypatch.setenv("SESSION_COOKIE_SECURE", "true")

        settings = Settings()

        assert settings.session_cookie_secure is True
