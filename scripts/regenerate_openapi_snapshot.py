"""Regenerate the committed OpenAPI snapshot from the live FastAPI app.

Writes ``contracts/openapi/openapi.json`` from ``app.openapi()``. Run
this whenever an API shape changes — new route, edited DTO, new/changed
response, example fix, description update — so the drift guard
(``services/api/tests/contract/test_openapi_snapshot.py``) stays in
sync with reality. The drift guard is compare-only; it never writes
back. A new schema only lands when a human runs this script and
commits the regenerated file.

Usage (from repo root):

    cd services/api && uv run python ../../scripts/regenerate_openapi_snapshot.py

The script is deliberately kept out of ``services/api/scripts/`` so
the same invocation pattern matches ``scripts/generate_bootstrap_fixture.py``
(worker fixture regen). Both live at repo root and are discovered by
editor tooling there.

Env vars
--------
Matches ``services/api/tests/conftest.py`` exactly. Critical because
both this script AND the drift test call ``app.openapi()`` — if they
use different env, they generate different specs and the drift test
flips red on CI for "drift" that is actually just env divergence.
Aligning on ``APP_ENV=test`` defaults guarantees reproducibility.

Note on dev-only ``/openapi.json`` route
---------------------------------------
``services/api/src/api/main.py`` sets ``openapi_url=None`` in non-dev
envs. That only removes the HTTP route serving the spec; ``app.openapi()``
as a Python method still returns the full spec regardless of env. The
snapshot therefore represents the full public contract surface, not a
dev-only subset. No conflict with the prod hardening posture.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


# Must match services/api/tests/conftest.py::_inject_env_vars so the
# regenerator and the drift test produce byte-identical specs.
_TEST_ENV: dict[str, str] = {
    "APP_ENV": "test",
    "DATABASE_URL": "postgresql+psycopg://test:test@localhost:5432/testdb",
    "REDIS_URL": "redis://localhost:6379/0",
    "OIDC_CLIENT_ID": "dprk-cti",
    "OIDC_CLIENT_SECRET": "test-oidc-secret",
    "OIDC_ISSUER_URL": "http://keycloak.test/realms/dprk",
    "OIDC_REDIRECT_BASE_URL": "http://localhost:8000",
    "SESSION_SIGNING_KEY": "test-signing-key-at-least-32-chars!",
    "SESSION_COOKIE_NAME": "dprk_cti_session",
    "SESSION_COOKIE_SECURE": "false",
    "SESSION_COOKIE_SAMESITE": "lax",
    "CORS_ORIGINS": "http://localhost:3000",
    "RATE_LIMIT_STORAGE_URL": "memory://",
}

for key, value in _TEST_ENV.items():
    os.environ.setdefault(key, value)

# Make ``from api.main import app`` resolve when invoked via
# ``uv run`` inside ``services/api`` — which adds ``src/`` to the path
# via the package install — but also when invoked from the repo root
# with the venv already activated.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_API_SRC = _REPO_ROOT / "services" / "api" / "src"
if str(_API_SRC) not in sys.path:
    sys.path.insert(0, str(_API_SRC))

# Clear any cached settings so the env vars above take effect even
# when get_settings has been memoized by an earlier import chain.
from api.config import get_settings  # noqa: E402

get_settings.cache_clear()

from api.main import app  # noqa: E402


def _canonical_json(spec: dict) -> str:
    """Canonical JSON — sorted keys, 2-space indent, trailing newline.

    Kept identical to the drift-test serializer so the comparison
    is a byte-exact match. Serialization drift between the two is
    the kind of bug that produces "drift found but the dicts look
    identical" confusion; eliminating it up front is cheap.
    """
    return json.dumps(spec, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> None:
    spec = app.openapi()
    out_path = _REPO_ROOT / "contracts" / "openapi" / "openapi.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = _canonical_json(spec)
    out_path.write_text(payload, encoding="utf-8")
    print(
        f"wrote {out_path.relative_to(_REPO_ROOT)} "
        f"({len(payload):,} bytes, "
        f"{len(spec.get('paths', {}))} paths)"
    )


if __name__ == "__main__":
    main()
