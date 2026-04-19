# Lighthouse manual audit harness (plan D6)

This directory owns the **manual acceptance** Lighthouse audit.
Plan D6 locks it as a **PR body artifact**, **not** a CI hard
gate — the reviewer runs the audit, reads the 3-run median, and
attaches the JSON reports to the PR conversation.

Shipped in PR #13 Group K with `/dashboard` as the only target.
PR #14 Group H added three detail routes + a per-route reports
sub-directory so each route keeps its own SUMMARY.md. PR #15
Group G adds one more target — `/actors/999003` replayed against
the PR #15 Group C **populated actor-reports** provider state so
the reviewer sees `ActorDetailPage` with the `ActorLinkedReportsPanel`
populated, not empty.

## What the harness does

`run-audit.mjs` runs Lighthouse `LH_RUNS` times (default 3) against
a preview-build URL for each theme in `LH_THEMES` (default
`light,dark`), using Chrome DevTools Protocol
`Emulation.setEmulatedMedia` to drive `prefers-color-scheme`
before first paint so the FOUC script in `index.html` resolves the
right theme immediately.

Each run writes the full Lighthouse JSON to `reports/<theme>-run<N>.json`.
After every theme's runs finish, the harness writes `reports/SUMMARY.md`
with a median table across the 4 D6 categories:

- Performance
- Accessibility
- Best Practices
- SEO

Exit code is **always `0`**. A harness bug or a single failing run
never breaks the loop — plan D6 explicitly forbids CI-gating on
this signal because headless Lighthouse variance on shared runners
is ±10 points.

## Targets

All audits run against the Vite **preview** build on `:4173`
(`vite preview` — the production-shaped bundle). **Not the dev
server.** D6 locks this: dev-mode HMR bundles over-report or
under-report depending on the runner, and would mask real
regressions.

| Route                        | Target path                 | Required provider-state (`.given(...)`)                                            | Pinned fixture id(s)            | Added in        |
|:-----------------------------|:----------------------------|:-----------------------------------------------------------------------------------|:--------------------------------|:----------------|
| Dashboard                    | `/dashboard`                | `seeded actors with at least 100 rows and an authenticated session`                | —                               | PR #13 Group K  |
| Report detail                | `/reports/999001`           | `seeded report detail fixture and an authenticated analyst session`                | 999001                          | PR #14 Group H  |
| Incident detail              | `/incidents/999002`         | `seeded incident detail fixture and an authenticated analyst session`              | 999002                          | PR #14 Group H  |
| Actor detail (empty panel)   | `/actors/999003`            | `seeded actor detail fixture and an authenticated analyst session`                 | 999003                          | PR #14 Group H  |
| Actor detail with linked reports | `/actors/999003`        | `seeded actor with linked reports fixture and an authenticated analyst session`    | 999003 + 999050 / 999051 / 999052 | PR #15 Group G  |

The PR #15 target reuses the **same path** `/actors/999003` as
the PR #14 row but runs against a **different provider state**.
That state seeds three reports (`ACTOR_REPORTS_FIXTURE_REPORT_IDS
= 999050 / 999051 / 999052`) linked to actor 999003 via
`report_codenames`, so the new `ActorLinkedReportsPanel` renders
its populated branch instead of the D15 empty card. Running both
targets captures any regression where mounting the panel degrades
the detail-page scores.

Pinned fixture ids come from Group C (report / incident /
similar), PR #14 Group G (actor — re-pinned to eliminate Lazarus
natural-id drift), and PR #15 Group C (new reports pinned at
999050 / 999051 / 999052). Full id registry lives in
`apps/frontend/tests/contract/README.md` under "Pinned-id strategy
for detail + similar + actor-reports paths".

## Prerequisites

1. **Build + preview the FE**

   In one terminal:
   ```bash
   pnpm --filter @dprk-cti/frontend run build
   pnpm --filter @dprk-cti/frontend run preview
   ```
   Preview serves on `:4173` and blocks the terminal. Leave it
   running for the audit.

2. **BE running on `:8000`**

   In another terminal:
   ```bash
   cd services/api && ./.venv/Scripts/python.exe -m uvicorn api.main:app --port 8000
   ```

