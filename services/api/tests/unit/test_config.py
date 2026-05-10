"""Unit tests for api.config — hybrid-search settings + session-cookie security.

Three contracts pinned:

1. **PR #19b Group A — hybrid search field validators**
   Pins the 3 net-new ``Settings`` fields added for PR #19b hybrid
   ``/search``:
     - ``hybrid_search_coverage_threshold`` (plan D5)
     - ``hybrid_search_vector_k`` (plan D2 / OI1 = B)
     - ``hybrid_search_coverage_refresh_seconds`` (plan D5 / OI4 = B)

   Each field has an accompanying ``@field_validator`` enforcing bounds
   documented in the plan. These tests exercise default values, env
   override path, and every out-of-range rejection case.

2. **Phase 0 deferral — session_cookie_secure secure-by-default**
   Pins the ``True`` default + the ``app_env=='prod'`` fail-closed
   guard against ``SESSION_COOKIE_SECURE=false`` so a future config
   refactor cannot quietly regress production cookies to ``Secure=False``.

3. **Phase 0 deferral — session_cookie_name __Host- prefix**
   Pins the ``__Host-dprk_cti_session`` default + the
   ``app_env=='prod'`` fail-closed guard requiring the ``__Host-``
   prefix. The prefix forces browser-side enforcement of Secure +
   Path=/ + no Domain attribute, closing cookie-fixation /
   subdomain-injection vectors that ``Secure=True`` alone does not.

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


class TestSessionCookieSecureProdFailClosed:
    """Pin the ``app_env=='prod'`` fail-closed guard.

    Mirrors the ``rate_limit_storage_url`` policy on the same Settings
    class: prod MUST refuse to boot if a critical security-default has
    been turned off. The default-flip closes the implicit-False case;
    this validator closes the explicit-False-in-prod case.
    """

    def test_prod_with_secure_false_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``APP_ENV=prod`` + ``SESSION_COOKIE_SECURE=false`` → boot fails."""
        monkeypatch.setenv("APP_ENV", "prod")
        monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")
        # Satisfy the sibling __Host- validator so we isolate the
        # session_cookie_secure failure path.
        monkeypatch.delenv("SESSION_COOKIE_NAME", raising=False)

        with pytest.raises(ValidationError) as exc_info:
            Settings()

        assert "session_cookie_secure must be True" in str(exc_info.value)
        assert "prod" in str(exc_info.value)

    def test_prod_with_secure_true_boots(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``APP_ENV=prod`` + explicit ``SESSION_COOKIE_SECURE=true`` is fine."""
        monkeypatch.setenv("APP_ENV", "prod")
        monkeypatch.setenv("SESSION_COOKIE_SECURE", "true")
        monkeypatch.delenv("SESSION_COOKIE_NAME", raising=False)

        settings = Settings()

        assert settings.app_env == "prod"
        assert settings.session_cookie_secure is True

    def test_prod_with_secure_unset_boots_via_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``APP_ENV=prod`` + unset env var → default True → no fail-closed."""
        monkeypatch.setenv("APP_ENV", "prod")
        monkeypatch.delenv("SESSION_COOKIE_SECURE", raising=False)
        monkeypatch.delenv("SESSION_COOKIE_NAME", raising=False)

        settings = Settings()

        assert settings.app_env == "prod"
        assert settings.session_cookie_secure is True

    @pytest.mark.parametrize("env", ["dev", "test", "ci", "staging"])
    def test_non_prod_with_secure_false_boots(
        self, monkeypatch: pytest.MonkeyPatch, env: str
    ) -> None:
        """Non-prod envs with ``SESSION_COOKIE_SECURE=false`` boot unaffected.

        Dev compose serves HTTP and conftest.py forces false in test/CI.
        The fail-closed branch must NOT regress those paths.
        """
        monkeypatch.setenv("APP_ENV", env)
        monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")

        settings = Settings()

        assert settings.app_env == env
        assert settings.session_cookie_secure is False


class TestSessionCookieNameDefault:
    """Pin the ``__Host-`` secure-by-default contract on the cookie NAME.

    The Phase 0 deferral on the ``__Host-`` prefix was closed by flipping
    the default from ``"dprk_cti_session"`` to ``"__Host-dprk_cti_session"``.
    These tests pin the new default + the env override path so a future
    refactor cannot quietly regress production cookies to a non-prefixed
    name.

    Dev / test / CI continue overriding to the bare name explicitly via
    ``envs/api.env.example`` and ``services/api/tests/conftest.py``
    because the dev compose serves HTTP and the browser would reject
    ``__Host-`` cookies without the Secure flag (which dev does not
    set). The override path is exercised below.
    """

    def test_default_is_host_prefixed_when_env_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unset ``SESSION_COOKIE_NAME`` → default ``__Host-dprk_cti_session``."""
        monkeypatch.delenv("SESSION_COOKIE_NAME", raising=False)

        settings = Settings()

        assert settings.session_cookie_name == "__Host-dprk_cti_session"
        assert settings.session_cookie_name.startswith("__Host-")

    def test_env_override_to_bare_name_in_dev(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``SESSION_COOKIE_NAME=dprk_cti_session`` is the dev/CI HTTP override."""
        monkeypatch.setenv("SESSION_COOKIE_NAME", "dprk_cti_session")

        settings = Settings()

        assert settings.session_cookie_name == "dprk_cti_session"


class TestSessionCookieNameProdFailClosed:
    """Pin the ``app_env=='prod'`` fail-closed guard on the cookie NAME.

    Mirrors ``TestSessionCookieSecureProdFailClosed`` and the
    ``rate_limit_storage_url`` policy on the same Settings class: prod
    MUST refuse to boot if a critical security-default has been turned
    off. The default-flip closes the implicit-bare-name case; this
    validator closes the explicit-bare-name-in-prod case.
    """

    def test_prod_with_bare_name_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``APP_ENV=prod`` + ``SESSION_COOKIE_NAME=dprk_cti_session`` → boot fails."""
        monkeypatch.setenv("APP_ENV", "prod")
        monkeypatch.setenv("SESSION_COOKIE_NAME", "dprk_cti_session")
        # Satisfy the sibling SECURE validator so we isolate the
        # session_cookie_name failure path.
        monkeypatch.setenv("SESSION_COOKIE_SECURE", "true")

        with pytest.raises(ValidationError) as exc_info:
            Settings()

        assert "__Host-" in str(exc_info.value)
        assert "prod" in str(exc_info.value)

    def test_prod_with_host_prefix_boots(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``APP_ENV=prod`` + explicit ``__Host-`` prefix is accepted."""
        monkeypatch.setenv("APP_ENV", "prod")
        monkeypatch.setenv("SESSION_COOKIE_NAME", "__Host-custom_app_session")
        monkeypatch.setenv("SESSION_COOKIE_SECURE", "true")

        settings = Settings()

        assert settings.app_env == "prod"
        assert settings.session_cookie_name == "__Host-custom_app_session"

    def test_prod_with_name_unset_boots_via_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``APP_ENV=prod`` + unset env var → default ``__Host-`` → no fail."""
        monkeypatch.setenv("APP_ENV", "prod")
        monkeypatch.delenv("SESSION_COOKIE_NAME", raising=False)
        monkeypatch.setenv("SESSION_COOKIE_SECURE", "true")

        settings = Settings()

        assert settings.app_env == "prod"
        assert settings.session_cookie_name.startswith("__Host-")

    @pytest.mark.parametrize("env", ["dev", "test", "ci", "staging"])
    def test_non_prod_with_bare_name_boots(
        self, monkeypatch: pytest.MonkeyPatch, env: str
    ) -> None:
        """Non-prod envs with the bare cookie name boot unaffected.

        Dev / test / CI use the bare name because the browser rejects
        ``__Host-`` cookies served over HTTP (no Secure flag). The
        fail-closed branch must NOT regress those paths.
        """
        monkeypatch.setenv("APP_ENV", env)
        monkeypatch.setenv("SESSION_COOKIE_NAME", "dprk_cti_session")

        settings = Settings()

        assert settings.app_env == env
        assert settings.session_cookie_name == "dprk_cti_session"
