"""Regression test: ``infra/keycloak/realm-export.template.json`` carries no plaintext credentials.

Catches the silent-drift class where a contributor re-exports a modified
realm from a running Keycloak (per the README "Re-exporting a modified
realm" procedure) and forgets to re-introduce the
``__DPRK_DEV_USER_PASSWORD__`` / ``__DPRK_DEV_CLIENT_SECRET__``
placeholders — silently re-committing plaintext credentials.

The test enforces two invariants:

  1. The template contains both placeholder markers (so the render-time
     substitution still has something to find).
  2. The template contains NO known plaintext default value for either
     credential — the historical "test1234" user password and the
     "dev-secret-rotate-in-prod" client secret marker.

Per ``pattern_layer_boundary_lock_via_static_source`` (PR #47 / #48 / #49
lineage): the maintenance burden of "remember to re-placeholder after
admin-console export" is mechanized as a CI gate so it cannot silently
drift.

Path resolution: ``parents[4]`` from
``services/api/tests/unit/test_realm_export_template_no_plaintext.py`` is
the repo root; the template lives at
``infra/keycloak/realm-export.template.json``.

Known limitations (acceptable trade-offs):

  - The plaintext denylist is hardcoded. A future PR that introduces a
    new env-driven credential field (e.g., a per-user password override)
    must update both this test and the docker-compose ``sed`` pipeline
    in lockstep. The PR body should call this out.
  - The test only inspects the TEMPLATE, not the rendered output. A
    runtime render with `${DPRK_DEV_USER_PASSWORD}` set to an empty
    string would produce a Keycloak realm where users have empty
    passwords — but that is a deployment misconfiguration, not a
    committed-credential leak, and out of scope for the static-source
    gate.

The api service is the closest semantic owner of this test (OIDC
client config flows through the api Settings), and infrastructure tests
have no other natural home in the repo layout.
"""
from __future__ import annotations

from pathlib import Path

# Plaintext values that MUST never reappear in the committed template.
# Update in lockstep with `docker-compose.yml` `keycloak-init` substitution
# targets if new env-driven credentials are added.
_PLAINTEXT_DENYLIST: tuple[str, ...] = (
    "test1234",
    "dev-secret-rotate-in-prod",
)

# Placeholder markers that MUST appear in the committed template — they
# are what the `keycloak-init` `sed` pipeline substitutes against. Drift
# between these and the compose substitution targets would silently
# leave plaintext markers in the rendered realm-export.json.
_REQUIRED_PLACEHOLDERS: tuple[str, ...] = (
    "__DPRK_DEV_USER_PASSWORD__",
    "__DPRK_DEV_CLIENT_SECRET__",
)


def _realm_template() -> Path:
    """Locate ``infra/keycloak/realm-export.template.json``.

    Layout: ``<repo>/services/api/tests/unit/test_realm_export_template_no_plaintext.py``
    so ``parents[4]`` is ``<repo>``.
    """
    return (
        Path(__file__).resolve().parents[4]
        / "infra"
        / "keycloak"
        / "realm-export.template.json"
    )


def test_template_file_exists() -> None:
    """Sanity check the path resolution math still finds the template."""
    template = _realm_template()
    assert template.is_file(), (
        f"expected realm template at {template}; the relative-path math "
        f"in _realm_template() may be wrong if the repo was restructured."
    )


def test_template_contains_required_placeholders() -> None:
    """Both placeholder markers must be present.

    Without them the `keycloak-init` `sed` substitution has nothing to
    target — the rendered file would carry literal `__PLACEHOLDER__`
    strings as Keycloak credentials (test users could not log in,
    OIDC client auth would fail).
    """
    text = _realm_template().read_text(encoding="utf-8")
    missing = [p for p in _REQUIRED_PLACEHOLDERS if p not in text]
    assert not missing, (
        f"realm-export.template.json is missing required placeholder(s): {missing!r}. "
        f"The docker-compose `keycloak-init` sed pipeline depends on these "
        f"markers — without them the rendered import file carries the "
        f"verbatim placeholder string as a credential."
    )


def test_template_contains_no_plaintext_credentials() -> None:
    """Known plaintext default values must NEVER appear in the template.

    Fails when a contributor re-exports a modified realm from a running
    Keycloak (per README) and forgets to re-placeholder. Each entry on
    the denylist is the historical literal value that was committed
    before PR #50 closed this gap.
    """
    text = _realm_template().read_text(encoding="utf-8")
    leaked = [s for s in _PLAINTEXT_DENYLIST if s in text]
    assert not leaked, (
        f"realm-export.template.json contains plaintext credential(s) that "
        f"belong in the env-driven render path, not in version control: "
        f"{leaked!r}. Replace each with the corresponding "
        f"__DPRK_DEV_*__ placeholder and set the value via env var in "
        f"the repo-root `.env` (or `.env.example` for defaults). "
        f"See infra/keycloak/README.md § 'How the render works'."
    )