3. **Seed every provider-state the target list needs, in one session**

   Without a session, every protected route redirects to `/login`
   and the audit measures the login page. Each state handler in
   `services/api/src/api/routers/pact_states.py` mints a session
   cookie; POSTing each state sequentially with `-b/-c` re-uses
   the same cookie jar (state handlers are idempotent on the DB,
   so re-seeding is safe).

   ```bash
   STATES=(
     "seeded actors with at least 100 rows and an authenticated session"
     "seeded report detail fixture and an authenticated analyst session"
     "seeded incident detail fixture and an authenticated analyst session"
     "seeded actor detail fixture and an authenticated analyst session"
     "seeded actor with linked reports fixture and an authenticated analyst session"
   )
   for state in "${STATES[@]}"; do
     curl -sS -X POST http://127.0.0.1:8000/_pact/provider_states \
       -H 'Content-Type: application/json' \
       -d "{\"state\":\"$state\"}" \
       -c session.cookies -b session.cookies >/dev/null
   done
   ```

   All five states are idempotent on the DB; the fifth state
   (PR #15 Group C) overlaps the fourth's actor seed by design — it
   reuses `ACTOR_DETAIL_FIXTURE_ID=999003` and only ADDS the three
   `report_codenames` links, so seeding both in one session is
   safe and leaves the cookie jar intact.

   Then import `session.cookies` into the browser profile used by
   the headless Chrome the audit launches OR attach it via a
   profile known to chrome-launcher. For purely command-line use,
   a future iteration could add `--extra-headers` — tracked as a
   follow-up.

## Running

### Single target (backwards compatible with PR #13)

```bash
pnpm --filter @dprk-cti/frontend run lighthouse:audit
```

Writes to `reports/`. Useful for a `/dashboard`-only smoke.

### All targets (PR #14 Group H + PR #15 Group G)

Loop over the five targets; each invocation lands in its own
sub-directory so `SUMMARY.md` + per-theme JSONs don't overwrite.
The two `/actors/999003` targets share a path but not a subdir —
the reviewer sees both the empty-panel (PR #14) and the populated-
panel (PR #15) audits side by side.

```bash
TARGETS=(
  "dashboard:/dashboard"
  "reports-999001:/reports/999001"
  "incidents-999002:/incidents/999002"
  "actors-999003:/actors/999003"
  "actors-999003-linked-reports:/actors/999003"
)
for entry in "${TARGETS[@]}"; do
  subdir="${entry%%:*}"
  route="${entry#*:}"
  LH_PATH="$route" LH_REPORTS_SUBDIR="$subdir" \
    pnpm --filter @dprk-cti/frontend run lighthouse:audit
done
```

**Ordering note**: run `actors-999003` BEFORE `actors-999003-linked-reports`.
Once the PR #15 Group C populated state seeds the three
`report_codenames` rows, the PR #14 "empty panel" audit can still
produce the populated shape because the DB state persists between
audit runs. Reviewer can either (a) tear down the linked-reports
rows between runs, or (b) accept that both audits measure the
populated state if the empty-panel variant already shipped
artifacts in a prior PR #14 reviewer run.

Result layout:

```
apps/frontend/lighthouse/reports/
├── dashboard/
│   ├── SUMMARY.md
│   ├── light-run1.json .. light-run3.json
│   └── dark-run1.json  .. dark-run3.json
├── reports-999001/   … same shape
├── incidents-999002/ … same shape
├── actors-999003/    … same shape (empty panel state)
└── actors-999003-linked-reports/ … same shape (populated panel state)
```

### Env overrides

| Env var              | Default                         | Purpose |
|:---------------------|:--------------------------------|:--------|
| `LH_URL_BASE`        | `http://127.0.0.1:4173`         | Preview origin |
| `LH_PATH`            | `/dashboard`                    | Audited route |
| `LH_REPORTS_SUBDIR`  | *(empty)*                       | Sub-dir under `reports/` — keep per-route artifacts isolated |
| `LH_RUNS`            | `3`                             | Runs per theme (median window) |
| `LH_THEMES`          | `light,dark`                    | Comma list — each emulated via CDP |
| `LH_TIMEOUT_MS`      | `90000`                         | Per-run ceiling |

## Interpreting output

- `reports/<subdir>/<theme>-run<N>.json` — full Lighthouse report
  (audits, diagnostics, resource traces). Attach to the PR body
  as-needed (the SUMMARY is usually enough for review, JSONs are
  for regression diagnosis).
- `reports/<subdir>/SUMMARY.md` — human-readable 3-run-median
  table per theme + self-contained reproduction block that echoes
  the exact env values used. Paste this file into the PR comment
  as the acceptance artifact; one paste per target route.

The reviewer checks, per target:

1. Was the audit run against `:4173` preview (not `:5173` dev)?
   Grep `SUMMARY.md` for the target URL line — it starts with
   `- Target: http://127.0.0.1:4173/...`.
2. Are all 4 categories ≥ 90 on the **median** (not the best or
   worst run)?
3. Are results captured for both themes (light + dark)?
4. Does the target path match the expected fixture id? (e.g.,
   `/reports/999001` — mismatch likely means the state wasn't
   seeded and the audit measured a NotFound page.)

If any category drops below 90 on the median, the reviewer either
(a) requests a regression-specific follow-up, or (b) accepts with
rationale documented in the PR. Plan D6 makes this a judgment
call, not a build break.

## Not a CI gate

This harness is deliberately absent from `.github/workflows/ci.yml`.
CI-runner Lighthouse variance invalidates any meaningful pass/fail
signal at this scope. Enforcement lands in a later milestone once
measurements stabilize (see plan D6 rationale).
