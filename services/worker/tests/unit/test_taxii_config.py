"""Tests for worker.ingest.taxii.config — TAXII collection catalog loader.

Follows the same pattern as test_ingest_config.py (PR #8 Group A).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from worker.ingest.taxii.config import (
    DEFAULT_STIX_TYPES,
    TaxiiCatalog,
    TaxiiCatalogError,
    TaxiiCollectionConfig,
    default_collections_path,
    load_collections,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
REAL_COLLECTIONS = REPO_ROOT / "data/dictionaries/taxii_collections.yml"


def _minimal_entry(**overrides: object) -> dict:
    """Return a minimal valid YAML entry, with optional overrides."""
    base: dict = {
        "slug": "test-collection",
        "display_name": "Test Collection",
        "server_url": "https://example.com",
        "api_root_path": "/taxii/",
        "collection_id": "test-col-1",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Happy path against the real committed taxii_collections.yml
# ---------------------------------------------------------------------------


def test_real_collections_loads_without_error() -> None:
    catalog = load_collections(REAL_COLLECTIONS)
    assert len(catalog) >= 3


def test_real_collections_all_have_unique_slugs() -> None:
    catalog = load_collections(REAL_COLLECTIONS)
    slugs = [c.slug for c in catalog.collections]
    assert len(slugs) == len(set(slugs))


def test_real_collections_unique_server_collection_pairs() -> None:
    catalog = load_collections(REAL_COLLECTIONS)
    pairs = [(c.server_url, c.collection_id) for c in catalog.collections]
    assert len(pairs) == len(set(pairs))


def test_real_collections_all_enabled() -> None:
    catalog = load_collections(REAL_COLLECTIONS)
    assert len(catalog.enabled) >= 1


def test_real_collections_stix_types_non_empty() -> None:
    catalog = load_collections(REAL_COLLECTIONS)
    for col in catalog.collections:
        assert len(col.stix_types) >= 1


def test_real_collections_poll_interval_positive() -> None:
    catalog = load_collections(REAL_COLLECTIONS)
    for col in catalog.collections:
        assert col.poll_interval_minutes >= 1


def test_real_collections_max_pages_positive() -> None:
    catalog = load_collections(REAL_COLLECTIONS)
    for col in catalog.collections:
        assert col.max_pages >= 1


def test_real_collections_objects_url_format() -> None:
    catalog = load_collections(REAL_COLLECTIONS)
    for col in catalog.collections:
        url = col.objects_url
        assert url.startswith("https://")
        assert "/collections/" in url
        assert url.endswith("/objects/")


# ---------------------------------------------------------------------------
# TaxiiCollectionConfig pydantic model — valid entries
# ---------------------------------------------------------------------------


def test_config_accepts_valid_entry() -> None:
    cfg = TaxiiCollectionConfig(**_minimal_entry())
    assert cfg.slug == "test-collection"
    assert cfg.auth_type == "none"
    assert cfg.stix_types == DEFAULT_STIX_TYPES
    assert cfg.enabled is True
    assert cfg.poll_interval_minutes == 30
    assert cfg.max_pages == 100


def test_config_objects_url() -> None:
    cfg = TaxiiCollectionConfig(**_minimal_entry(
        server_url="https://cti-taxii.mitre.org",
        api_root_path="/stix/",
        collection_id="enterprise-attack",
    ))
    assert cfg.objects_url == (
        "https://cti-taxii.mitre.org/stix/collections/"
        "enterprise-attack/objects/"
    )


def test_config_objects_url_strips_trailing_slash() -> None:
    cfg = TaxiiCollectionConfig(**_minimal_entry(
        server_url="https://example.com/",
        api_root_path="/api/v1/",
    ))
    # server_url trailing slash stripped by validator
    assert cfg.objects_url.startswith("https://example.com/api/v1/")


def test_config_disabled_collection() -> None:
    cfg = TaxiiCollectionConfig(**_minimal_entry(enabled=False))
    assert cfg.enabled is False


def test_config_custom_stix_types() -> None:
    cfg = TaxiiCollectionConfig(**_minimal_entry(
        stix_types=["intrusion-set", "malware"]
    ))
    assert cfg.stix_types == ["intrusion-set", "malware"]


def test_config_custom_max_pages() -> None:
    cfg = TaxiiCollectionConfig(**_minimal_entry(max_pages=50))
    assert cfg.max_pages == 50


# ---------------------------------------------------------------------------
# TaxiiCollectionConfig — auth validation (D1)
# ---------------------------------------------------------------------------


def test_config_auth_none_no_extra_fields() -> None:
    cfg = TaxiiCollectionConfig(**_minimal_entry(auth_type="none"))
    assert cfg.resolve_auth_headers() == {}


def test_config_auth_basic_valid() -> None:
    cfg = TaxiiCollectionConfig(**_minimal_entry(
        auth_type="basic",
        username="user1",
        password_env="TEST_TAXII_PASSWORD",
    ))
    assert cfg.auth_type == "basic"
    assert cfg.username == "user1"
    assert cfg.password_env == "TEST_TAXII_PASSWORD"


def test_config_auth_basic_missing_username() -> None:
    with pytest.raises(Exception, match="username"):
        TaxiiCollectionConfig(**_minimal_entry(
            auth_type="basic",
            password_env="TEST_TAXII_PASSWORD",
        ))


def test_config_auth_basic_missing_password_env() -> None:
    with pytest.raises(Exception, match="password_env"):
        TaxiiCollectionConfig(**_minimal_entry(
            auth_type="basic",
            username="user1",
        ))


def test_config_auth_header_api_key_valid() -> None:
    cfg = TaxiiCollectionConfig(**_minimal_entry(
        auth_type="header_api_key",
        auth_header_name="X-Api-Key",
        auth_header_value_env="TEST_TAXII_API_KEY",
    ))
    assert cfg.auth_type == "header_api_key"
    assert cfg.auth_header_name == "X-Api-Key"


def test_config_auth_header_api_key_missing_header_name() -> None:
    with pytest.raises(Exception, match="auth_header_name"):
        TaxiiCollectionConfig(**_minimal_entry(
            auth_type="header_api_key",
            auth_header_value_env="TEST_KEY",
        ))


def test_config_auth_header_api_key_missing_value_env() -> None:
    with pytest.raises(Exception, match="auth_header_value_env"):
        TaxiiCollectionConfig(**_minimal_entry(
            auth_type="header_api_key",
            auth_header_name="X-Api-Key",
        ))


def test_config_auth_invalid_type() -> None:
    with pytest.raises(Exception):
        TaxiiCollectionConfig(**_minimal_entry(auth_type="oauth"))


# ---------------------------------------------------------------------------
# resolve_auth_headers — runtime env var resolution
# ---------------------------------------------------------------------------


def test_resolve_basic_auth_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_PASSWORD", "secret123")
    cfg = TaxiiCollectionConfig(**_minimal_entry(
        auth_type="basic",
        username="admin",
        password_env="MY_PASSWORD",
    ))
    headers = cfg.resolve_auth_headers()
    assert "Authorization" in headers
    assert headers["Authorization"].startswith("Basic ")


def test_resolve_basic_auth_missing_env_raises() -> None:
    env_var = "NONEXISTENT_VAR_FOR_TEST_12345"
    if env_var in os.environ:
        del os.environ[env_var]
    cfg = TaxiiCollectionConfig(**_minimal_entry(
        auth_type="basic",
        username="admin",
        password_env=env_var,
    ))
    with pytest.raises(TaxiiCatalogError, match=env_var):
        cfg.resolve_auth_headers()


def test_resolve_header_api_key_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MY_API_KEY", "key-abc-123")
    cfg = TaxiiCollectionConfig(**_minimal_entry(
        auth_type="header_api_key",
        auth_header_name="X-Api-Key",
        auth_header_value_env="MY_API_KEY",
    ))
    headers = cfg.resolve_auth_headers()
    assert headers == {"X-Api-Key": "key-abc-123"}


def test_resolve_header_api_key_missing_env_raises() -> None:
    env_var = "NONEXISTENT_API_KEY_FOR_TEST_67890"
    if env_var in os.environ:
        del os.environ[env_var]
    cfg = TaxiiCollectionConfig(**_minimal_entry(
        auth_type="header_api_key",
        auth_header_name="X-Api-Key",
        auth_header_value_env=env_var,
    ))
    with pytest.raises(TaxiiCatalogError, match=env_var):
        cfg.resolve_auth_headers()


# ---------------------------------------------------------------------------
# TaxiiCollectionConfig — field validation
# ---------------------------------------------------------------------------


def test_config_rejects_blank_slug() -> None:
    with pytest.raises(Exception, match="slug"):
        TaxiiCollectionConfig(**_minimal_entry(slug="  "))


def test_config_rejects_uppercase_slug() -> None:
    with pytest.raises(Exception, match="slug"):
        TaxiiCollectionConfig(**_minimal_entry(slug="MITRE-Enterprise"))


def test_config_rejects_blank_display_name() -> None:
    with pytest.raises(Exception, match="display_name"):
        TaxiiCollectionConfig(**_minimal_entry(display_name="  "))


def test_config_rejects_non_https_server_url() -> None:
    with pytest.raises(Exception, match="server_url"):
        TaxiiCollectionConfig(**_minimal_entry(server_url="ftp://bad.com"))


def test_config_rejects_http_server_url() -> None:
    """P1 Codex R1: plain http rejected to prevent credential leak."""
    with pytest.raises(Exception, match="https"):
        TaxiiCollectionConfig(**_minimal_entry(server_url="http://insecure.com"))


def test_config_rejects_blank_server_url() -> None:
    with pytest.raises(Exception, match="server_url"):
        TaxiiCollectionConfig(**_minimal_entry(server_url=""))


def test_config_rejects_api_root_without_leading_slash() -> None:
    with pytest.raises(Exception, match="api_root_path"):
        TaxiiCollectionConfig(**_minimal_entry(api_root_path="stix/"))


def test_config_rejects_blank_collection_id() -> None:
    with pytest.raises(Exception, match="collection_id"):
        TaxiiCollectionConfig(**_minimal_entry(collection_id="  "))


def test_config_rejects_empty_stix_types() -> None:
    with pytest.raises(Exception, match="stix_types"):
        TaxiiCollectionConfig(**_minimal_entry(stix_types=[]))


def test_config_rejects_zero_poll_interval() -> None:
    with pytest.raises(Exception):
        TaxiiCollectionConfig(**_minimal_entry(poll_interval_minutes=0))


def test_config_rejects_zero_max_pages() -> None:
    with pytest.raises(Exception):
        TaxiiCollectionConfig(**_minimal_entry(max_pages=0))


# ---------------------------------------------------------------------------
# TaxiiCatalog — enabled filter
# ---------------------------------------------------------------------------


def test_catalog_enabled_filter() -> None:
    cols = (
        TaxiiCollectionConfig(**_minimal_entry(
            slug="a", collection_id="col-a", enabled=True,
        )),
        TaxiiCollectionConfig(**_minimal_entry(
            slug="b", collection_id="col-b", enabled=False,
        )),
        TaxiiCollectionConfig(**_minimal_entry(
            slug="c", collection_id="col-c", enabled=True,
        )),
    )
    catalog = TaxiiCatalog(collections=cols)
    assert len(catalog) == 3
    assert len(catalog.enabled) == 2
    assert all(c.enabled for c in catalog.enabled)


# ---------------------------------------------------------------------------
# Loader failure modes
# ---------------------------------------------------------------------------


def test_load_empty_file(tmp_path: Path) -> None:
    p = tmp_path / "empty.yml"
    p.write_text("", encoding="utf-8")
    with pytest.raises(TaxiiCatalogError, match="empty"):
        load_collections(p)


def test_load_non_list_top_level(tmp_path: Path) -> None:
    p = tmp_path / "bad.yml"
    p.write_text("collections:\n  - slug: x\n", encoding="utf-8")
    with pytest.raises(TaxiiCatalogError, match="list"):
        load_collections(p)


def test_load_non_mapping_entry(tmp_path: Path) -> None:
    p = tmp_path / "bad.yml"
    p.write_text("- just a string\n", encoding="utf-8")
    with pytest.raises(TaxiiCatalogError, match="mapping"):
        load_collections(p)


def test_load_missing_required_field(tmp_path: Path) -> None:
    entries = [{"slug": "x", "display_name": "X"}]
    p = tmp_path / "missing.yml"
    p.write_text(yaml.dump(entries), encoding="utf-8")
    with pytest.raises(TaxiiCatalogError, match="Field required"):
        load_collections(p)


def test_load_duplicate_slug(tmp_path: Path) -> None:
    entries = [
        _minimal_entry(slug="dup", collection_id="col-a"),
        _minimal_entry(slug="dup", collection_id="col-b"),
    ]
    p = tmp_path / "dup_slug.yml"
    p.write_text(yaml.dump(entries), encoding="utf-8")
    with pytest.raises(TaxiiCatalogError, match="duplicate slug"):
        load_collections(p)


def test_load_duplicate_server_collection_pair(tmp_path: Path) -> None:
    entries = [
        _minimal_entry(
            slug="a",
            server_url="https://same.com",
            collection_id="same-col",
        ),
        _minimal_entry(
            slug="b",
            server_url="https://same.com",
            collection_id="same-col",
        ),
    ]
    p = tmp_path / "dup_endpoint.yml"
    p.write_text(yaml.dump(entries), encoding="utf-8")
    with pytest.raises(TaxiiCatalogError, match="duplicate"):
        load_collections(p)


def test_load_different_server_same_collection_id_ok(tmp_path: Path) -> None:
    """Same collection_id on different servers is allowed."""
    entries = [
        _minimal_entry(
            slug="a",
            server_url="https://server-a.com",
            collection_id="shared-col",
        ),
        _minimal_entry(
            slug="b",
            server_url="https://server-b.com",
            collection_id="shared-col",
        ),
    ]
    p = tmp_path / "ok.yml"
    p.write_text(yaml.dump(entries), encoding="utf-8")
    catalog = load_collections(p)
    assert len(catalog) == 2


def test_load_malformed_yaml(tmp_path: Path) -> None:
    p = tmp_path / "bad.yml"
    p.write_text("- slug: x\n  url: [broken\n", encoding="utf-8")
    with pytest.raises(TaxiiCatalogError, match="invalid YAML"):
        load_collections(p)


# ---------------------------------------------------------------------------
# Default path resolution
# ---------------------------------------------------------------------------


def test_default_collections_path_resolves_to_existing_file() -> None:
    p = default_collections_path()
    assert p.exists(), f"default collections path {p} does not exist"
    assert p.name == "taxii_collections.yml"


def test_default_collections_path_loadable() -> None:
    catalog = load_collections(default_collections_path())
    assert len(catalog) >= 1
