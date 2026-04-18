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

| State name                                                             | Meaning                                              |
|:-----------------------------------------------------------------------|:-----------------------------------------------------|
| `an authenticated analyst session`                                     | Valid signed session cookie present, role=analyst    |
| `no valid session cookie`                                              | No cookie / expired cookie — `/auth/me` returns 401  |
| `seeded reports/incidents/actors and an authenticated analyst session` | DB has rows for the dashboard aggregator             |
| `seeded actors and an authenticated session`                           | DB has at least one actor row                        |
| `seeded actors with at least 100 rows and an authenticated session`    | Actors > one page (PAGE_SIZE=50) so offset works     |

PR #11 baseline does not implement provider state handlers in the
verifier. The handlers can be added incrementally; until they exist
the producer test passes by virtue of stable test fixtures + the
same shapes the BE returns under any analyst session.
