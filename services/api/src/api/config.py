import json
from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
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
    # TODO(P1.x): remove jwt_secret. Keycloak now issues + signs the JWT, the
    # API only ever verifies it via JWKS, so the platform no longer needs a
    # local symmetric secret. Kept for one release to avoid a breaking env
    # change.
    jwt_secret: str = Field(...)
    oidc_client_id: str = Field(...)
    oidc_client_secret: str = Field(...)
    oidc_issuer_url: str = Field(...)

    # Public base URL the API is reachable at — used to build the OIDC
    # callback URL we hand to Keycloak (e.g. http://localhost:8000).
    oidc_redirect_base_url: str = Field(...)

    # Session cookie + Redis-backed session store
    session_cookie_name: str = "dprk_cti_session"
    session_cookie_secure: bool = False
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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
