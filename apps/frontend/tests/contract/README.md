# Pact consumer tests

Consumer-driven contract tests using `pact-js` (V3 / FFI). Each
`*.pact.test.ts` here writes to `contracts/pacts/<consumer>-<provider>.json`
at the repo root, which the BE `contract-verify` job verifies via
`pact-python` against a live uvicorn process.

## Run

```bash
pnpm test:contract     # apps/frontend
```

## Coverage (PR #12 D8 lock + PR #13 Group J + PR #14 Group G)

| Endpoint                               | Interactions                          | Added in |
|:---------------------------------------|:--------------------------------------|:---------|
| `GET  /api/v1/auth/me`                 | happy (200)                           | PR #12   |
| `GET  /api/v1/dashboard/summary`       | happy with date+group filters         | PR #12   |
| `GET  /api/v1/actors`                  | first page + offset pagination        | PR #12   |
| `POST /api/v1/auth/logout`             | 204                                   | PR #12   |
| `GET  /api/v1/analytics/attack_matrix` | happy with date + top_n (D2 row-based shape; unfiltered by group — see Codex R1 P2 note in the test file) | PR #13 Group J |
| `GET  /api/v1/analytics/trend`         | happy with date (D2 monthly YYYY-MM buckets; unfiltered by group) | PR #13 Group J |
| `GET  /api/v1/analytics/geo`           | happy with date filters (D2/D7 plain `{iso2, count}` rows; KP is a plain row) | PR #13 Group J |
| `GET  /api/v1/reports/{id}`            | detail happy with linked_incidents (D9 cap + D11 navigation via `incident_sources`) | PR #14 Group G |
| `GET  /api/v1/incidents/{id}`          | detail happy with linked_reports (D9 cap + D11 bidirectional `incident_sources`) | PR #14 Group G |
| `GET  /api/v1/actors/{id}`             | detail happy (D11 out-of-scope pin: no `linked_reports`/`reports`/`recent_reports` fields) | PR #14 Group G |
| `GET  /api/v1/reports/{id}/similar`    | populated (D8 shape + D9 cap) **AND** D10 empty (`{items: []}` when source has NULL embedding — distinct interaction) | PR #14 Group G |

Total: **13 interactions** across **10 endpoints**.

### Pinned-id strategy for detail + similar paths (PR #14 Group G)

Detail endpoints take the resource id in the PATH. A regex-on-path
matcher would skate close to R3 (pact-js V3 FFI has panicked on
regex matchers applied to headers; path-regex is less tested). The
safer approach is to **literal-pin** the consumer path at a known
fixture id and have the BE state handler seed THAT id specifically
via `ON CONFLICT (id) DO NOTHING` upserts.

Constants live in `services/api/src/api/routers/pact_states.py`:

| Fixture constant                     | Id     | Consumer path                           |
|:-------------------------------------|:-------|:----------------------------------------|
| `REPORT_DETAIL_FIXTURE_ID`           | 999001 | `/api/v1/reports/999001`                |
| `INCIDENT_DETAIL_FIXTURE_ID`         | 999002 | `/api/v1/incidents/999002`              |
| `ACTOR_DETAIL_FIXTURE_ID`            | 999003 | `/api/v1/actors/999003`                 |
| `SIMILAR_POPULATED_SOURCE_ID`        | 999020 | `/api/v1/reports/999020/similar?k=10`   |
| `SIMILAR_EMPTY_EMBEDDING_SOURCE_ID`  | 999030 | `/api/v1/reports/999030/similar?k=10`   |

`ACTOR_DETAIL_FIXTURE_ID` was added in Group G specifically to
avoid Lazarus natural-id drift — the Group C `_ensure_actor_detail_
fixture` originally aliased `_ensure_canonical_lazarus_fixture`,
whose id was DB-sequence-assigned. Pinning a Pact-specific actor
at 999003 makes the contract robust across state replays and
fixture reorderings.

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
| `GET  /api/v1/reports`            | List shell — advanced filter surface (q / tag / source / tlp / domain) has not landed. Detail (`/reports/{id}`) shipped in PR #14 Group G. |
| `GET  /api/v1/incidents`          | Same as above — list shell advanced filter surface pending. Detail (`/incidents/{id}`) shipped in PR #14 Group G. |

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
| `seeded report detail fixture and an authenticated analyst session`       | Pinned-id report at `REPORT_DETAIL_FIXTURE_ID`=999001 + source + 2 tags + Andariel codename link + T1566 technique link + 2 linked incidents (newest-first D9 ordering) | PR #14 Group C |
| `seeded incident detail fixture and an authenticated analyst session`     | Pinned-id incident at `INCIDENT_DETAIL_FIXTURE_ID`=999002 + motivation/sector/country + 1 linked report via `incident_sources` | PR #14 Group C |
| `seeded actor detail fixture and an authenticated analyst session`        | Pinned-id actor at `ACTOR_DETAIL_FIXTURE_ID`=999003 (distinct-name Pact fixture group, NOT Lazarus — avoids DB-sequence drift) + 1 linked codename | PR #14 Group C (rewritten in Group G to pin the id) |
| `seeded similar reports populated fixture and an authenticated analyst session` | Pinned-id source at `SIMILAR_POPULATED_SOURCE_ID`=999020 with embedding + 3 pinned-id neighbors (999011/012/013) with distinct embeddings — cosine kNN returns a 3-row non-empty result (self-exclusion + stable sort per D8) | PR #14 Group C |
| `seeded similar reports empty-embedding fixture and an authenticated analyst session` | Pinned-id source at `SIMILAR_EMPTY_EMBEDDING_SOURCE_ID`=999030 with **NULL embedding** + 1 neighbor (999031) WITH embedding — BE D10 branch returns `{items: []}` despite the neighbor having embedding (regression guard against "DB-wide emptiness" collapse) | PR #14 Group C |

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
