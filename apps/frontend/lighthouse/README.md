# Lighthouse manual audit harness (PR #13 Group K / plan D6)

This directory owns the **manual acceptance** Lighthouse audit for
PR #13. Plan D6 locks it as a **PR body artifact**, **not** a CI
hard gate — the reviewer runs the audit, reads the 3-run median,
and attaches the JSON reports to the PR conversation.

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

Default target is `http://127.0.0.1:4173/dashboard` — the preview
(Vite's `vite preview` output, i.e., the production-shaped bundle).
**Not the dev server.** D6 locks this: dev-mode HMR bundles
over-report or under-report depending on the runner, and would
mask real regressions.

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

3. **Seeded session cookie forwarded to the preview origin**

   Without a session, `/dashboard` redirects to `/login` and the
   audit measures the login page instead. Use the same BE
   provider-state endpoint the Playwright E2E uses (drift-free
   with `contract-verify`):

   ```bash
   curl -X POST http://127.0.0.1:8000/_pact/provider_states \
     -H 'Content-Type: application/json' \
     -d '{"state":"seeded actors with at least 100 rows and an authenticated session"}' \
     -c session.cookies
   ```

   Then import `session.cookies` into your local browser OR run
   the audit from a browser profile that already has the cookie.
   For purely command-line use, a future iteration could add
   `--extra-headers` — tracked as a follow-up.

## Running

```bash
pnpm --filter @dprk-cti/frontend run lighthouse:audit
```

Override defaults via env:

| Env var        | Default                         | Purpose |
|:---------------|:--------------------------------|:--------|
| `LH_URL_BASE`  | `http://127.0.0.1:4173`         | Preview origin |
| `LH_PATH`      | `/dashboard`                    | Audited route |
| `LH_RUNS`      | `3`                             | Runs per theme (median window) |
| `LH_THEMES`    | `light,dark`                    | Comma list — each emulated via CDP |
| `LH_TIMEOUT_MS`| `90000`                         | Per-run ceiling |

## Interpreting output

- `reports/<theme>-run<N>.json` — full Lighthouse report (audits,
  diagnostics, resource traces). Attach to the PR body.
- `reports/SUMMARY.md` — human-readable 3-run-median table per
  theme + reproduction block. Paste this whole file into the PR
  comment as the acceptance artifact.

The reviewer checks:

1. Was the audit run against `:4173` preview (not `:5173` dev)?
   Grep `SUMMARY.md` for the target URL line.
2. Are all 4 categories ≥ 90 on the **median** (not the best or
   worst run)?
3. Are results captured for both themes (light + dark)?

If any category drops below 90 on the median, the reviewer either
(a) requests a regression-specific follow-up, or (b) accepts with
rationale documented in the PR. Plan D6 makes this a judgment
call, not a build break.

## Not a CI gate

This harness is deliberately absent from `.github/workflows/ci.yml`.
CI-runner Lighthouse variance invalidates any meaningful pass/fail
signal at this scope. Enforcement lands in a later milestone once
measurements stabilize (see plan D6 rationale).
