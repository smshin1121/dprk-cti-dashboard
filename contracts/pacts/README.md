# Pact consumer contracts

This directory holds consumer-driven contract (CDC) files produced by the
frontend (`apps/frontend`) using `pact-js`. The API (`services/api`) verifies
those contracts against its live surface via `pact-python`.

## Flow

```
apps/frontend  ─ pact-js ─▶  contracts/pacts/<consumer>-<provider>.json
                                        │
services/api   ─ pact-python ◀──────────┘   (verify)
```

1. FE writes consumer expectations in Pact-v3 JSON → emits a pact file.
2. FE commits the pact file into this directory.
3. The CI `contract-verify` job boots the API and runs `pact-python`'s
   `Verifier` against every `*.json` in this directory.

## Naming

`<consumer>-<provider>.json` — e.g. `frontend-dprk-cti-api.json`. Lowercase,
hyphen-separated. No suffix duplication (don't name it `.pact.json` —
pact-python accepts the bare `.json` extension).

## Baseline state (PR #11 Group I)

This directory currently ships only this `README.md` plus `.gitkeep`. The
verifier harness in `services/api/tests/contract/test_pact_producer.py`
enumerates `contracts/pacts/*.json` and **skips-with-ok** when the list is
empty. The CI `contract-verify` job is green as long as either:

- No consumer contract exists (skip)
- All contracts verify successfully (pass)

Once `apps/frontend` (PR #12) starts emitting a pact file, the harness
switches from skip-with-ok to live verification automatically — no code
change required in the harness itself, only the `pact-python` verifier call
gets activated.

## Why CDC here and not OpenAPI-only

- OpenAPI (`contracts/openapi/openapi.yaml`) catches **surface drift**:
  missing endpoint, missing status code, wrong request schema.
- Pact catches **consumer expectation drift**: FE expects field X in shape
  Y but BE returns it in shape Z. OpenAPI alone won't detect this when
  the schemas both happen to be valid superset/subset of each other.

The two are complementary. PR #11 ships the **producer side of Pact** so
FE (PR #12) can start writing consumer expectations on day 1 rather than
needing a BE round-trip.

## References

- Plan: `docs/plans/pr11-read-api-surface.md` §5.3, D7
- Pact spec v3: https://github.com/pact-foundation/pact-specification/tree/version-3
- pact-python verifier: https://docs.pact.io/implementation_guides/python
