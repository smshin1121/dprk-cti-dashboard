# PR #11 Plan — Phase 2.2 Read API Surface + Rate Limiting (BE only)

**Phase:** 2.2 (design doc v2.0 §14 Phase 1 W5 잔여 — "핵심 API(summary, reports, incidents, actors), OpenAPI 계약, Pact 베이스라인" + §9.2 STRIDE DoS 완화의 rate-limit 번들).
**Status:** **Locked — 2026-04-18** (Decisions D1–D13 lock 완료, PR #10 merge commit `ff709dc` 후 `feat/p2.2-read-api` 분기). Execution-unblocked — Group A 착수 가능.
**Predecessors:** PR #10 (Phase 2.1 review/promote write-path, branch `feat/p2.1-review-promote-api`). 본 PR는 PR #10 머지 직후 새 feature branch에서 시작.
**Successors:**
- **PR #12 (Phase 2.3)** — FE shell (§14 Phase 2 W1–W2). PR #11의 read surface + Pact contract가 FE consumer의 안전 네트워크.
- **PR #13 (Phase 2.4)** — Dashboard views (§14 Phase 2 W3–W6). PR #11이 제공한 JSON shape 위에서 동작.

> **Phase 2.2 범위 근거.** §14 Phase 1 W5는 "핵심 API"를 명시. Phase 1.x에서 Bootstrap/DQ/Audit/RSS/TAXII까지 완료됐으나, FE가 직접 호출할 **read-only** 엔드포인트는 아직 501 stub 또는 미구현 상태. PR #10은 write-path를 열었고, PR #11은 **FE가 붙을 수 있는 최소 read surface** 를 여는 PR — 이후 FE shell(PR #12)과 dashboard view(PR #13)가 모두 이 read 계약 위에서 병렬 진행 가능.

---

## 1. Goal

**FE가 붙을 수 있는 최소 read surface 4종 + OpenAPI 3.1 완성 + Pact producer baseline + 요청 rate limiting 번들.**

Deliver four GET endpoints — `/api/v1/dashboard/summary`, `/api/v1/reports`, `/api/v1/incidents`, `/api/v1/actors` — that return real DB-aggregated shapes (not stubs), with consistent pagination, filter surface, RBAC via existing `require_role` triad, and OpenAPI schema completeness. Bundle a Redis-backed rate limiter (§7.5 스택의 Redis를 재사용) applied at minimum to `/api/v1/auth/login` + `/api/v1/auth/callback` (anti-bruteforce) and to each read endpoint (anti-scrape). Establish a Pact producer baseline — consumer contracts land with PR #12 FE shell, but the producer-side verify harness should be in place so PR #12 can just plug in.

**Non-goals (explicit):**
- **Frontend UI** — PR #12–#13.
- **Write path** beyond what PR #10 already delivered.
- **Analytics endpoints** (`/api/v1/analytics/*`, `/api/v1/search`, `/api/v1/alerts`, `/api/v1/export/*`) — 501 stubs remain. §14 Phase 3 이후.
- **Similarity** (`/api/v1/reports/{id}/similar`) — Phase 3 pgvector work.
- **Read API에 TLP row-level filtering 적용** — design doc §9.3 RBAC matrix은 "View AMBER = analyst/soc/admin"을 명시하지만, PR #11 범위는 **TLP WHITE/GREEN 데이터만 정상 반환**에 제한. AMBER 필터링은 후속 RLS PR로 분리 (lock 필요 — §2 D4 참조).
- **Redis 응답 캐시** (§7.7 aggregate 5분 TTL) — PR #11 은 rate-limit용 Redis만. 응답 캐시는 p95 튜닝 시점인 Phase 4 W4로 지연.
- **Materialized Views** — §7.7 명시적 p95 전략이지만 Phase 4 튜닝.
- **Prometheus 메트릭 신규 추가** — 기존 OpenTelemetry 계측 그대로. Rate-limit block 이벤트는 `audit_log`로 기록 (또는 DQ — lock 필요).
- **Bulk export / CSV / PDF** — §7.6 `/api/v1/export/*` 전용 PR.
- **`POST /ingest/rss/run` + `POST /ingest/taxii/run`** 실제 Prefect 연결 — 501 stub 유지, 별도 infra PR.
- **§10.3 staging 30-day auto-purge** — PR #10 carried follow-up 유지.
- **Node.js 20 GHA bump** — 2026-06-02 deadline, 별도 cleanup PR.

---

## 2. Decisions Locked (D1–D13)

### 2.1 Locked (사용자 1차 리뷰 2026-04-18 — D1–D13 lock)

| ID | Item | Locked Position | Rationale |
|:---:|:---|:---|:---|
| **D1** | Rate-limit 백엔드 | **slowapi + Redis storage**. 앱 레벨에서 처리해야 Keycloak 세션 식별 이후 user/IP 분리 판단 가능. Redis는 이미 session/OIDC state 용도로 존재하므로 신규 인프라 없음. | slowapi = FastAPI 공식 권장, `@limiter.limit` 데코레이터 + Redis storage plug 간단. nginx는 compose topology 밖, 자체 middleware는 유지비용만 증가. |
| **D2** | Rate-limit 수치 + 기준 | **Auth endpoints** (`/auth/login`, `/auth/callback`) = **10/min/IP** (anti-bruteforce, pre-session 이므로 user 식별 불가). **Read endpoints** (`/auth/me`, `/dashboard/summary`, `/reports`, `/incidents`, `/actors`) = **60/min/user** (authenticated `CurrentUser.sub` 기준). **Mutation endpoints** (`/staging/review`, `/staging/{id}` GET, `POST /reports/review/{id}`) = **30/min/user**. 초과 시 **HTTP 429 + `Retry-After` 헤더 + `X-RateLimit-Remaining`**. | IP-only는 NAT 뒤 팀 공유 환경에서 정당한 사용자 차단. user-sub 기준이 정확. anonymous endpoint는 IP fallback 불가피. 60/min read 는 UI interactive(클릭/필터) 통과 + 스크래이퍼 억제의 타협점. |
| **D3** | Pagination 전략 | **Keyset cursor 기본**, PR #10 `/staging/review` 일관. `/reports`: cursor=`(published_at DESC, id DESC)`. `/incidents`: cursor=`(reported DESC, id DESC)`. **`/actors`: offset 예외** (`limit=50 default, max=200`, 소량이라 드리프트 체감 없음). `/dashboard/summary`: 페이지네이션 없음 (단일 객체). `limit` default=50, max=200. 응답 shape `{items: [...], next_cursor: str\|null}`. | Keyset = stable under concurrent writes. Offset 은 actors 만 예외. 단일 cursor 표준이 FE 구현 단순화. |
| **D4** | TLP 필터링 | **PR #11 범위 밖 (defer).** 모든 read endpoint = row-level TLP 필터 없이 전체 행 반환. 현재 데이터는 사실상 WHITE/GREEN. AMBER 유입 시점에 별도 RLS PR. DTO 는 `tlp` 필드 포함하여 FE가 미래 RLS 준비 완료 상태 유지. | §9.3 RBAC 정의는 있으나 AMBER 데이터 0 rows. 조기 구현은 테스트 편의 저하 + 향후 RLS 전환 시 중복 작업. 정책/데이터 두 축이 모두 얇음. |
| **D5** | Filter 파라미터 shape | `/reports`: `q` (title ILIKE only — summary는 Phase 3 pgvector 경로), `tag` (repeatable), `source` (repeatable), `date_from`/`date_to` (ISO date). `/incidents`: `date_from`/`date_to`, `motivation` (repeatable), `sector` (repeatable), `country` (repeatable, ISO 3166-1 alpha-2). `/actors`: 필터 없음. `/dashboard/summary`: `date_from`/`date_to`, `group_ids` (repeatable). Repeatable 필터는 OR semantics. | v1.0 §5.4 원문 충실. 과도한 쿼리 DSL은 Phase 3 analytics. `q` 는 title-only로 좁혀야 pg_trgm 없이 일반 ILIKE 로도 p95 통과 가능. |
| **D6** | `/dashboard/summary` shape | `{total_reports, total_incidents, total_actors, reports_by_year: [{year, count}], incidents_by_motivation: [{motivation, count}], top_groups: [{group_id, name, report_count}]}`. **`top_groups` 기본 N = 5** (`?top_n=N` query param, max=20). 모두 단일 쿼리로 계산 가능한 집계. Redis 응답 캐시는 Phase 4 W4 deferred. p95 ≤300 ms 는 모니터링만 설정 (블로커 아님). | FE KPI 카드 (§14 Phase 2 W1) 필수 필드만. top_n 가변은 FE drill-down 대비. Materialized view는 optimization PR. |
| **D7** | Pact baseline 범위 | **Producer-side verify harness + `contracts/pacts/` 디렉토리 + CI job `contract-verify` 신설 (skip-with-ok)**. Consumer contract 파일은 FE 없으므로 미작성. PR #12 FE shell 이 contract file 커밋 시 verify job 즉시 동작. 라이브러리 **`pact-python`**. | PR #12 와 병렬 작업 가능하게 producer-side 사전 개방. Consumer 없는 상태 skip 은 CI 노이즈 억제. |
| **D8** | Rate-limit block 이벤트 저장 | **Structured log only** (JSON log, fields: `timestamp`, `key` (sub 또는 ip-hash), `endpoint`, `limit`, `window`). **`audit_log` 저장 금지 + 별도 테이블 미생성.** Audit 는 도메인 mutation 추적용이고 rate-limit 은 운영/보안 이벤트로 성격이 다름. Prometheus counter (`rate_limit_blocks_total{endpoint}`) 는 Phase 4 관측성 PR 로 연기. | Audit/도메인 분리가 정석. 로그는 이미 OpenTelemetry 로 Loki/Grafana 로 흐르므로 추가 인프라 없이 관측 가능. 운영 PR에서 필요시 Prometheus counter 추가. |
| **D9** | Detail endpoints (`/reports/{id}`, `/incidents/{id}`, `/actors/{id}`) | **PR #11 범위 밖.** List only. Detail 은 §5.2 `/reports/{id}/similar` 와 함께 **Phase 3**. FE KPI/list 뷰는 detail 없이 구현 가능. | List 커버리지 먼저 + FE shell 병행. Detail 은 pgvector similarity + 드릴다운과 묶어야 가치 발생. |
| **D10** | `/auth/me` 응답 확장 | **현재 `CurrentUser` 스키마 유지** (sub/email/name/roles). `tlp_max` 등 파생 필드 추가 **안함**. PR #12 FE가 실제 필요시 그 PR 에서 확장. PR #11 은 rate-limit decorator 부착 + OpenAPI description 보강만. | 미리 추가한 필드는 소비자 없으면 dead code. FE 요구가 실제로 나올 때 확장. |
| **D11** | 기본 정렬 (endpoint별) | **명시적 lock:** `/reports` = `published_at DESC, id DESC` (cursor tiebreak 일관). `/incidents` = `reported DESC, id DESC`. `/actors` = `name ASC, id ASC` (알파벳순이 FE default UX). `/dashboard/summary` = 정렬 없음 (집계). sort override query param은 **미지원** (PR #11 범위 밖 — 추후 필요 시 별도 lock). | Sort 기본값 명시 없으면 엔진 자유로 결과 순서가 흔들려 integration 테스트/FE가 flaky. Cursor 정의와 sort 정의는 **반드시 일치**. |
| **D12** | Invalid filter 값 처리 | **조용한 ignore 금지. 전부 HTTP 422 + Pydantic `ValidationError` detail.** 빈 string, invalid ISO date, invalid country (ISO 3166-1 alpha-2 regex 검증), invalid tag 형식, out-of-range `limit` (>200 or <=0), malformed cursor, unknown sort key(해당 없음) 모두 422. `/openapi.json` 422 response schema 는 FastAPI 기본 `HTTPValidationError` 재사용. | Silent ignore는 FE 디버깅 지옥 + 보안 측면에서도 침묵은 취약. 경계 검증은 boundary-layer(Pydantic) 에서 일관. |
| **D13** | OpenAPI examples | **PR #11 필수 포함.** 5개 read endpoint + 4개 filter 예시 (happy path + 429 + 422 + empty list) 각각에 `example=` 또는 `openapi_extra={"examples": {...}}` 명시. DTO 단위에서 `Field(..., examples=[...])` + response 단위에서 multi-example. `/docs` Swagger UI + Redoc 두 화면 모두에서 meaningful 예시 노출. | Read API 는 schema 보다 example payload 가 FE/policy 이해도에 지배적. Pact baseline + OpenAPI example 은 서로 보완 관계 (example 은 human-readable, Pact 는 machine-checked). |

### 2.2 Inherited locks (이미 PR #10에서 확정)

| Item | Value |
|:---|:---|
| RBAC | 모든 read endpoint = `Depends(verify_token)` + `Depends(require_role("analyst","researcher","policy","soc","admin"))` — 읽기는 5개 역할 전부. admin-only endpoint는 PR #11 에 없음. |
| Session/auth | Keycloak OIDC + URLSafeTimedSerializer 세션 쿠키 (Phase 1.1 landed). `/auth/me` 는 이미 real (auth.py:245) — PR #11 범위는 verification + docstring 보강 + rate-limit 부착만. |
| OpenAPI docs visibility | dev only (`_docs_url = "/docs" if app_env == "dev" else None`) — main.py 이미 gated. PR #11 에서 변경 없음. |
| Audit logging | 신규 audit action 없음 — read는 audit 미생성 (§11 관측성 + §9.2 Repudiation은 mutation만 대상). Rate-limit block 은 **structured log only** (D8 lock). |

### 2.3 Endpoint/Decision 매트릭스 (D1–D13 locks 반영)

| 엔드포인트 | 메서드 | RBAC | Pagination (D3) | Default sort (D11) | Filters (D5) / invalid → 422 (D12) | Rate limit (D2) | p95 목표 |
|:---|:---:|:---|:---|:---|:---|:---|:---:|
| `/api/v1/dashboard/summary` | GET | analyst/researcher/policy/soc/admin | 없음 (단일 객체) | — | date_from/to, group_ids[], top_n (D6) | 60/min/user | ≤ 300 ms (§7.7) |
| `/api/v1/reports` | GET | same | cursor `(published_at DESC, id DESC)` | published_at DESC, id DESC | q(title ILIKE), tag[], source[], date_from/to | 60/min/user | ≤ 500 ms |
| `/api/v1/incidents` | GET | same | cursor `(reported DESC, id DESC)` | reported DESC, id DESC | date_from/to, motivation[], sector[], country[] | 60/min/user | ≤ 500 ms |
| `/api/v1/actors` | GET | same | offset (`limit` 50/200) | name ASC, id ASC | 필터 없음 | 60/min/user | ≤ 500 ms |
| `/api/v1/auth/me` | GET | (existing `verify_token`) | — | — | — | 60/min/user | — |
| `/api/v1/auth/login` | GET | public | — | — | — | 10/min/IP | — |
| `/api/v1/auth/callback` | GET | public | — | — | — | 10/min/IP | — |
| `/api/v1/staging/review` | GET | analyst/researcher/admin | (PR #10) | (PR #10 FIFO) | — | 30/min/user | — |
| `/api/v1/staging/{id}` | GET | same | — | — | — | 30/min/user | — |
| `POST /api/v1/reports/review/{id}` | POST | same | — | — | — | 30/min/user | — |

---

## 3. Scope

### In scope

- **`services/api/src/api/routers/dashboard.py`** (신규) — `GET /api/v1/dashboard/summary` with filter params per D5/D6.
- **`services/api/src/api/routers/reports.py`** (확장) — `GET /api/v1/reports` 추가 (기존 501 similar 유지, POST review 는 PR #10 그대로).
- **`services/api/src/api/routers/incidents.py`** (신규) — `GET /api/v1/incidents`.
- **`services/api/src/api/routers/actors.py`** (신규) — `GET /api/v1/actors`.
- **`services/api/src/api/main.py`** — 신규 라우터 3종 등록 (dashboard, incidents, actors).
- **`services/api/src/api/read/`** (신규 패키지):
  - `__init__.py`
  - `repositories.py` — 각 엔드포인트의 집계/페이지 쿼리 (SQLAlchemy core select). 읽기 전용이므로 `promote/repositories.py` 와 분리.
  - `dashboard_aggregator.py` — `/dashboard/summary` 집계 계산.
  - `pagination.py` — cursor encode/decode 공통 helper (PR #10 staging의 cursor 로직 일반화 이식).
- **`services/api/src/api/schemas/read.py`** (신규) — Pydantic DTO: `ReportItem`, `ReportListResponse`, `IncidentItem`, `IncidentListResponse`, `ActorItem`, `ActorListResponse`, `DashboardSummary`, `DashboardTopGroup`, `DashboardYearCount`, `DashboardMotivationCount`.
- **`services/api/src/api/rate_limit.py`** (신규) — slowapi `Limiter` 인스턴스 초기화 + Redis storage config + key_func (user sub > IP fallback) + default dependency. `main.py` 에 `limiter.enabled` 기본 True, 테스트 env에서 disable 가능.
- **`services/api/src/api/routers/auth.py`** (확장) — `/login`, `/callback` 에 `@limiter.limit("10/minute")` 부착.
- **`services/api/src/api/routers/staging.py`** + **reports.py** (review POST) — 기존 handler 에 limiter decorator 부착 (30/min/user).
- **`services/api/src/api/config.py`** — Rate-limit 관련 env 추가: `rate_limit_enabled: bool = True`, `rate_limit_storage_url` (Redis URL 재사용 또는 override). Dev default = 기존 Redis URL 재사용.
- **`services/api/tests/` 확장:**
  - `tests/unit/test_read_schemas.py` — DTO 검증 (**D12 — invalid 입력 전부 422 assertion 포함**).
  - `tests/unit/test_pagination_helper.py` — cursor encode/decode round-trip + malformed cursor → 422.
  - `tests/unit/test_read_routes_sqlite.py` — sqlite-memory 스키마 & 라우팅 검증 + default sort (D11) 검증.
  - `tests/unit/test_openapi_examples.py` — **D13 — 5 endpoint + DTO examples 가 `/openapi.json` 에 populate 되어 있음 assertion**.
  - `tests/integration/test_read_real_pg.py` — real-PG 7 시나리오 (§5.2 참조).
  - `tests/integration/test_rate_limit.py` — slowapi 동작 검증 (**fakeredis-py 사용** — lock: 실제 Redis 컨테이너는 CI 비용만 증가, slowapi storage 는 `redis.Redis` 호환이면 OK).
  - `tests/contract/test_pact_producer.py` — Pact producer verify harness (stub, consumer contract 없으면 skip-with-ok).
- **`contracts/pacts/`** (신규 디렉토리) — README + CI integration plan. FE consumer 파일 커밋 시 CI가 자동 verify.
- **`contracts/openapi/`** — 기존 디렉토리에 PR #11 endpoint 반영된 `/openapi.json` snapshot commit + drift 검증 CI step (PR #10 의 OpenAPI surface 검증 스텝 확장).
- **`.github/workflows/ci.yml`** — `api-integration` job 에 새 read-path + rate-limit 테스트 포함. 신규 `contract-verify` job 은 Pact consumer 없으면 **skip-with-ok** 처리.
- **`services/api/pyproject.toml`** — `slowapi`, `pact-python` (dev extra), `fakeredis` (dev extra, rate-limit 테스트용) 추가.
- **D13 — OpenAPI examples:** 각 DTO 에 `Field(..., examples=[...])`, 각 route 에 `responses={200: {"content": {"application/json": {"examples": {...}}}}}` 또는 `openapi_extra`. Happy path + 429 + 422 + empty list 예시 필수.

### Out of scope (explicit)

- `/api/v1/analytics/*` (heatmap, attribution, geopolitical, forecast) — §14 Phase 3.
- `/api/v1/search` — Phase 3 (pgvector + pg_trgm 하이브리드).
- `/api/v1/alerts*` — Phase 4.
- `/api/v1/export/*` — Phase 5.
- `/api/v1/reports/{id}/similar` — Phase 3.
- `/api/v1/reports/{id}`, `/api/v1/incidents/{id}`, `/api/v1/actors/{id}` detail — **D9 lock: 제외** (Phase 3).
- Sort override query param (`?sort=...`) — D11 lock: **미지원**.
- Redis 응답 캐시 (§7.7) — Phase 4 W4 튜닝.
- Materialized views — Phase 4.
- AMBER TLP row-level security — D4 defer.
- Webhook/Slack alert — Phase 4.
- Prefect flow 연결 (ingest 실제 실행) — 별도 infra PR.
- FE Pact consumer contract 작성 — PR #12.
- Node.js 20 GHA bump.
- Rate-limit block 의 `audit_log` / 신규 테이블 저장 — **D8 lock: structured log only.** Prometheus counter 는 Phase 4 관측성 PR.

---

## 4. Groups (Preliminary — 사용자 lock 후 finalize)

| Group | 목표 | 주요 파일 | 테스트 | 의존 |
|:---:|:---|:---|:---|:---|
| **A** | Pagination helper + read schemas (DTO) | `services/api/src/api/read/pagination.py`, `services/api/src/api/schemas/read.py` | `test_read_schemas.py`, `test_pagination_helper.py` | — |
| **B** | `/actors` list (소량, 가장 단순) — pipeline 검증용 첫 엔드포인트 | `services/api/src/api/routers/actors.py`, `services/api/src/api/read/repositories.py` (partial) | sqlite + real-PG actor 조회 | A |
| **C** | `/reports` list (필터 + cursor) | `services/api/src/api/routers/reports.py` (GET 추가), `read/repositories.py` (reports) | sqlite + real-PG 필터 조합 | A |
| **D** | `/incidents` list (필터 + 다중 조인) | `services/api/src/api/routers/incidents.py`, `read/repositories.py` (incidents) | sqlite + real-PG 조인 | A |
| **E** | `/dashboard/summary` (aggregator) | `services/api/src/api/routers/dashboard.py`, `read/dashboard_aggregator.py` | sqlite + real-PG 집계 | A |
| **F** | Rate limit infrastructure (slowapi + Redis + config) | `services/api/src/api/rate_limit.py`, `services/api/src/api/config.py`, `main.py` 등록 | `test_rate_limit.py` (fakeredis) | — (F는 B–E와 병렬) |
| **G** | Rate limit 적용 — 기존 라우터 (auth/login·callback, staging, POST review) | `services/api/src/api/routers/auth.py`, `staging.py`, `reports.py` | integration 429 경계 | F |
| **H** | Rate limit 적용 — 신규 read 라우터 (B–E에 decorator 부착) | actors.py, reports.py, incidents.py, dashboard.py | 포함된 integration 테스트에서 검증 | F + B/C/D/E |
| **I** | Pact producer baseline | `services/api/tests/contract/test_pact_producer.py`, `contracts/pacts/README.md`, CI stub job | — | A |
| **J** | OpenAPI surface snapshot + drift 체크 CI | `contracts/openapi/openapi.json` (commit), CI step | CI 자체 | B, C, D, E |
| **K** | Real-PG integration suite (§5.2 시나리오) | `services/api/tests/integration/test_read_real_pg.py` | 이 그룹 자체가 acceptance | B, C, D, E, F, G, H |

**실행 순서:** A → (B, C, D, E, F 병렬) → (G, H 병렬) → (I, J 병렬) → K. K는 마지막에 real-PG로 모든 앞 그룹 검증.

---

## 5. Test Strategy

### 5.1 Unit (sqlite-memory)
- DTO validation (Pydantic) — 필터 파라미터 invalid, 빈 string, invalid date, cursor 변조, ISO 3166-1 alpha-2 위반, `limit` out-of-range 등. **D12 — 전부 422 assertion**.
- Pagination helper — cursor encode/decode round-trip, malformed cursor → 422.
- 라우팅 smoke — 5개 read endpoint 등록 + verify_token dependency 부착 + default sort (D11) 반영.
- Aggregator 단위 — mock data 로 `/dashboard/summary` shape 검증 + `top_n` 경계값 (1/5/20).
- **D13 — OpenAPI examples 검증** — `/openapi.json` 의 각 endpoint/DTO 가 happy + 429 + 422 + empty 예시 4종 모두 노출.

### 5.2 Integration (real-PG, acceptance criteria)

신규 CI job 확장 (PR #10 `api-integration` 재사용). 시나리오 (최소 7 — lock):

1. **`/actors` 정상** — 3 그룹 + codename 시드 → offset list 응답 + **default sort=name ASC (D11)** 검증.
2. **`/reports` + 필터 조합** — tag 필터 / source 필터 / q (title ILIKE) / date range 각 1 시나리오 + 조합 1 시나리오. **published_at DESC 정렬 (D11)** 검증.
3. **`/incidents` + 다중 country OR semantics** — `?country=KR&country=US` 결과에 두 국가 incidents 모두 포함. **reported DESC 정렬 (D11)** 검증.
4. **`/dashboard/summary`** — 시드 고정값 대비 `total_reports`, `total_incidents`, `top_groups[0].name`, `top_groups` length == min(top_n, available) assertion. `top_n=20` max 경계 포함.
5. **Keyset cursor stability** — 동시 insert 중 next_cursor 로 페이지 넘겨도 중복 없음 + **cursor tiebreak (id DESC)** 효과 검증.
6. **Rate limit 429 + headers** — 60/min 초과 시 429 + `Retry-After` + `X-RateLimit-Remaining`. `/auth/login` 10/min 경계도 별도 케이스로 검증 (IP 기반).
7. **Invalid filter → 422 (D12)** — 빈 tag, invalid date, invalid country code, `limit=0`, `limit=201`, malformed cursor 각각 422 + FastAPI `HTTPValidationError` shape.
8. **OpenAPI surface + examples 검증 (D13)** — 5개 endpoint + DTO 가 `/openapi.json` 에 존재 + 각 endpoint 의 response examples (happy/429/422/empty) 4종 populate.

### 5.3 Contract (Pact producer)

- `pact-python` verifier harness. `contracts/pacts/` 디렉토리 비어 있으면 skip-with-ok. CI job `contract-verify` 신설 (fail-fast on contract drift once FE consumer 파일이 존재).

### 5.4 Manual verification (reproducible script 유지)

`scripts/pr11_manual_verification.py` — 5 read endpoint actual response + 1 rate-limit 429 capture. PR #10 forged-cookie 패턴 재사용.

---

## 6. Acceptance Criteria (Locked)

- [ ] 5 신규/확장 read endpoint `/openapi.json` 반영 + **D13 examples** (happy/429/422/empty) 모두 populate + `/docs` Swagger + Redoc 양쪽 수동 로드 확인.
- [ ] real-PG integration §5.2 시나리오 **1–8 all green** on `api-integration` CI job.
- [ ] `services/api` unit coverage ≥ 80% (기존 게이트).
- [ ] slowapi rate-limit 동작: `/auth/login` 11번째 요청 429 + `Retry-After` + `X-RateLimit-Remaining` 세 헤더 모두 존재.
- [ ] **D11 default sort** — 각 endpoint 기본 정렬 integration 테스트로 검증 (reports/incidents/actors).
- [ ] **D12 invalid filter** — 모든 invalid 경로가 silent ignore 없이 422 반환 (integration 시나리오 #7).
- [ ] **D8 structured log** — rate-limit block 시 JSON log 한 줄 emit (`key`, `endpoint`, `limit`, `window` 필드 포함) — test harness 에서 log capture 로 assertion.
- [ ] Dev Keycloak 세션으로 `/dashboard/summary`, `/reports?tag=...`, `/incidents?country=KR`, `/actors`, `/auth/me` 각 1회 수동 호출 후 DB 값 대조 — `docs/plans/pr11-evidence/` 에 커밋 (PR #10 evidence 패턴 재사용).
- [ ] Pact producer CI job `contract-verify` 등록 + consumer 없을 때 skip-with-ok 검증.
- [ ] OpenAPI surface drift CI step green.
- [ ] Codex 최종 라운드 CLEAN (P1×0).

---

## 7. Design Doc References

- v1.0 §5.4 — API 엔드포인트 설계 (read surface 원문).
- v2.0 §7.6 — API 엔드포인트 v2.0 추가분 (reports/review 및 확장 스코프).
- v2.0 §7.7 — 성능 전략 (p95 ≤ 300 ms / 500 ms, Redis 응답 캐시 deferred).
- v2.0 §9.2 STRIDE — DoS 완화 = rate limit.
- v2.0 §9.3 — RBAC 매트릭스 (View = 모든 역할).
- v2.0 §14 Phase 1 W5 — "핵심 API, OpenAPI 계약, Pact 베이스라인".
- v2.0 §14 Phase 2 W1–W2 — FE 레이아웃/KPI 카드 (PR #12 consumer).

---

## 8. Open Items

**모든 D1–D13 locked (2026-04-18).** 남은 open items 없음.

**실행 게이트:**
- PR #10 Codex CLEAN + merge **전에는 Group A 착수 금지** (branch 생성 포함). Plan-Locked / Execution-Gated.
- PR #10 merge 직후 `feat/p2.2-read-api` 분기 → Group A 시작.

**운영 이슈 (PR #11 lock 과 분리, 별도 PR):**
- MITRE TAXII smoke (KIDA 방화벽).
- Node.js 20 GHA bump (2026-06-02 deadline).
- `worker.data_quality.cli` `SelectorEventLoopPolicy` 패치 (Windows).
- `§10.3` staging 30-day auto-purge.
- `§10.3` `rejected` 포함 여부 정책.

**후속 PR 분리 (Phase 2 내):**
- **PR #12 Phase 2.3** — FE shell + Pact consumer contract 작성 (PR #11 producer verify harness 와 연결).
- **PR #13 Phase 2.4** — Dashboard views (§14 Phase 2 W3–W6, M2 exit = Lighthouse ≥ 90 + a11y pass).

---

## 9. Status Timeline

- **2026-04-18** Draft v1 — PR #10 Codex 대기 중 선행 초안. Decisions D1–D10 OPEN.
- **2026-04-18** 사용자 1차 리뷰 → D1–D7 accept-as-proposed, D8 structured log only (변경), D9 exclude, D10 유지 + **D11/D12/D13 추가 lock**.
- **2026-04-18** **Draft v2 → Status = Plan-Locked, Execution-Gated** (PR #10 merge 전 집행 금지).
- **2026-04-18** PR #10 Codex R1 P2 fix (`7ce6f9a`) → R2 CLEAN → merge commit `ff709dc` → `feat/p2.2-read-api` 분기. Status = **Locked** (execution-unblocked). Group A 착수 대기.
