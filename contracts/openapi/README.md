# OpenAPI contract

## Source of truth

`openapi.json` is the canonical snapshot of the API's OpenAPI 3.1 surface.
It is regenerated from the live FastAPI app (`services/api/src/api/main.py`
→ `app.openapi()`) and committed verbatim. The FastAPI app — routers,
DTOs, `responses={}` blocks, `Field(..., examples=[...])` — is the
source of truth; `openapi.json` is the drift-detectable artifact.

## Drift guard

CI runs `services/api/tests/contract/test_openapi_snapshot.py` in the
`contract-verify` job. The test calls `app.openapi()`, canonicalizes it
(sort_keys + 2-space indent + trailing newline), and does a byte-exact
comparison against `openapi.json`. Any drift — new endpoint, changed
response, edited example, renamed DTO field — fails the test with a
pinpointed error message and a regeneration command.

The test is **compare-only** — it never writes the snapshot. Updates
are always a deliberate developer action, so a consumer-breaking
change cannot silently self-heal through CI.

## Regenerating the snapshot

After any API shape change:

```bash
cd services/api && uv run python ../../scripts/regenerate_openapi_snapshot.py
```

Then review `git diff contracts/openapi/openapi.json`. If the diff
matches the intended API change, commit it alongside the code change.
If the diff contains unintended entries, revert and fix the source.

## Why a snapshot + not just OpenAPI YAML

- FastAPI generates the spec from code; a hand-written YAML would drift
  from reality the moment a developer adds a route without updating it.
- A snapshot caught by CI forces the regenerate-and-commit step to
  accompany the code change, keeping the contract artifact honest.
- The snapshot is consumable by frontend tooling (codegen, mocks,
  integration tests) that wants a static file to point at rather than
  hitting a running server for every build.

## Dev-only `/openapi.json` route

`services/api/src/api/main.py` sets `openapi_url=None` in non-dev
environments so an unauthenticated scraper cannot enumerate the surface
via `GET /openapi.json` in prod. This does not affect the committed
snapshot: `app.openapi()` as a Python method returns the full spec
regardless of env, and the regeneration script + drift test both use
the Python call — not the HTTP route.

## Legacy

`openapi.yaml` in this directory is a leftover placeholder from
pre-Phase-2 bootstrapping when the contract was hand-written. It is
**not authoritative**. The authoritative artifact is `openapi.json`.
`openapi.yaml` may be removed in a future cleanup PR once consumer
tooling finishes migrating.
