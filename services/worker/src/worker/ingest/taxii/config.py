"""TAXII collection catalog loader with bijection lint and auth validation.

Loads ``data/dictionaries/taxii_collections.yml`` and validates structural
invariants at load time. Pattern follows ``worker.ingest.config.load_feeds``.

Resolution order for the default path:
  1. Repo checkout — ``<repo>/data/dictionaries/taxii_collections.yml``.
  2. Packaged wheel — ``worker/ingest/taxii/data/taxii_collections.yml``
     (force-included via hatch).

Auth schema (per D1):
  auth_type = "none"           — no auth headers sent.
  auth_type = "basic"          — HTTP Basic; requires username + password_env.
  auth_type = "header_api_key" — custom header; requires auth_header_name
                                  + auth_header_value_env.
  Secrets are NEVER stored as plaintext — only env var names.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator


__all__ = [
    "TaxiiCatalogError",
    "TaxiiCollectionConfig",
    "TaxiiCatalog",
    "load_collections",
    "default_collections_path",
    "DEFAULT_STIX_TYPES",
]


_PACKAGE_DIR = Path(__file__).resolve().parent

DEFAULT_STIX_TYPES: list[str] = [
    "intrusion-set",
    "malware",
    "attack-pattern",
    "tool",
    "campaign",
    "indicator",
]


class TaxiiCatalogError(ValueError):
    """Raised when the YAML catalog violates a load-time invariant."""


_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class TaxiiCollectionConfig(BaseModel, frozen=True):
    """Single TAXII collection entry from ``taxii_collections.yml``."""

    slug: str
    display_name: str
    server_url: str
    api_root_path: str
    collection_id: str

    # Auth — D1
    auth_type: Literal["none", "basic", "header_api_key"] = "none"
    username: str | None = None
    password_env: str | None = None
    auth_header_name: str | None = None
    auth_header_value_env: str | None = None

    # STIX type filter — B
    stix_types: list[str] = Field(default_factory=lambda: list(DEFAULT_STIX_TYPES))

    enabled: bool = True
    poll_interval_minutes: int = 30
    max_pages: int = 100

    @field_validator("slug")
    @classmethod
    def _slug_format(cls, v: str) -> str:
        v = v.strip()
        if not _SLUG_RE.match(v):
            raise ValueError(
                "slug must be lowercase, hyphen-separated alphanumeric "
                f"(e.g. 'mitre-enterprise-attack'), got {v!r}"
            )
        return v

    @field_validator("display_name")
    @classmethod
    def _display_name_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("display_name must be a non-empty string")
        return v

    @field_validator("server_url")
    @classmethod
    def _server_url_https(cls, v: str) -> str:
        v = v.strip().rstrip("/")
        parsed = urlparse(v)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError(
                f"server_url must be an absolute https URL, got {v!r}"
            )
        return v

    @field_validator("api_root_path")
    @classmethod
    def _api_root_path_starts_with_slash(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith("/"):
            raise ValueError(
                f"api_root_path must start with '/', got {v!r}"
            )
        return v

    @field_validator("collection_id")
    @classmethod
    def _collection_id_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("collection_id must be a non-empty string")
        return v

    @field_validator("stix_types")
    @classmethod
    def _stix_types_non_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("stix_types must contain at least one type")
        return v

    @field_validator("poll_interval_minutes")
    @classmethod
    def _poll_interval_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("poll_interval_minutes must be >= 1")
        return v

    @field_validator("max_pages")
    @classmethod
    def _max_pages_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("max_pages must be >= 1")
        return v

    @model_validator(mode="after")
    def _validate_auth_fields(self) -> TaxiiCollectionConfig:
        if self.auth_type == "basic":
            if not self.username:
                raise ValueError(
                    "auth_type='basic' requires 'username'"
                )
            if not self.password_env:
                raise ValueError(
                    "auth_type='basic' requires 'password_env' "
                    "(env var name holding the password)"
                )
        elif self.auth_type == "header_api_key":
            if not self.auth_header_name:
                raise ValueError(
                    "auth_type='header_api_key' requires 'auth_header_name'"
                )
            if not self.auth_header_value_env:
                raise ValueError(
                    "auth_type='header_api_key' requires "
                    "'auth_header_value_env' (env var name holding the value)"
                )
        return self

    @property
    def objects_url(self) -> str:
        """Full URL for fetching objects from this collection."""
        root = self.api_root_path.rstrip("/")
        return f"{self.server_url}{root}/collections/{self.collection_id}/objects/"

    def resolve_auth_headers(self) -> dict[str, str]:
        """Build auth headers by resolving env var references.

        Raises ``TaxiiCatalogError`` if referenced env vars are not set.
        """
        if self.auth_type == "none":
            return {}

        if self.auth_type == "basic":
            import base64

            password = os.environ.get(self.password_env or "")
            if password is None:
                raise TaxiiCatalogError(
                    f"env var {self.password_env!r} not set "
                    f"(required by collection {self.slug!r} auth_type=basic)"
                )
            credentials = base64.b64encode(
                f"{self.username}:{password}".encode()
            ).decode("ascii")
            return {"Authorization": f"Basic {credentials}"}

        if self.auth_type == "header_api_key":
            value = os.environ.get(self.auth_header_value_env or "")
            if value is None:
                raise TaxiiCatalogError(
                    f"env var {self.auth_header_value_env!r} not set "
                    f"(required by collection {self.slug!r} "
                    f"auth_type=header_api_key)"
                )
            return {self.auth_header_name or "": value}

        return {}


@dataclass(frozen=True, slots=True)
class TaxiiCatalog:
    """Validated, immutable catalog of TAXII collection configurations."""

    collections: tuple[TaxiiCollectionConfig, ...]

    @property
    def enabled(self) -> tuple[TaxiiCollectionConfig, ...]:
        return tuple(c for c in self.collections if c.enabled)

    def __len__(self) -> int:
        return len(self.collections)


def _validate_bijection(
    collections: Sequence[TaxiiCollectionConfig],
    source: Path,
) -> None:
    """Enforce unique slug and unique (server_url, collection_id)."""
    seen_slugs: dict[str, int] = {}
    seen_endpoints: dict[tuple[str, str], str] = {}

    for idx, col in enumerate(collections):
        if col.slug in seen_slugs:
            prev = seen_slugs[col.slug]
            raise TaxiiCatalogError(
                f"{source}: duplicate slug {col.slug!r} "
                f"at entries {prev} and {idx}"
            )
        seen_slugs[col.slug] = idx

        endpoint_key = (col.server_url, col.collection_id)
        if endpoint_key in seen_endpoints:
            owner = seen_endpoints[endpoint_key]
            raise TaxiiCatalogError(
                f"{source}: duplicate (server_url, collection_id) "
                f"({col.server_url!r}, {col.collection_id!r}) "
                f"claimed by slugs {owner!r} and {col.slug!r}"
            )
        seen_endpoints[endpoint_key] = col.slug


def load_collections(path: Path | str) -> TaxiiCatalog:
    """Load and validate the TAXII collection catalog at ``path``.

    Raises :class:`TaxiiCatalogError` on structural violations.
    """
    source = Path(path)
    with source.open("r", encoding="utf-8") as handle:
        try:
            raw = yaml.safe_load(handle)
        except yaml.YAMLError as exc:
            raise TaxiiCatalogError(
                f"{source}: invalid YAML — {exc}"
            ) from exc

    if raw is None:
        raise TaxiiCatalogError(f"{source}: file is empty")
    if not isinstance(raw, list):
        raise TaxiiCatalogError(
            f"{source}: top-level YAML must be a list of collection entries"
        )

    collections: list[TaxiiCollectionConfig] = []
    for idx, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise TaxiiCatalogError(
                f"{source}: entry {idx} must be a mapping, "
                f"got {type(entry).__name__}"
            )
        try:
            collections.append(TaxiiCollectionConfig(**entry))
        except Exception as exc:
            raise TaxiiCatalogError(
                f"{source}: entry {idx} "
                f"(slug={entry.get('slug', '?')}): {exc}"
            ) from exc

    _validate_bijection(collections, source)

    # P2 Codex R5: validate that auth env vars exist at load time so
    # misconfiguration is caught early, not during a scheduled fetch.
    # P3 Codex R6: skip disabled collections — they are never polled.
    for col in collections:
        if col.enabled and col.auth_type != "none":
            try:
                col.resolve_auth_headers()
            except TaxiiCatalogError:
                raise  # re-raise with the descriptive message

    return TaxiiCatalog(collections=tuple(collections))


def default_collections_path() -> Path:
    """Resolve the default TAXII collection catalog path.

    Resolution order: repo checkout -> packaged wheel data.
    Same dual-resolution pattern as ``worker.ingest.config.default_feeds_path``.
    """
    # _PACKAGE_DIR = .../services/worker/src/worker/ingest/taxii/
    # parents[5] = repo root
    checkout_candidate = (
        _PACKAGE_DIR.parents[5] / "data/dictionaries/taxii_collections.yml"
    )
    if checkout_candidate.exists():
        return checkout_candidate
    return _PACKAGE_DIR / "data/taxii_collections.yml"
