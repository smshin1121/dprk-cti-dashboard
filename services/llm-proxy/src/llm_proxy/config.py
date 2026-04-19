"""llm-proxy settings — PR #18 Group A (plan D3 Draft v2).

Single ``Settings`` class loading every env var the service needs.
Fail-closed at startup when configuration is structurally unsafe:

- ``provider=openai`` with empty ``OPENAI_API_KEY`` → refuse to boot.
- ``provider=mock`` with ``APP_ENV=prod`` → refuse to boot. Mock
  emits deterministic-fake 1536-dim vectors that would ingest
  cleanly into ``reports.embedding`` and silently corrupt hybrid
  retrieval. A hard 503 is strictly less dangerous than that
  silent corruption, so we block it before any request arrives.

Unit-test-friendly: ``Settings`` can be instantiated directly with
keyword overrides — tests do not need to mutate process env.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ProviderName = Literal["openai", "mock"]
AppEnv = Literal["dev", "test", "prod"]


class Settings(BaseSettings):
    """Runtime configuration for the llm-proxy service."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # Align with services/api: field names map to UPPER_SNAKE env
        # vars verbatim (pydantic-settings default behavior).
    )

    app_env: AppEnv = Field(default="dev", description="Deployment environment.")

    # Existing X-Internal-Token guard — already consumed by
    # main.py::require_internal_token. Surfaced here for parity so
    # test harnesses can pass an explicit value.
    llm_proxy_internal_token: str = Field(
        default="",
        description=(
            "Shared secret clients send as `X-Internal-Token`. Empty "
            "means the middleware returns 503 on every non-health "
            "request (fail-closed)."
        ),
    )

    # D3 core config.
    llm_proxy_embedding_provider: ProviderName = Field(
        default="mock",
        description=(
            "Embedding provider implementation. `openai` hits "
            "api.openai.com; `mock` returns deterministic "
            "sha256-derived 1536-dim vectors (dev / test / CI only)."
        ),
    )
    llm_proxy_embedding_model: str = Field(
        default="text-embedding-3-small",
        description=(
            "Default embedding model name. Callers may override "
            "per-request; the chosen value appears in the cache key "
            "so switching models opens a fresh cache space."
        ),
    )
    llm_proxy_embedding_timeout_seconds: float = Field(
        default=10.0,
        gt=0,
        description="Per-request upstream timeout (seconds).",
    )
    llm_proxy_embedding_max_batch: int = Field(
        default=16,
        ge=1,
        le=100,
        description="Defensive cap on batch size per request.",
    )

    # OpenAI-specific — only required when provider=openai. Root
    # validator below enforces presence.
    openai_api_key: str = Field(
        default="",
        description="OpenAI API key. Required when provider=openai.",
    )

    # Redis — shared between D6 embedding cache AND D5 slowapi storage.
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description=(
            "Redis connection URL. Same Redis is used for the "
            "embedding cache (D6) and the rate-limit bucket "
            "storage (D5). Two logical keyspaces, one connection."
        ),
    )

    # D5 rate limit — one knob so ops can loosen / tighten without a
    # code change. Default 30/minute per the PR #18 plan lock.
    llm_proxy_embedding_rate_limit: str = Field(
        default="30/minute",
        description=(
            "slowapi rate-limit expression applied to "
            "POST /api/v1/embedding. Per X-Internal-Token principal."
        ),
    )

    # ------------------------------------------------------------------
    # Validators
    # ------------------------------------------------------------------

    @model_validator(mode="after")
    def _openai_requires_key(self) -> "Settings":
        """D3: provider=openai MUST carry a non-empty OPENAI_API_KEY."""
        if (
            self.llm_proxy_embedding_provider == "openai"
            and not self.openai_api_key.strip()
        ):
            raise ValueError(
                "LLM_PROXY_EMBEDDING_PROVIDER=openai requires "
                "OPENAI_API_KEY to be set. Refusing to start."
            )
        return self

    @model_validator(mode="after")
    def _mock_forbidden_in_prod(self) -> "Settings":
        """D3 Draft v2: mock provider MUST NOT serve prod traffic.

        Deterministic-fake vectors would ingest cleanly into the
        `reports.embedding` column and silently corrupt hybrid
        retrieval. Startup fail-closed is the only safe posture.
        """
        if (
            self.llm_proxy_embedding_provider == "mock"
            and self.app_env == "prod"
        ):
            raise ValueError(
                "LLM_PROXY_EMBEDDING_PROVIDER=mock is forbidden "
                "when APP_ENV=prod. The mock provider emits "
                "deterministic-fake 1536-dim vectors that would "
                "silently corrupt production embedding data. "
                "Refusing to start."
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide ``Settings`` singleton.

    Test code should not use this; instantiate ``Settings(...)``
    directly with explicit kwargs to isolate each test from the env.
    """
    return Settings()
