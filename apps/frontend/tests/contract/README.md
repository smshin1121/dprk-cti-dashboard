# Pact consumer tests

Consumer-driven contract tests using `pact-js` (V3 / FFI). Each
`*.pact.test.ts` here writes to `contracts/pacts/<consumer>-<provider>.json`
at the repo root, which the BE `contract-verify` job verifies via
`pact-python` against a live uvicorn process.

## Run

```bash
pnpm test:contract     # apps/frontend
```

## Coverage (PR #12 — plan D8 lock)

| Endpoint                          | Interactions                          |
|:----------------------------------|:--------------------------------------|
| `GET  /api/v1/auth/me`            | happy (200) + missing-session (401)   |
| `GET  /api/v1/dashboard/summary`  | happy with date+group filters         |
| `GET  /api/v1/actors`             | first page + offset pagination        |
| `POST /api/v1/auth/logout`        | 204                                   |

Total: **6 interactions** across **4 endpoints**. The "four
interactions" wording in plan §5.3 refers to the four endpoints; the
sub-cases listed in D8 lock are individual interactions.

## Deferred to PR #13 (D8 lock)

| Endpoint                          | Why deferred                          |
|:----------------------------------|:--------------------------------------|
| `GET  /api/v1/reports`            | Detail view + advanced filter surface land in PR #13. Pact coverage lands together so the contract spans both list + detail. |
| `GET  /api/v1/incidents`          | Same as above. |

The producer-side verifier in
`services/api/tests/contract/test_pact_producer.py` enumerates every
`contracts/pacts/*.json` and verifies all interactions. Adding the
deferred endpoints in PR #13 is purely additive — no harness change
required, the new interactions auto-verify.

## When this list breaks

If a future Group H edit changes the interaction count, update both
the table above AND the BE `provider state` handlers (when those
land in PR #13+). Drift between the FE-emitted pact and the
producer-side state setup surfaces as a `contract-verify` job
failure, which is the intended fail-fast posture per plan D7.

## Provider states declared by these tests

Handlers live in `services/api/src/api/routers/pact_states.py` and
mount at `POST /_pact/provider_states` when `APP_ENV != "prod"` (the
prod guard is pinned by
`services/api/tests/contract/test_pact_states_prod_guard.py`). The
producer verifier harness in
`services/api/tests/contract/test_pact_producer.py` passes
`provider_states_setup_url` so pact-ruby POSTs each state before
replaying its interaction.

| State name                                                             | Handler behavior                                     |
|:-----------------------------------------------------------------------|:-----------------------------------------------------|
| `an authenticated analyst session`                                     | Mints a Redis session + returns `Set-Cookie` so the follow-up request authenticates |
| `no valid session cookie`                                              | No-op — the follow-up `/auth/me` call reaches the 401 path |
| `seeded reports/incidents/actors and an authenticated analyst session` | Ensures a group row + mints a session. Dashboard aggregator returns tolerable integers (matchers are shape-only). |
| `seeded actors and an authenticated session`                           | Upserts `Lazarus Group` + mints a session            |
| `seeded actors with at least 100 rows and an authenticated session`    | Idempotently seeds `pact-fixture-group-NNNN` rows up to 100 so offset=50 lands on a non-empty second page |

Extending this list is PR-local: add a new `.given(...)` string in
the FE pact test, add a matching branch in `pact_states.py`, and the
verifier picks it up on the next run. Unknown states fall through to
"mint an analyst session" so typos don't silently authenticate as
an unintended role.
