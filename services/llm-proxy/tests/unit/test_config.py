"""Unit tests for ``llm_proxy.config.Settings`` — PR #18 Group A.

Review criterion #1 pinned: ``APP_ENV=prod + provider=mock`` MUST
fail at Settings construction. The regression this catches is the
worst failure mode for this slice — mock emits deterministic-fake
1536-dim vectors that ingest cleanly into ``reports.embedding`` and
silently corrupt hybrid retrieval. Startup fail-closed is the only
safe posture.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from llm_proxy.config import Settings


# ---------------------------------------------------------------------------
# Criterion #1 — prod + provider=mock MUST startup-fail
# ---------------------------------------------------------------------------


class TestMockInProdStartupFail:
    """Draft v2 D3 Draft refinement — mock provider is test/dev-only."""

    def test_prod_plus_mock_raises_at_settings_init(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                app_env="prod",
                llm_proxy_embedding_provider="mock",
            )
        # Error message carries the load-bearing context so a sleepy
        # ops engineer reading the crash log knows why.
        message = str(exc_info.value)
        assert "mock" in message.lower()
        assert "prod" in message.lower()
        assert "refusing to start" in message.lower()

    @pytest.mark.parametrize("env", ["dev", "test"])
    def test_non_prod_with_mock_boots_cleanly(self, env: str) -> None:
        # The only provider that works without an API key, and the
        # only provider allowed outside prod — baseline for every
        # unit test after this.
        settings = Settings(
            app_env=env,
            llm_proxy_embedding_provider="mock",
        )
        assert settings.app_env == env
        assert settings.llm_proxy_embedding_provider == "mock"

    def test_prod_with_openai_and_key_boots_cleanly(self) -> None:
        # The blessed production configuration — confirms the
        # mock-in-prod guard doesn't collaterally break openai.
        settings = Settings(
            app_env="prod",
            llm_proxy_embedding_provider="openai",
            openai_api_key="sk-test-not-a-real-key",
        )
        assert settings.app_env == "prod"
        assert settings.llm_proxy_embedding_provider == "openai"


# ---------------------------------------------------------------------------
# D3 OpenAI-requires-key guard
# ---------------------------------------------------------------------------


class TestOpenaiRequiresKey:
    """provider=openai without an API key must fail at init."""

    @pytest.mark.parametrize("empty_key", ["", "   ", "\t\n"])
    def test_empty_key_raises(self, empty_key: str) -> None:
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                app_env="dev",
                llm_proxy_embedding_provider="openai",
                openai_api_key=empty_key,
            )
        message = str(exc_info.value)
        assert "openai" in message.lower()
        assert "openai_api_key" in message.lower()

    def test_present_key_boots(self) -> None:
        settings = Settings(
            app_env="dev",
            llm_proxy_embedding_provider="openai",
            openai_api_key="sk-test",
        )
        assert settings.openai_api_key == "sk-test"


# ---------------------------------------------------------------------------
# Field-level validators
# ---------------------------------------------------------------------------


class TestFieldValidators:
    """Timeout and batch bounds."""

    def test_timeout_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            Settings(
                app_env="dev",
                llm_proxy_embedding_provider="mock",
                llm_proxy_embedding_timeout_seconds=0,
            )
        with pytest.raises(ValidationError):
            Settings(
                app_env="dev",
                llm_proxy_embedding_provider="mock",
                llm_proxy_embedding_timeout_seconds=-1.0,
            )

    def test_max_batch_in_range(self) -> None:
        # 1 is the floor (a single-text batch is valid).
        Settings(
            app_env="dev",
            llm_proxy_embedding_provider="mock",
            llm_proxy_embedding_max_batch=1,
        )
        # 100 is the documented cap (defensive).
        Settings(
            app_env="dev",
            llm_proxy_embedding_provider="mock",
            llm_proxy_embedding_max_batch=100,
        )
        with pytest.raises(ValidationError):
            Settings(
                app_env="dev",
                llm_proxy_embedding_provider="mock",
                llm_proxy_embedding_max_batch=0,
            )
        with pytest.raises(ValidationError):
            Settings(
                app_env="dev",
                llm_proxy_embedding_provider="mock",
                llm_proxy_embedding_max_batch=101,
            )

    def test_provider_literal_rejects_arbitrary_strings(self) -> None:
        with pytest.raises(ValidationError):
            Settings(
                app_env="dev",
                llm_proxy_embedding_provider="anthropic",  # type: ignore[arg-type]
            )


# ---------------------------------------------------------------------------
# Default value contract
# ---------------------------------------------------------------------------


class TestDefaults:
    """Lock the default values that the PR plan D3 / D5 / D6 commit to."""

    def test_mock_default_provider_keeps_ci_offline(self) -> None:
        # Committed default in config.py. CI stays offline without
        # ever needing to set LLM_PROXY_EMBEDDING_PROVIDER.
        assert Settings(app_env="test").llm_proxy_embedding_provider == "mock"

    def test_default_model_is_1536_dim_model(self) -> None:
        # OpenAI's text-embedding-3-small defaults to 1536-dim,
        # matching reports.embedding vector(1536).
        assert (
            Settings(app_env="test").llm_proxy_embedding_model
            == "text-embedding-3-small"
        )

    def test_default_rate_limit_is_30_per_minute(self) -> None:
        # D5 Draft v2 commit — conservative default. Bumping is a
        # one-line env var change for ops.
        assert (
            Settings(app_env="test").llm_proxy_embedding_rate_limit
            == "30/minute"
        )

    def test_default_timeout_is_10_seconds(self) -> None:
        assert Settings(app_env="test").llm_proxy_embedding_timeout_seconds == 10.0

    def test_default_max_batch_is_16(self) -> None:
        # OI1 = A batch support; 16 matches the plan's request DTO.
        assert Settings(app_env="test").llm_proxy_embedding_max_batch == 16
