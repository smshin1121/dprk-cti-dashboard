# Pact consumer tests

Consumer-driven contract tests using `pact-js` (V3 / FFI). Each
`*.pact.test.ts` here writes to `contracts/pacts/<consumer>-<provider>.json`
at the repo root, which the BE `contract-verify` job verifies via
`pact-python` against a live uvicorn process.

## Run

```bash
pnpm test:contract     # apps/frontend
```

## Coverage (PR #12 D8 lock + PR #13 Group J extension)

| Endpoint                               | Interactions                          | Added in |
|:---------------------------------------|:--------------------------------------|:---------|
| `GET  /api/v1/auth/me`                 | happy (200)                           | PR #12   |
| `GET  /api/v1/dashboard/summary`       | happy with date+group filters         | PR #12   |
| `GET  /api/v1/actors`                  | first page + offset pagination        | PR #12   |
| `POST /api/v1/auth/logout`             | 204                                   | PR #12   |
| `GET  /api/v1/analytics/attack_matrix` | happy with date+group+top_n (D2 row-based shape) | PR #13 Group J |
| `GET  /api/v1/analytics/trend`         | happy with date+group (D2 monthly YYYY-MM buckets) | PR #13 Group J |
| `GET  /api/v1/analytics/geo`           | happy with date filters (D2/D7 plain `{iso2, count}` rows; KP is a plain row) | PR #13 Group J |

Total: **8 interactions** across **7 endpoints**.

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

## Still deferred (PR #13 D7 carry-forward)

| Endpoint                          | Why deferred                          |
|:----------------------------------|:--------------------------------------|
| `GET  /api/v1/reports`            | Detail view + advanced filter surface land in Phase 3 (PR #13 kept list shell types-only; detail DTO shape is still moving). |
| `GET  /api/v1/incidents`          | Same as above. |

The producer-side verifier in
`services/api/tests/contract/test_pact_producer.py` enumerates every
`contracts/pacts/*.json` and verifies all interactions. Adding the
deferred endpoints in a later PR is purely additive — no harness
change required, the new interactions auto-verify.

## When this list breaks

If a future edit changes the interaction count, update both the
table above AND the BE `provider state` handlers. Drift between the
FE-emitted pact and the producer-side state setup surfaces as a
`contract-verify` job failure, which is the intended fail-fast
posture per plan D7.

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

| State name                                                                | DB shape seeded                                      | Added in |
|:--------------------------------------------------------------------------|:-----------------------------------------------------|:---------|
| `an authenticated analyst session`                                        | No DB seed — only present so the state table is complete for the `/auth/me` happy case | PR #12 |
| `seeded actors and an authenticated session`                              | Upserts `Lazarus Group` with full shape + 1 linked codename | PR #12 |
| `seeded actors with at least 100 rows and an authenticated session`       | Idempotently tops up groups to 100; every filler carries mitre id + non-empty aka + non-null description + linked codename (page-2 matcher requirement) | PR #12 |
| `seeded reports/incidents/actors and an authenticated analyst session`    | Source + group + codename + report (linked via `report_codenames`) + incident + motivation — satisfies every `eachLike` array on `/dashboard/summary` | PR #12 |
| `seeded attack_matrix dataset and an authenticated analyst session`       | Techniques `T1566` + `T1190` on `TA0001` and `T1059` on `TA0002`; 3 reports inside pact window linked to both Lazarus codename (so `group_id=1` filter still produces rows) AND techniques. Aggregator output: `TA0001: {T1566: 2, T1190: 1}` + `TA0002: {T1059: 1}` — every `eachLike` array non-empty | PR #13 Group B |
| `seeded trend dataset and an authenticated analyst session`               | 3 reports spanning 2 months inside pact window (2026-02 ×2, 2026-03 ×1), all linked to Lazarus codename — `buckets` ≥ 2 under a group filter | PR #13 Group B |
| `seeded geo dataset and an authenticated analyst session`                 | 3 incidents with distinct ISO2 countries (`KR`, `US`, `KP`), all inside pact window — exercises plan D7 "KP is a plain row" invariant. No group_id wiring required (`/analytics/geo` is group-no-op by schema) | PR #13 Group B |

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
