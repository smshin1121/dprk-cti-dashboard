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
| `GET  /api/v1/auth/me`            | happy (200)                           |
| `GET  /api/v1/dashboard/summary`  | happy with date+group filters         |
| `GET  /api/v1/actors`             | first page + offset pagination        |
| `POST /api/v1/auth/logout`        | 204                                   |

Total: **5 interactions** across **4 endpoints**.

### Why `/auth/me 401` is not in the consumer pact

Pact-ruby's Verifier applies `custom_provider_headers` — the
mechanism we use to inject the session cookie — to EVERY
interaction in a single run. That authenticates the 401 request and
makes it return 200, so co-existing `happy + 401` against one live
provider is structurally impossible without splitting the pact
across multiple verifier passes.

The 401 path is a FE-side cache-eviction contract, not an HTTP-shape
contract. It is covered end-to-end by:

  `apps/frontend/src/features/auth/__tests__/useMe.test.tsx`
    → `surfaces ApiError 401 as null cached data via queryCache handler`

That test pins the queryCache onError branch — a contract Pact can't
express because it's about FE-local state transitions, not the HTTP
surface.

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

## Provider states + auth propagation

Handlers live in `services/api/src/api/routers/pact_states.py` and
mount at `POST /_pact/provider_states` when `APP_ENV != "prod"` (the
prod guard is pinned by
`services/api/tests/contract/test_pact_states_prod_guard.py`). The
producer verifier harness in
`services/api/tests/contract/test_pact_producer.py` passes
`provider_states_setup_url` so pact-ruby POSTs each state before
replaying its interaction.

State handlers **seed the DB** required by each interaction's
matchers. They do NOT handle auth propagation — pact-ruby does not
forward cookies from state-change responses to interaction requests.
Auth is supplied by the verifier via `custom_provider_headers` (see
below).

| State name                                                             | DB shape seeded                                      |
|:-----------------------------------------------------------------------|:-----------------------------------------------------|
| `an authenticated analyst session`                                     | No DB seed — only present so the state table is complete for the `/auth/me` happy case |
| `seeded actors and an authenticated session`                           | Upserts `Lazarus Group` with full shape + 1 linked codename |
| `seeded actors with at least 100 rows and an authenticated session`    | Idempotently tops up groups to 100; every filler carries mitre id + non-empty aka + non-null description + linked codename (page-2 matcher requirement) |
| `seeded reports/incidents/actors and an authenticated analyst session` | Source + group + codename + report (linked via `report_codenames`) + incident + motivation — satisfies every `eachLike` array on `/dashboard/summary` |

For the auth cookie: the CI `contract-verify` job POSTs
`/_pact/provider_states` with `{"state": "an authenticated analyst
session"}` once before running the verifier, reads `Set-Cookie`,
and exports the cookie value as `PACT_SESSION_COOKIE`. The
`test_pact_producer` harness passes it to the verifier as
`custom_provider_headers=["Cookie: dprk_cti_session=<value>"]`,
which pact-ruby injects on every interaction request.

Extending this list is PR-local: add a new `.given(...)` string in
the FE pact test, add a matching DB-seed branch in `pact_states.py`,
and the verifier picks it up on the next run.
