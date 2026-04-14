import json
from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Non-sensitive — defaults are fine
    app_name: str = "dprk-cti-api"
    app_env: str = "dev"
    # `NoDecode` disables pydantic-settings' default JSON-decode of complex
    # env values so the validator below can accept the ergonomic
    # comma-separated form without a `SettingsError`.
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, v: object) -> list[str]:
        """Accept comma-separated string, JSON array, or list.

        Env-var form `CORS_ORIGINS=http://a.com,http://b.com` is supported in
        addition to JSON (`["http://a.com","http://b.com"]`).
        """
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
        raise ValueError(f"Unsupported cors_origins value: {type(v).__name__}")

    # CRITICAL: no fallback values — startup fails if these are absent from env
    database_url: str = Field(...)
    redis_url: str = Field(...)
    jwt_secret: str = Field(...)
    oidc_client_id: str = Field(...)
    oidc_client_secret: str = Field(...)
    oidc_issuer_url: str = Field(...)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


# Convenience alias so existing `from .config import settings` callers still work.
# Do not use this alias in new code; call get_settings() directly.
settings = get_settings()
