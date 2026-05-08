# PR 3 — Actor-network data path + populated graph

Implements `docs/plans/actor-network-data.md` v1.6.1 (commit
`b2f418c`; original v1.6 plan-lock at commit `174479a`, v1.6.1 adds
T15 PR-as-diff Codex r1 §0.1 amendments). Closes the Option-C 3-PR
sequence by replacing the L6
reserved-slot text-only `actor-network-graph` block (PR #32 lock)
with a populated SNA visualization driven by a new BE endpoint —
while preserving every reserved-slot discipline already locked at
the design layer (no mock SVG, no fabricated data, honest empty
contract when the BE returns no rows).

**BE + FE PR.** New `/api/v1/analytics/actor_network` route +
aggregator + 3 DTOs; new `useActorNetwork` hook + zod schema +
endpoint + queryKey; new `ActorNetworkGraph.tsx` component (d3-force
SVG, stopped-and-ticked); existing reserved-slot block in
`DashboardPage.tsx:119-143` swapped for `<ActorNetworkGraph />`;
empty-state branch preserves the L6 vocabulary so the workspace
test contract holds across the swap.

## Scope

**In scope (this PR):**
- BE new endpoint, aggregator, 3 Pydantic DTOs, OpenAPI snapshot
  regen.
- BE Pact provider-state handler entry that seeds parents-before-
  junctions with distinct natural keys.
- FE new zod schema (3 schemas + `cap_breached: z.boolean().default(false)`),
  endpoint client, queryKey factory, React Query hook, Pact
  consumer interaction.
- FE `ActorNetworkGraph.tsx` (d3-force SVG; stable topology
  signature; degree → radius; kind → distinct stroke; aria-label
  per node; cap-breach surface conditional on `cap_breached: true`;
  empty state preserves L6 testids).
- FE `DashboardPage.tsx` swap of reserved-slot block for the
  component; `DashboardPage.workspace.test.tsx` extended to mock
  the new endpoint with empty-state body so the workspace's "no
  svg/canvas/etc." negative pin still holds in the empty branch.
- Tests: BE 16 unit + 18 integration + 4 OpenAPI snapshot + 3 pact-
  state matcher tests; FE 14 hook + 11 component + 4 architectural
  guard.
- 1 new i18n key per locale (`dashboard.actorNetwork.capBreachedNotice`),
  folds T12 i18n parity work.

**Out of scope (deferred — explicit, with target):**
- Tool↔tool / tool↔sector / sector↔sector edges (deferred per L3;
  future PR if analyst UAT requests).
- Persisted graph snapshots / time-travel queries (no DB write
  surface added).
- Click-to-drill from a node into `/actors/:id` or `/incidents`
  filtered view (separate FE PR).
- Performance optimization for `top_n_*` > 200 (clamp prevents
  this).
- Comprehensive responsive redesign for the SVG layout on `< 1024px`
  (same minimum-collapse contract PR 2 locked).
- Continuous animation of d3-force (deferred — stopped-and-ticked
  default per L12).
- DESIGN.md token migration for the hardcoded SVG colors
  (`#ef4444` / `#3b82f6` / `#10b981` / `#94a3b8` / `white`) —
  Codex r9 L1; tracked as a follow-up that touches DESIGN.md
  vocabulary.

## Plan locks (L1-L16)

All 16 architectural decisions pre-applied at plan v1.6 lock; see
`docs/plans/actor-network-data.md` §2 for the full table. Highlights:

- **L1**: Data path = new endpoint (Option A; Codex round 0).
- **L2**: Wire shape `{nodes, edges, cap_breached}`. `source_id` /
  `target_id` (NOT `source` / `target`).
- **L3**: 3 canonical edge classes (actor↔tool, actor↔sector,
  actor↔actor) with `COUNT(DISTINCT)` to prevent self-join inflation.
- **L4**: Step A-F algorithm — eligibility filter → cap-aware
  actor cut → tool/sector cuts → first-pass edges → high-weight
  rescue (within eligible set) → final response.
- **L7(b)**: Selected actors always count toward `top_n_actor`;
  filler ranking by GLOBAL degree (not eligible-set degree).
- **L13**: Stable topology signature (sorted node IDs + sorted
  `source:target:weight` triples) drives d3-force `useMemo` reseed.
- **L14**: Pact provider state `actor network co-occurrence
  available`; parents-before-junctions; distinct natural keys.

## §0.1 amendments

| ID | Plan said | Implementation | Reason |
|:---|:---|:---|:---|
| §0.1 (T8) | "Pinned IDs in 999xxx range per memory `pattern_pact_literal_pinned_paths`." | No pinned IDs; natural-key SELECT-first matching `_ensure_attack_matrix_fixture` / `_ensure_trend_fixture` / `_ensure_geo_fixture` patterns. | `pattern_pact_literal_pinned_paths` applies to **path-param** interactions (`/actors/{id}` etc.); actor-network has only query params, so pinning IDs deviates from sibling-analytics convention without unblocking any matcher. Recorded in plan v1.6 history + commit body of `f7e44fc`. |
| §0.1 (T8 r2) | Plan v1.6 used mitre IDs `G9001/G9002/G9003`. | Implementation uses `G9101/G9102/G9103`. | `_ensure_actor_detail_fixture` already uses `G9003`; `groups.mitre_intrusion_set_id` is NOT a unique column so this wouldn't have raised, but keeps the "cannot collide" claim accurate. Codex r2 M1; folded in `c7bb567`. |
| §0.1 (T10) | Plan T12 said i18n parity is no-op "if no new keys". | T10 introduces `dashboard.actorNetwork.capBreachedNotice` key (1 per locale) for the cap-breach surface, folding T12 work into T10. Cross-locale parity test extended in `apps/frontend/src/i18n/__tests__/init.test.ts` to include the new key. | The cap-breach surface is part of T4 contract (testid pinned); rendering an empty surface or hardcoded literal would either fail the test or violate the i18n discipline. T15 PR-as-diff Codex r1 M1 (parity test extension) folded. |
| §0.1 (T10) | Plan L12 specified d3-force runs inside a `useEffect` keyed on the L13 topology signature. | Implementation uses `useMemo` instead. | Codex r9 M1 fold during T10 GREEN required separating topology-stable computation (positions) from per-render concerns (label/kind/degree on same-topology refetch). With `useEffect`, the layout would run after render and require a `useState` position map + setter to trigger re-render — that bypasses the M1 fold's "render label/kind/degree from CURRENT props" guarantee. With `useMemo`, the topology-keyed memo runs synchronously per render and the render branch reads `nodes` (current props) joined to the position map, satisfying both L12 ("synchronous run + `.stop()`") and the M1 fold (memoize positions only). Pattern saved as memory `pattern_memo_positions_only_when_metadata_can_drift`. T15 PR-as-diff Codex r1 M2 folded. |

## Test results

### BE — passes locally

| Test file | Tests | Status |
|:---|:---:|:---:|
| `services/api/tests/unit/test_analytics_aggregator.py` (T2 — 8 actor-network classes + sibling) | 16 actor-network + 21 sibling | ✓ all GREEN |
| `services/api/tests/integration/test_analytics_route.py` (T1 — 6 actor-network classes + sibling) | 18 actor-network + 31 sibling | ✓ all GREEN |
| `services/api/tests/contract/test_openapi_snapshot.py` (T6) | 4 | ✓ all GREEN |
| `services/api/tests/integration/test_pact_state_fixtures.py` (T8 +3 actor-network) | 3 actor-network + sibling | skip locally (CI-only) |
| **Actor-network + sibling analytics suite** | **90** | **✓ all GREEN** |
| **Full BE suite** | **807 passed + 5 skipped** | **0 regressions** (1 pre-existing local-only `test_pact_producer_verifies_consumer_contracts` requires `PACT_PROVIDER_BASE_URL`, unrelated) |

### FE — passes locally

| Test file | Tests | Status |
|:---|:---:|:---:|
| `useActorNetwork.test.tsx` (T3) | 14 | ✓ all GREEN |
| `ActorNetworkGraph.test.tsx` (T4) | 11 | ✓ all GREEN |
| `ActorNetworkGraph.architectural-guard.test.tsx` (T5) | 4 | ✓ all GREEN |
| `DashboardPage.workspace.test.tsx` (extended for actor_network mock) | unchanged count | ✓ all GREEN |
| `frontend-dprk-cti-api.pact.test.ts` (T11 +1 actor-network) | 21 | ✓ all GREEN |
| **Full FE suite** | **742** | **✓ 0 regressions** |

`pnpm run build` exits 0.

### CI — GREEN on `b2f418c`

All 12 checks COMPLETED with conclusion=SUCCESS, including:

- **`contract-verify`**: pact-python verifier ran against the
  regenerated `contracts/pacts/frontend-dprk-cti-api.json` (with
  the new actor-network interaction) against a live uvicorn
  instance with the T8 provider state — passed. Matcher cascade
  intact, all eachLike fixtures non-empty, integer / boolean
  fields type-checked.
- `frontend`, `frontend-e2e`, `python-services` (api / worker /
  llm-proxy), `api-tests`, `worker-tests`, `llm-proxy-tests`,
  `db-migrations`, `data-quality-tests`, `api-integration` — all
  GREEN.

PR mergeStateStatus = `CLEAN`, mergeable = `MERGEABLE`.

### Pending — manual smoke

- **Manual smoke (T14)**: pending user run per memory
  `pattern_host_hybrid_dev_triad`. Login as `analyst@dev.local` per
  `keycloak_dev_realm`; navigate to `/dashboard`; verify
  `<ActorNetworkGraph />` renders with seeded fixture data; degree-
  centrality node sizing visible; FilterBar group_id toggle
  re-renders the focused subset (topology signature flip drives
  reseed); date-out range collapses to text-only empty state;
  navigate to `/reports`, `/incidents`, `/actors` — verify
  ActorNetworkGraph DOES NOT render (slot is dashboard-only per
  DESIGN.md).
- **Pact provider verifier local run**: not run locally as part of
  this PR's commits because the `contract-verify` CI job is the
  canonical surface (now GREEN on `b2f418c`); matcher-shape is
  independently verified by `test_pact_state_fixtures.py`.

## Cross-AI review trail

| Round | Phase | Verdict | Findings folded |
|:---:|:---|:---|:---|
| r0 | Data path decision (prior session) | RECOMMEND Option A | — |
| r1 | Plan-doc REVISE 1 (prior session) | REVISE | 18 (3 CRITICAL, 6 HIGH, 5 MEDIUM, 4 LOW) |
| r2 | Plan-doc REVISE 2 (prior session) | REVISE | 9 (2 CRITICAL, 4 HIGH, 3 MEDIUM) |
| r3 | Plan-doc PROCEED-WITH-AMENDMENT (prior session) | PROCEED | 1 LOW (history-entry literal-string nit) |
| r4 | RED-batch (prior session) | REVISE | 4 (1 CRITICAL, 2 HIGH, 1 MEDIUM) — degree fixture conflation, COUNT(DISTINCT) regression coverage, lenient wire-shape, null-group test |
| r5 | RED-batch confirm (prior session) | PROCEED | 0 |
| r6 | T7 GREEN (prior session) | PROCEED | 3 (1 MEDIUM edge global-sort + 2 LOW: 422 description, dead var) |
| r7 | T7 GREEN confirm (prior session) | PROCEED | 0 |
| r1 (this session) | Next-task decision | CLEAN PROCEED to T8 | 0 (2 LOW defer/annotate) |
| r2 (this session) | T8 fold review | FOLD-then-PROCEED | 5 (1 HIGH source/target field rename, 2 MEDIUM, 2 LOW) |
| r3 (this session) | T8 confirm | FOLD-again | 3 LOW (docstring drift × 2, tautological assert) |
| r4 (this session) | T8 final | CLEAN PROCEED to T3-T5 | 0 |
| r5 (this session) | T3-T5 RED batch review | FOLD-then-PROCEED | 7 (1 HIGH symbol guard, 4 MEDIUM, 2 LOW) |
| r6 (this session) | T3-T5 confirm | FOLD-again | 1 MEDIUM (chain-shape canonical edge classes) |
| r7 (this session) | T3-T5 final | CLEAN PROCEED to T9 | 0 |
| r8 (this session) | T9 GREEN review | CLEAN PROCEED to T10 (Path A) | 0 |
| r9 (this session) | T10 GREEN review | FOLD-then-PROCEED | 4 (1 MEDIUM memo positions only, 3 LOW: tokens deferred, hashId, d3 types) |
| r10 (this session) | T10 confirm | CLEAN PROCEED to T11 | 0 |
| r11 (this session) | T11 review | CLEAN PROCEED to T13 (Path A) | 0 |
| r1 (T15 PR-as-diff) | post-push, against `478ac76` | FOLD | 4 (2 MEDIUM i18n parity + L13/L12 plan deviation, 2 LOW body counts + DashboardPage docstring) |
| r2 (T15 PR-as-diff) | post-r1-fold, against `b2f418c` | FOLD (docs-only) | 2 LOW (PR body CI status + v1.6.1 reference drift) |

**Total**: 21 Codex rounds across plan, RED, T7, T8, T3-T5, T9,
T10, T11, and PR-as-diff. Every CRITICAL/HIGH finding folded; r1
PR-as-diff confirmed all spec/code Codex resolutions held under
top-to-bottom PR review; r2 verified r1 folds and surfaced only
docs-only LOWs (this commit folds them).

## Acceptance criteria

Plan §7 — 12 ACs:

1. ✅ `GET /api/v1/analytics/actor_network` returns 200 with locked
   DTO shape (verified by T1 + T2 + T7 GREEN).
2. ✅ Filter validation: `group_id=0` → 422; `top_n_*` outside
   `1..200` → 422; vacuous-window `date_from > date_to` → 200
   empty per L10 (verified by T1).
3. ✅ Rate limit returns 429 after 60 calls/minute (per L8); does
   NOT consume `/analytics/attack_matrix` budget (verified by T1).
4. ✅ Pact contract regen GREEN (T11 ✓); provider verifier
   passed on CI `contract-verify` job (commit `b2f418c`, against
   live uvicorn with T8 provider state).
5. ✅ OpenAPI snapshot diff = 1 new path + 3 schemas (verified by
   T6).
6. ✅ `useActorNetwork` queryKey isolated from `summarySharedCache`
   (verified by T5 architectural guard + T3 cache scope tests).
7. ✅ ActorNetworkGraph renders exact `<circle>` count =
   `nodes.length`, exact `<line>` count = `edges.length`; renders
   text-only empty state when `nodes.length === 0`; reserved-slot
   discipline preserved (verified by T4).
8. 🟡 Manual smoke: pending T14 (user action).
9. ✅ Build (`pnpm run build`) exits 0; full FE suite GREEN; full
   BE suite GREEN; Pact consumer GREEN.
10. ✅ No mock SVG / fabricated nodes / synthetic edges /
    skeleton charts / sparkline placeholders rendered for any
    state of the slot (verified by T4 + workspace negative pin).
11. ✅ High-weight rescue rule verifiable (verified by T2).
12. ✅ Group-filter cap-aware behavior verifiable per L4 Step B +
    L7(b) — Scenarios A/B/C (verified by T2).

🟡 = pending user action (T14 manual smoke). All CI checks GREEN.

## Plan reference

`docs/plans/actor-network-data.md` v1.6.1 (commit `b2f418c`); v1.6
plan-lock at commit `174479a`. v1.6.1 adds T15 PR-as-diff Codex r1
fold §0.1 amendments (i18n parity test extension, L13 signature
literal compliance, L12 useEffect→useMemo deviation, plus PR body
count + DashboardPage docstring corrections).
