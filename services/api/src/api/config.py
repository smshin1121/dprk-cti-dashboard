import json
from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def _parse_str_list(v: object, field_name: str) -> list[str]:
    """Accept comma-separated string, JSON array, or list."""
    if v is None or v == "":
        return []
    if isinstance(v, list):
        return [str(s).strip() for s in v if str(s).strip()]
    if isinstance(v, str):
        s = v.strip()
        if s.startswith("["):
            parsed = json.loads(s)
            return [str(x).strip() for x in parsed if str(x).strip()]
        return [part.strip() for part in s.split(",") if part.strip()]
    raise ValueError(f"Unsupported {field_name} value: {type(v).__name__}")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Non-sensitive — defaults are fine
    app_name: str = "dprk-cti-api"
    app_env: str = "dev"
    # `NoDecode` disables pydantic-settings' default JSON-decode of complex
    # env values so the validator below can accept the ergonomic
    # comma-separated form without a `SettingsError`.
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    # Additional trusted JWT ``iss`` values accepted during token verification.
    # Useful when the discovery ``issuer`` value differs from the public-facing
    # hostname Keycloak stamps into tokens (e.g., reverse proxies / test envs).
    oidc_trusted_issuers: Annotated[list[str], NoDecode] = Field(default_factory=list)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, v: object) -> list[str]:
        """Accept comma-separated string, JSON array, or list.

        Env-var form `CORS_ORIGINS=http://a.com,http://b.com` is supported in
        addition to JSON (`["http://a.com","http://b.com"]`).
        """
        return _parse_str_list(v, "cors_origins")

    @field_validator("oidc_trusted_issuers", mode="before")
    @classmethod
    def _parse_trusted_issuers(cls, v: object) -> list[str]:
        """Same parsing rules as ``cors_origins`` for trusted issuer list."""
        return _parse_str_list(v, "oidc_trusted_issuers")

    # CRITICAL: no fallback values — startup fails if these are absent from env
    database_url: str = Field(...)
    redis_url: str = Field(...)
    oidc_client_id: str = Field(...)
    oidc_client_secret: str = Field(...)
    oidc_issuer_url: str = Field(...)

    # Public base URL the API is reachable at — used to build the OIDC
    # callback URL we hand to Keycloak (e.g. http://localhost:8000).
    oidc_redirect_base_url: str = Field(...)

    # Session cookie + Redis-backed session store.
    #
    # `session_cookie_secure` defaults to True so production deployments
    # that don't explicitly set the env var still get the secure-by-default
    # `Secure` cookie attribute (browser only sends the cookie over HTTPS).
    # Dev/CI explicitly override to False via envs/api.env.example +
    # services/api/tests/conftest.py because the dev compose serves HTTP.
    #
    # `session_cookie_name` defaults to the ``__Host-`` prefixed form,
    # which the browser enforces as: must have Secure attribute, must
    # have Path=/, must NOT have Domain attribute. The session helpers
    # (``set_session_cookie`` / ``clear_session_cookie``) already meet
    # these requirements unconditionally, so the prefix is a strict
    # tightening at the browser layer with no server-side change. Dev
    # serves HTTP so it cannot satisfy the browser's Secure check —
    # envs/api.env.example + conftest.py override to the bare name for
    # local development. The ``_enforce_session_cookie_host_prefix_in_prod``
    # validator below mirrors ``_enforce_session_cookie_secure_in_prod``:
    # prod refuses to boot if the override drops the prefix.
    session_cookie_name: str = "__Host-dprk_cti_session"
    session_cookie_secure: bool = True
    session_cookie_samesite: str = "lax"
    session_signing_key: str = Field(...)
    session_ttl_seconds: int = 3600

    # Rate-limit storage (plan D1). PR #11 Group F locks the
    # environment policy:
    #   - prod:  required to start with ``redis://`` (fail-closed; any
    #            other scheme raises at startup)
    #   - test:  forced to ``memory://`` so fakeredis is not needed and
    #            slowapi's built-in in-process storage gives
    #            deterministic window semantics
    #   - dev:   honors the env value. If empty, reuses ``redis_url``
    #            so the dev Redis session store serves double duty.
    # Enforcement lives in ``api.rate_limit.build_limiter`` so the
    # policy holds regardless of how ``Settings()`` is constructed.
    rate_limit_enabled: bool = True
    rate_limit_storage_url: str = ""

    # PR #19a Group B — llm-proxy embedding client config.
    # Both empty means: embedding disabled. The promote route will
    # skip the embed step entirely (see api.deps.get_embedding_client)
    # and ingest/promote UX is unaffected. Populating BOTH activates
    # the embed-on-ingest pathway added in PR #19a.
    # Token is read from env only — never logged or echoed.
    llm_proxy_url: str = ""
    llm_proxy_internal_token: str = ""
    llm_proxy_embedding_timeout_seconds: float = 10.0

    # PR #19b Group A — hybrid-search knobs.
    # Coverage threshold: if ``reports.embedding`` population ratio
    # drops below this, /search degrades to FTS-only (plan D5(b)).
    # Bounded to [0.0, 1.0]. Default 0.5 per plan.
    hybrid_search_coverage_threshold: float = 0.5
    # Vector kNN candidate set size — LIMIT on the vector rank list
    # before RRF fusion (plan D2 / OI1 = B). Must be >= 1.
    hybrid_search_vector_k: int = 50
    # Process-local coverage cache refresh interval in seconds
    # (plan D5 / OI4 = B). Must be >= 1 — zero would force a
    # per-request recompute, defeating the cache's purpose.
    hybrid_search_coverage_refresh_seconds: int = 600

    @field_validator("hybrid_search_coverage_threshold")
    @classmethod
    def _validate_coverage_threshold(cls, v: float) -> float:
        """Reject out-of-[0.0, 1.0] coverage threshold (plan D5 bound)."""
        if not 0.0 <= v <= 1.0:
            raise ValueError(
                f"hybrid_search_coverage_threshold must be in [0.0, 1.0], "
                f"got {v}"
            )
        return v

    @field_validator("hybrid_search_vector_k")
    @classmethod
    def _validate_vector_k(cls, v: int) -> int:
        """Reject non-positive vector_k (plan D2 / OI1 = B bound)."""
        if v < 1:
            raise ValueError(
                f"hybrid_search_vector_k must be >= 1, got {v}"
            )
        return v

    @field_validator("hybrid_search_coverage_refresh_seconds")
    @classmethod
    def _validate_refresh_seconds(cls, v: int) -> int:
        """Reject non-positive refresh interval (plan D5 / OI4 = B bound)."""
        if v < 1:
            raise ValueError(
                f"hybrid_search_coverage_refresh_seconds must be >= 1, "
                f"got {v}"
            )
        return v

    @model_validator(mode="after")
    def _enforce_session_cookie_host_prefix_in_prod(self) -> "Settings":
        """Fail-closed when prod ships the session cookie without ``__Host-``.

        Mirrors ``_enforce_session_cookie_secure_in_prod``. Browser-side
        enforcement of the ``__Host-`` prefix ensures the cookie is
        scoped to exactly this host (no Domain attribute), at the root
        path, and only sent over HTTPS — closing
        cookie-fixation / subdomain-injection vectors that
        ``Secure=True`` alone does not. Dev / test / CI / staging are
        unaffected — only ``app_env=="prod"`` triggers the fail-closed
        branch.
        """
        if self.app_env == "prod" and not self.session_cookie_name.startswith(
            "__Host-"
        ):
            raise ValueError(
                "session_cookie_name must start with '__Host-' when "
                "app_env='prod'. The __Host- prefix forces browser-side "
                "checks (Secure, Path=/, no Domain) that close "
                "cookie-fixation and subdomain-injection vectors. Either "
                "leave SESSION_COOKIE_NAME unset (default "
                "'__Host-dprk_cti_session') or set it to a value that "
                "starts with '__Host-'."
            )
        return self

    @model_validator(mode="after")
    def _enforce_session_cookie_secure_in_prod(self) -> "Settings":
        """Fail-closed when prod ships session cookies without ``Secure``.

        Mirrors the ``rate_limit_storage_url`` policy on this same Settings
        class: ``app_env=="prod"`` MUST refuse to boot if a critical
        security-default has been turned off. The Phase 0 deferral that
        flipped the field default to ``True`` covers operators who never
        set the env var; this validator covers the remaining case where
        an operator explicitly sets ``SESSION_COOKIE_SECURE=false`` in
        prod (e.g. via a stale config copied from dev).

        Dev / test / CI / staging are unaffected — only ``app_env=="prod"``
        triggers the fail-closed branch.
        """
        if self.app_env == "prod" and not self.session_cookie_secure:
            raise ValueError(
                "session_cookie_secure must be True when app_env='prod'. "
                "Setting SESSION_COOKIE_SECURE=false in production would "
                "issue session cookies without the Secure attribute, "
                "exposing them to network interception over HTTP. Either "
                "leave SESSION_COOKIE_SECURE unset (default True) or set "
                "it to true."
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
