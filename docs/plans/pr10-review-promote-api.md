# PR #10 Plan — Phase 2.1 Review / Promote API (BE only)

**Phase:** 2.1 (design doc v2.0 §14 Phase 1 W5 잔여 + §14 Phase 2 선행 — Phase 2를 4 PR로 분할한 첫 번째 PR).
**Status:** **Locked 2026-04-17** — 3라운드 사용자 리뷰 (1차 D1–D5 제안, 2차 A–E 추가 + audit 2건 모순 지적, 3차 open items 5건 lock + lock 상태 승인) 거쳐 확정. discuss-phase 별도 라운드 생략 — Group A 실행으로 직진.
**Predecessors:** PR #8 (RSS ingest → staging, `9107116`), PR #9 (TAXII ingest → staging, `e2c68f8`). 두 PR 모두 staging-only 쓰기 경로로 제한되어 있어 production 테이블로의 promote 경로가 부재한 상태.
**Successors:**
- **PR #11 (Phase 2.2)** — Read API surface (`/dashboard/summary`, `/reports`, `/incidents`, `/actors`, `/auth/me` 실제 구현) + OpenAPI 3.1 완성 + Pact baseline.
- **PR #12 (Phase 2.3)** — FE shell (§14 Phase 2 W1–W2: 라우팅, 상단바, KPI 카드, 테마, auth 연동).
- **PR #13 (Phase 2.4)** — Dashboard views (§14 Phase 2 W3–W6: D3 세계지도, ATT&CK Heatmap, Command Palette, URL state, i18n, a11y audit).

> **Phase 2 4-PR 분할 근거.** §14 Phase 2는 6주 분량(FE 중심) + Phase 1 W5 잔여("핵심 API")가 합쳐져 단일 PR이 불가. Phase 1을 1.1/1.2/1.3a/1.3b로 쪼갠 동일 패턴. PR #10은 **production write-path를 처음으로 여는 PR** — 이후 read/UI 모두 이 쓰기 경로의 정합성에 의존.

---

## 1. Goal

Deliver a **staging-review queue API** and a **promote-to-production** write path that lets an authorized reviewer approve or reject individual `staging` rows and, on approve, atomically materializes the row into the production `reports` / `sources` / `tags` / `report_tags` / `report_codenames` / `groups` / `codenames` tables. Every decision emits audit lineage to `audit_log` (actor = Keycloak `sub`, action ∈ {`STAGING_APPROVED`, `STAGING_REJECTED`, `REPORT_PROMOTED`}) and contributes to the new `review.*` DQ namespace (`review.backlog_size`, `review.avg_latency_hours`).

**Non-goals (explicit)**:
- **Frontend UI** — PR #12–#13. PR #10은 BE only. 리뷰어는 Swagger UI 또는 직접 curl로 호출.
- **Read API surface** (`/dashboard/summary`, `/reports`, `/incidents`, `/actors`) — PR #11.
- **`/auth/me` 실제 구현** — PR #11. 현재 `CurrentUser` DTO는 이미 존재하나 endpoint가 511 stub.
- **`POST /ingest/rss/run` / `POST /ingest/taxii/run` 실제 연결** — 별도 infra PR. PR #10에서는 endpoint RBAC만 admin으로 확인하는 수준 (501 유지).
- **LLM-filled staging 필드 처리** (`staging.summary`, `staging.tags_jsonb`, `staging.embedding`) — Phase 4 LLM enrichment. PR #10 promote는 NULL/empty인 LLM 필드는 그대로 NULL로 reports에 복사.
- **Rate limiting** on `/login`/`/callback` — PR #11 에 번들 (read endpoints 진입 시점이 공식 트리거).
- **Alert/webhook** on approve/reject — Phase 4 Intelligence Automation.
- **Bulk approve / bulk reject** endpoints — 후속. PR #10은 single-item 리뷰만.
- **Promote 이력 dedicated 테이블** (e.g., `staging_review_events`) — `audit_log` + `staging.status`/`reviewed_at`/`decision_reason`로 충분히 재구성 가능. 별도 테이블은 과도.
- **Auto-promote / confidence-threshold-based auto-approve** — Phase 4.
- **Review decision 수정 / 번복** — `rejected` → `pending` 재투입은 admin-only 별도 action. PR #10에서는 미지원 (후속).
- **§10.3 staging 30일 auto-purge 구현 / `rejected` 포함 여부 정책** — PR #10 범위 밖, follow-up TODO 유지 (§8 #1 lock-as-defer).
- **Node.js 20 GHA bump** — 2026-06-02 deadline. 별도 cleanup PR.

---

## 2. Decisions to Lock

### 2.1 User-Specified (1차, 5)

| ID | Question | Proposed Position | Rationale |
|:---:|:---|:---|:---|
| **D1** | **Review/promote API 범위**: read-only vs approve/reject 전체? | **전체 묶음.** Three endpoints: (1) `GET /api/v1/staging/review?status=pending&cursor=...&limit=50` → `{items: [StagingReviewItem], next_cursor}`. 정렬은 **`created_at ASC, id ASC` FIFO 고정** (§8 #3 lock). (2) `GET /api/v1/staging/{id}` → `StagingDetail` (원본 + source 정보 + 기존 reports 중복 매칭 힌트). (3) `POST /api/v1/reports/review/{id}` body=`{decision: "approve"|"reject", notes?: string, decision_reason?: string}`. `notes`는 두 decision 모두 optional, **`audit_log.diff_jsonb.notes`로만 저장 — staging 컬럼 없음** (§8 #4 lock). `decision_reason`은 **reject에서 필수 (비문자열/빈 문자열 422)**, approve에서는 무시 — `staging.decision_reason` 컬럼에 저장. 응답 body는 **최소형 `{staging_id, report_id: int|null, status: "promoted"|"rejected"}`** (§8 #2 lock) — reject 시 `report_id=null`. approve = production writes 후 `staging.status='promoted'` + `promoted_report_id=<new>` + `reviewed_by/at`; reject = `staging.status='rejected'` + `decision_reason` 저장 + `reviewed_by/at` (per C). | read-only만 있으면 큐만 쌓이고 실제 쓰기 경로 검증 불가. 같은 PR에서 엔드-투-엔드 완결해야 operational 가치 발생. |
| **D2** | **UI 포함 vs 분리** | **분리 — PR #10은 BE only.** FE는 PR #12–#13. 리뷰어는 Swagger `/docs` (dev) 또는 curl로 테스트. | 리뷰 화면은 운영 내부 화면이지 대시보드(§14 Phase 2 FE)가 아님. Read API 미완성 상태에서 FE를 먼저 붙이면 재작업. |
| **D3** | **ON CONFLICT refactor 대상 구체화** | **Promotion path가 건드리는 production writes 전체를 `INSERT ... ON CONFLICT` 패턴으로 전환.** 대상 표는 §2.3 참고. `reports.sha256_title` 하나로 축소하지 않음 — 실제 natural key는 테이블별로 상이. bootstrap 경로의 `upsert.py` check-then-insert는 이 PR에서 **건드리지 않음** (트리거가 아직 단일 writer) — PR #10의 promote 경로만 ON CONFLICT로 전환. | bootstrap은 여전히 single-threaded one-shot CLI이므로 race 없음. promote는 **다수 reviewer 동시 호출 가능성 + 동일 URL의 다른 staging row 중복 promote 가능성**이 모두 존재하므로 ON CONFLICT 필수. |
| **D4** | **Audit/DQ 재사용 + review.\* 메트릭 범위** | **Audit**: 신규 action **2종** — `STAGING_REJECTED` (reject path 단일 이벤트, entity=`staging`, entity_id=staging_id) + `REPORT_PROMOTED` (approve path 단일 이벤트, entity=`reports`, entity_id=new_report_id). **approve에 `STAGING_APPROVED`는 emit하지 않음** — `REPORT_PROMOTED.diff_jsonb`에 `{from_staging_id, attached_existing: bool, reviewer_notes: notes\|null, report_snapshot}` 을 담아 승인 사실 전부 encoding. 중복 이벤트 제거로 audit_log 부피도 절반. actor = Keycloak `sub` (세션의 `CurrentUser.sub`). 기존 `worker.bootstrap.audit` helper는 worker-side — **API-side 신규 `services/api/src/api/audit.py`** 생성 (경량 helper, AuditBuffer 불필요 — 요청 단위 1 이벤트만 emit). <br/>**DQ (축소)**: 2개만. `review.backlog_size` (COUNT `status='pending'`, warn > 500), `review.avg_latency_hours` (AVG `EXTRACT(EPOCH FROM reviewed_at-created_at)/3600` for decided rows, warn > 72). **`review.approval_rate`는 PR #10에서 제외** — 샘플 크기 적을 때 운영 오해 소지. 후속 PR에서 충분한 decision 누적 후 추가. <br/>**실행 시점 lock**: `review.*` 메트릭은 **per-request emit이 아님** — 엔드포인트 핸들러 내에서 DQ 계산을 하지 않는다. `worker.data_quality` CLI의 기존 manual/CI DQ run 경로로만 쿼리 (e.g., `python -m worker.data_quality run --expectation review_backlog_size`). PR #10의 acceptance는 해당 CLI를 한 번 실행해 `dq_events`에 row가 들어가는 것을 확인하는 수준. | PR #10은 운영 KPI가 아니라 core write-path PR. DQ는 backlog + latency의 기본 observability만. Approval rate는 운영 대시보드 / 후속 PR (Phase 3 Analytics or 별도) 으로 연기. Per-request emit을 하면 핸들러 지연 + COUNT 쿼리가 리뷰어 UX에 체감됨 — 전통적 DQ run (batch) 패턴 유지. |
| **D5** | **OIDC 역할 경계 + admin endpoints** | §9.3 RBAC 매트릭스 그대로 적용. **`GET /staging/review` + `GET /staging/{id}` + `POST /reports/review/{id}`** = `analyst / researcher / admin`. **admin-only** (PR #10 범위 내): 없음 (모든 리뷰 action은 analyst/researcher도 수행). admin 전용 신규 endpoint는 PR #10에서 추가하지 않음 — `/ingest/*/run` 등은 이미 admin-only 501 stub으로 존재. <br/>**`require_role`은 이미 variadic** (`def require_role(*allowed_roles: str)`) — 코드 수정 불필요, 호출 패턴만 `Depends(require_role("analyst", "researcher", "admin"))` 로 확립. | §9.3 "Human review 승인 = analyst/researcher/admin" 그대로. admin 전용 신규 endpoint를 이 PR에서 만들면 scope creep. RBAC helper 확장 불필요 — verification 결과 이미 variadic. |

### 2.2 User-Specified (2차 추가, 5)

| ID | Item | Proposed Position | Rationale |
|:---:|:---|:---|:---|
| **A** | **Promote 트랜잭션 경계** | **단일 트랜잭션.** `POST /reports/review/{id}` 핸들러 내부: `async with session.begin()` 하나로 묶음. 순서: (1) `SELECT staging WHERE id=? FOR UPDATE` — 같은 row 재승인 방지 + B의 동시 승인 경쟁 차단. (2) `INSERT INTO sources ... ON CONFLICT (name) DO NOTHING RETURNING id` (or existing id via fallback SELECT). (3) `INSERT INTO reports ... ON CONFLICT (url_canonical) DO NOTHING RETURNING id`. 결과가 empty면 기존 reports row의 id를 fallback SELECT (이때 `attached_existing=true`). (4) `INSERT INTO tags ... ON CONFLICT DO NOTHING` + `INSERT INTO report_tags ... ON CONFLICT DO NOTHING` (tags_jsonb가 NULL이면 skip). (5) 필요 시 `groups`/`codenames`/`report_codenames` (Phase 2 스테이징에는 LLM-filled tags가 아직 없으므로 실질 no-op — 스켈레톤만 구현). (6) `UPDATE staging SET status='promoted', promoted_report_id=?, reviewed_by=?, reviewed_at=now() WHERE id=? AND status='pending'` — 조건부 UPDATE. (7) `INSERT INTO audit_log (actor, action='REPORT_PROMOTED', entity='reports', entity_id=<report_id>, diff_jsonb={from_staging_id, attached_existing, reviewer_notes: notes\|null, report_snapshot})` — **단일 이벤트** (D4의 audit 축소와 일치). (8) commit. **Any step 실패 → rollback 전체** (staging 상태 포함 원복). **Reject 경로**는 production write 없이 `UPDATE staging SET status='rejected', decision_reason=?, reviewed_by=?, reviewed_at=now() WHERE id=? AND status='pending'` + `INSERT INTO audit_log (actor, action='STAGING_REJECTED', entity='staging', entity_id=<staging_id>, diff_jsonb={decision_reason, reviewer_notes: notes\|null})` + commit. | 다단 production write를 partial 반영하면 보고서 반쪽짜리 + staging 상태 불일치로 복구 난이도 급상승. DB-level 단일 트랜잭션이 원자성 보장 가장 확실. savepoint는 불필요 (전체 실패 시 전체 롤백이 의도). |
| **B** | **동시 승인 경쟁 처리** | **`SELECT ... FOR UPDATE` + 조건부 UPDATE 이중 방어.** 핸들러 시작 시 `SELECT id, status FROM staging WHERE id=? FOR UPDATE` — 이 row에 대한 다른 트랜잭션의 동시 접근 블록. 이후 상태 검증: `status != 'pending'`이면 409 Conflict 반환 (이미 결정됨). step 6의 UPDATE에도 `WHERE id=? AND status='pending'` 조건부로 이중 안전망 — UPDATE의 RETURNING id가 empty면 race로 판단하여 rollback + 409 반환. 실패 응답 body: `{error: "already_decided", current_status: "promoted"|"rejected", decided_by, decided_at}` — **현재 promote 경로의 실제 상태 전이는 `pending → promoted|rejected` 2-way만 가능**. staging CHECK enum의 `approved` / `error` 값은 미래용 예약어(auto-promote workflow 등)이며 PR #10 endpoint는 사용하지 않으므로 응답 enum에서 제외. | Postgres `FOR UPDATE` + 조건부 UPDATE는 Serializable 격리까지 안 가도 single-winner 보장 충분. 409 Conflict가 HTTP semantics 정확. 응답 enum을 실제 도달 가능 상태로 좁혀 클라이언트가 예상치 못한 값을 처리하지 않도록 제약. |
| **C** | **Reject semantics** | **Soft reject, 재승격은 admin action 필요.** `staging.status='rejected'` + 신규 `staging.decision_reason` text 컬럼에 사유 저장 (**reject 시 필수**, 비문자열/빈 문자열은 422). `reviewed_by/at` 동일하게 채움. `notes` (optional)는 `audit_log.diff_jsonb.reviewer_notes`에만 저장 — staging 컬럼 추가 없음 (§8 #4 lock). **재검토 / `rejected` → `pending` 복원은 PR #10에서 미지원** — 후속 admin endpoint (`PATCH /staging/{id}/status` with admin-only, audit `STAGING_REOPENED`) 으로 분리. **30일 auto-purge(§10.3)는 PR #10 범위 밖 — follow-up TODO 유지** (§10.3 해석은 후속 운영 PR에서 재논의). | Hard-delete는 audit trail 손실. Soft reject + 별도 reopen action = 결정 권한이 명확(admin-only reopen)하고 audit reconstruction 가능. 재검토 UX가 실제 필요해지면 후속에서 조합. Notes를 staging 컬럼에 저장하지 않는 이유: notes는 리뷰어 내부 메모 성격이라 entity data보다 audit 맥락이 적절. 컬럼을 하나 더 늘리면 auto-purge / migration / DTO 변경 포인트만 증가. |
| **D** | **OpenAPI / Pact contract** | **OpenAPI 3.1 포함, Pact는 PR #11부터.** FastAPI의 auto-generated `/openapi.json`이 이미 존재 (dev만). 새 endpoint 3종 + DTO 스키마를 Pydantic `BaseModel`로 정의하면 자동 포함. `/docs` Swagger UI 에서 수동 테스트 가능. **Pact** (consumer-driven contract test)는 FE consumer가 생성되는 PR #12에서 베이스라인 도입. PR #10은 서버 스키마만 안정화. | OpenAPI는 단독 cost 낮음(Pydantic BaseModel이 자동 스키마). Pact는 consumer 없이는 의미 없음 — FE shell(PR #12) 기동 시 BE-FE 계약 매칭이 실제 트리거. |
| **E** | **Real-PG integration test 필수화** | **Real-PG integration test를 acceptance criteria로 lock.** PR #8/9의 sqlite-memory 중심 테스트는 ON CONFLICT / `FOR UPDATE` / race / transaction rollback 세 축 모두 검증 불가. 신규 CI job **`api-integration`** 생성 (기존 `data-quality-tests` 확장 대신 분리 — Python service 경계가 다름 + job 이름 검색성). 서비스 컨테이너 postgres:16 + pgvector extension, alembic upgrade head 후 pytest `-m integration` 실행. 테스트 범위 (최소): (1) approve happy path — production writes + staging 상태 + audit_log 1 row. (2) reject — staging 상태 + decision_reason 저장 + audit_log 1 row. (3) 동일 url_canonical 이미 reports에 존재 → ON CONFLICT 경로 타고 기존 id 매칭 + staging은 `promoted` 확정. (4) 동시 approve 시뮬레이션 — 2개의 asyncio 태스크가 동일 staging id에 동시 POST, 1개만 성공 1개는 409. (5) step 중간 실패 시뮬레이션 — DB 오류 주입 후 staging 상태가 `pending` 그대로 유지 (롤백 검증). **Acceptance criteria**: 위 5 시나리오 green. sqlite-memory 테스트는 보조 용도로만 허용 (스키마 검증 / DTO validation). | ON CONFLICT, row locking, transaction race, pgvector-typed column은 sqlite에서 재현 불가. PR #10은 처음으로 production write-path를 여는 PR — 여기서 real-PG 검증이 없으면 prod에서 첫 reviewer action으로 data corruption 가능. CI job 분리는 실패 격리 + 로그 가독성. |

### 2.3 Promote Path ON CONFLICT 대상 표 (D3 구체화)

| 테이블 | Natural key (UNIQUE) | 전략 | Fallback on conflict |
|:---|:---|:---|:---|
| `sources` | `name` (UNIQUE) | `INSERT ... ON CONFLICT (name) DO NOTHING RETURNING id` | empty이면 `SELECT id FROM sources WHERE name=?` |
| `reports` | `url_canonical` (UNIQUE via `uq_reports_url_canonical`) | `INSERT ... ON CONFLICT (url_canonical) DO NOTHING RETURNING id` | empty이면 `SELECT id FROM reports WHERE url_canonical=?` — **기존 id 재사용하고 staging은 그 id로 promoted 마킹** (duplicate staging 방어). **INSERT도 UPDATE도 하지 않는 "첨부" semantics**. |
| `tags` | `name` (UNIQUE) | `INSERT ... ON CONFLICT (name) DO NOTHING RETURNING id` | empty이면 `SELECT id FROM tags WHERE name=?` |
| `report_tags` | 복합 PK `(report_id, tag_id)` | `INSERT ... ON CONFLICT (report_id, tag_id) DO NOTHING` | — (idempotent, return 불필요) |
| `report_codenames` | 복합 PK `(report_id, codename_id)` | `INSERT ... ON CONFLICT (report_id, codename_id) DO NOTHING` | — |
| `groups` | `name` (UNIQUE) | `INSERT ... ON CONFLICT (name) DO NOTHING RETURNING id` | empty이면 `SELECT id FROM groups WHERE name=?` |
| `codenames` | `name` (UNIQUE) | `INSERT ... ON CONFLICT (name) DO NOTHING RETURNING id` | empty이면 `SELECT id FROM codenames WHERE name=?` |
| `staging` | `id` (PK, 이미 알려진 값) | 조건부 `UPDATE` with `WHERE id=? AND status='pending'` (per B) | RETURNING id empty이면 race → rollback + 409 |
| `audit_log` | (없음 — append-only) | 단순 INSERT | — |
| `sha256_title` | **UNIQUE 아님** (fallback lookup only, source-scoped) | PR #10에서 사용하지 않음 | bootstrap 경로의 title-hash fallback은 ingestion path 특화이고, promote path는 이미 `staging.url_canonical` 기준 dedup이 끝난 상태라 title-hash fallback 불필요. |

**Scope boundary**: bootstrap(`worker.bootstrap.upsert`)은 check-then-insert 그대로 유지 (single writer). PR #10은 **API-side promote 경로만** ON CONFLICT로 구현 — 두 경로 공존 기간 동안은 `reports.url_canonical` UNIQUE 제약이 최종 dedup 보증.

**LLM-filled scope (Phase 4 지연)**: Phase 2에서 `staging.tags_jsonb` / `staging.summary` / `staging.embedding` 은 모두 NULL (RSS/TAXII가 채우지 않음). 따라서 `tags` / `report_tags` / `groups` / `codenames` / `report_codenames` 쓰기는 **스켈레톤 코드 구현 + no-op branch 테스트**만 수행 — 실제 데이터로는 Phase 4 enrichment 랜딩 후 실행됨. `summary`도 NULL → `reports.summary` NULL로 복사. `embedding`도 NULL → `reports.embedding` NULL.

---

## 3. Scope

### In scope

- **Migration `0008_staging_decision_reason`** — `ALTER TABLE staging ADD COLUMN decision_reason TEXT NULL`. **컬럼은 `decision_reason` 하나만 추가** — `notes`는 컬럼 없이 `audit_log.diff_jsonb.reviewer_notes`에 저장 (§8 #4 lock). `tables.py` SQLAlchemy mirror 업데이트. Migration down = `DROP COLUMN decision_reason`. Round-trip CI에서 검증.
- **`services/api/src/api/routers/staging.py`** (신규) — `GET /staging/review` 목록 (cursor 페이지네이션) + `GET /staging/{id}` 상세. 둘 다 `Depends(verify_token)` + `Depends(require_role("analyst","researcher","admin"))`.
- **`services/api/src/api/routers/reports.py`** (확장) — `POST /reports/review/{id}` 501 stub → 실제 구현. 같은 RBAC.
- **`services/api/src/api/promote/`** (신규 패키지):
  - `__init__.py`
  - `service.py` — `async def promote_staging_row(session, staging_id, current_user) -> PromoteResult` 오케스트레이션. A의 8단계 구현.
  - `repositories.py` — 각 테이블별 `upsert_*_on_conflict(session, ...)` 함수. §2.3 전략 그대로. sqlite-memory fallback에서는 ON CONFLICT 없이 check-then-insert로 polyfill (테스트 편의).
  - `errors.py` — `StagingAlreadyDecidedError`, `PromoteFailedError` 도메인 예외 → HTTPException 409/500 매핑.
- **`services/api/src/api/schemas/review.py`** (신규) — Pydantic DTO: `StagingReviewItem`, `StagingDetail`, `ReviewDecisionRequest` (discriminated union on `decision` literal; `decision_reason` validator — reject 시 필수/non-empty, approve 시 무시), `ReviewDecisionResponse = {staging_id: int, report_id: int | None, status: Literal["promoted","rejected"]}`, `AlreadyDecidedError = {error: "already_decided", current_status: Literal["promoted","rejected"], decided_by: str, decided_at: datetime}`.
- **`services/api/src/api/audit.py`** (신규) — 경량 API-side audit helper. `async def write_review_audit(session, actor, action, entity, entity_id, diff)`. `worker.bootstrap.audit` 의 패턴은 **참조**하되 AuditBuffer 없이 단발성 INSERT (요청당 1–2 이벤트).
- **`services/api/src/api/routers/staging.py`** (목록 엔드포인트) — 리뷰어 대시보드의 pending queue. cursor = `(created_at, id)` 복합 (stable 페이지네이션). default `limit=50`, max `200`.
- **`services/worker/src/worker/data_quality/expectations/review_metrics.py`** (신규) — 2개 expectation: `review_backlog_size` (warn > 500), `review_avg_latency_hours` (warn > 72). `ALL_EXPECTATION_NAMES`에 추가. **실행 경로는 기존 `worker.data_quality` CLI manual/CI run만** — API 핸들러에서 per-request 호출하지 않음 (D4 lock).
- **`services/api/tests/` 확장**:
  - `tests/unit/test_review_schemas.py` — DTO validation.
  - `tests/unit/test_promote_repositories_sqlite.py` — sqlite-memory polyfill 경로.
  - `tests/integration/test_promote_real_pg.py` — **E 필수 5 시나리오**. `pytest.mark.integration` 마커.
- **`.github/workflows/ci.yml`** 신규 job `api-integration` — services/api 경로에서 pytest `-m integration`, postgres:16 + pgvector, alembic upgrade head 전처리.
- **OpenAPI 스키마** — Pydantic auto-generated. 수동 `/docs` 검증 acceptance에 포함.
- **Follow-up TODO 클리어**: "Check-then-insert 레이스 컨디션 (promote path 트리거)" — PR #10에서 promote path만 ON CONFLICT 전환으로 클리어. bootstrap은 여전히 별도 트래커 유지.

### Out of scope (explicit)

- **Bootstrap `worker.bootstrap.upsert` ON CONFLICT 전환** → 별도 PR (트리거: 멀티 writer 도입 시).
- **`/ingest/rss/run`, `/ingest/taxii/run` 501 stub 실제 구현** → 별도 infra PR.
- **Read API surface** (`/reports`, `/incidents`, `/actors`, `/dashboard/summary`, `/auth/me` 실제) → PR #11.
- **FE 구현** → PR #12–#13.
- **Rate limiting** → PR #11 (read endpoint 진입 시점).
- **Bulk review** (approve/reject 일괄) → 후속 operational PR.
- **Reopen rejected** (`rejected` → `pending` admin action) → 후속.
- **Auto-promote based on confidence threshold** → Phase 4.
- **`review.approval_rate` DQ 메트릭** → 후속 (샘플 누적 후).
- **Alert/webhook on promote** → Phase 4.
- **Prefect flow 연결** → 별도 infra PR.
- **Node.js 20 GHA bump** → 별도 (2026-06-02 deadline).
- **Promote history dedicated 테이블** → 불필요 (audit_log + staging 상태로 복원 가능).

---

## 4. Groups (Preliminary — discuss-phase 후 재분해)

| Group | 목표 | 주요 파일 | 테스트 | 의존 |
|:---:|:---|:---|:---|:---|
| **A** | Migration 0008 + `tables.py` mirror | `db/migrations/versions/0008_staging_decision_reason.py`, `services/worker/src/worker/bootstrap/tables.py` | `db-migrations` CI job 그대로 round-trip 검증 + 신규 컬럼 presence assertion | — |
| **B** | Pydantic DTO 정의 | `services/api/src/api/schemas/review.py` | `test_review_schemas.py` | A |
| **C** | Promote repositories (ON CONFLICT 전략 per §2.3) | `services/api/src/api/promote/repositories.py`, `services/api/src/api/promote/errors.py` | `test_promote_repositories_sqlite.py` (sqlite polyfill) | A |
| **D** | Promote service orchestration (A 8단계 + B 동시성 + C soft reject) | `services/api/src/api/promote/service.py`, `services/api/src/api/audit.py` | `test_promote_service_sqlite.py` | B, C |
| **E** | Staging read endpoints | `services/api/src/api/routers/staging.py`, `services/api/src/api/main.py` (라우터 등록) | `test_staging_routes.py` (mocked session) | B |
| **F** | `POST /reports/review/{id}` 엔드포인트 (511 stub 교체) | `services/api/src/api/routers/reports.py` | `test_review_route.py` (mocked session) | B, D |
| **G** | DQ `review.*` 메트릭 2종 | `services/worker/src/worker/data_quality/expectations/review_metrics.py` | `test_review_metrics.py` | A |
| **H** | **Real-PG integration test** (E 필수 5 시나리오) + 신규 CI job | `services/api/tests/integration/test_promote_real_pg.py`, `.github/workflows/ci.yml` | 이 그룹 자체가 acceptance | A, C, D, E, F |

**실행 순서**: A → B → (C, E, G 병렬) → D → F → H. H는 마지막에 real-PG로 모든 앞 그룹 검증.

---

## 5. Test Strategy

### 5.1 Unit (sqlite-memory)
- DTO validation (Pydantic) — invalid decision literal, missing fields, notes 길이 제한 등.
- Repository polyfill 경로 (sqlite는 ON CONFLICT 일부만 지원하므로 `INSERT OR IGNORE` fallback 적용) — 테스트 편의용. sqlite 테스트는 "문법 검증" 수준까지만 인정.

### 5.2 Integration (real-PG, **acceptance criteria**)
`api-integration` 신규 CI job. 서비스 컨테이너 postgres:16 + pgvector/pg_trgm extension. alembic upgrade head 후 `pytest -m integration`. **최소 5 시나리오 green 필수**:

1. **Approve happy path** — 신규 `staging` row → POST approve → `reports` 신규 1 row, `sources` 신규/기존 1 row, `staging.status='promoted'`, `promoted_report_id` 채워짐, **`audit_log` 단 1 row (`action=REPORT_PROMOTED`, `diff_jsonb.attached_existing=false`)** — `STAGING_APPROVED`는 emit하지 않음을 적극 검증 (D4/A lock).
2. **Reject** — 신규 `staging` row → POST reject with `decision_reason` → `staging.status='rejected'`, `decision_reason` 저장, `audit_log` 1 row (`action=STAGING_REJECTED`, `diff_jsonb.reviewer_notes=<notes or null>`). `decision_reason` 누락/빈 문자열 시 422 검증 추가.
3. **Duplicate url_canonical** — `reports`에 이미 동일 `url_canonical` 존재 → POST approve → 신규 reports INSERT 없음, staging은 기존 report id로 `promoted` 마킹, `audit_log` 1 row (`action=REPORT_PROMOTED`, **`diff_jsonb.attached_existing=true`** — 재사용 사실 명시).
4. **Concurrent approve race** — 2개의 asyncio 태스크가 동일 staging id에 동시 POST → 1개 성공 (200 + promoted), 1개 409 Conflict with `current_status='promoted'` response body. 응답 enum에 `approved`가 노출되지 않음을 assertion.
5. **Mid-transaction failure rollback** — 예컨대 `sources` INSERT 후 `reports` INSERT에서 deliberate DB 예외 주입 → 전체 rollback, staging `status='pending'` 유지, audit_log row 없음.

### 5.3 OpenAPI 수동 검증
acceptance에 `/docs` Swagger UI 로드 + 3 endpoint schema presence + 1회 actual `POST /reports/review/{id}` 호출 (locally with dev Keycloak) 포함. 실패 시 블로커.

---

## 6. Acceptance Criteria (Lock 기준)

- [ ] 5 integration 시나리오 (§5.2) all green on real-PG CI.
- [ ] Unit 테스트 coverage (services/api) ≥ 80% (기존 게이트 유지).
- [ ] `db-migrations` CI job 0008 round-trip green.
- [ ] 3 신규 endpoint OpenAPI 스키마 `/openapi.json`에 반영 + `/docs` 수동 로드 확인.
- [ ] Dev Keycloak 세션으로 actual approve + reject 각 1회 실행 후 DB 상태 수동 검증 (Windows `psql` or `docker exec`) — 스크린샷/로그 PR body에 첨부.
- [ ] `review.backlog_size` + `review.avg_latency_hours` 메트릭이 `dq_events`에 emit 확인 — `python -m worker.data_quality run` 1회 수동 실행 후 `SELECT * FROM dq_events WHERE expectation LIKE 'review.%'` 결과 2 rows (per-request emit 없음을 코드 검토로 재확인).
- [ ] Codex 최종 라운드 CLEAN (P1×0).
- [ ] Follow-up TODO "promote path check-then-insert 레이스" 클리어 상태로 PR body에 명시.

---

## 7. Design Doc References

- §3.4 LLM 보조 정규화 / staging 큐 — `reviewed_by/at/status` 의 의도 (v1.0에 없던 신규).
- §7.6 API 엔드포인트 v2.0 — `/reports/review/{id}` 정의.
- §9.3 RBAC 매트릭스 — Human review = analyst/researcher/admin.
- §10.3 데이터 리텐션 — staging 30일 auto-purge (현재 미구현, `rejected` 포함 여부 follow-up).
- §11 관측성 — audit_log 2년 리텐션.

---

## 8. Open Items for Discuss-Phase

**모든 1차 open items는 이미 lock 처리됨.** 사용자 2차 리뷰에서 1–5 전부 결정 — 인라인 편입 완료:

1. ~~Reject된 staging의 30일 auto-purge~~ → **PR #10 범위 밖, follow-up TODO 유지** (§2.2 C, §10 Follow-up 참조). `rejected` 포함 여부는 별도 운영 PR에서 재논의.
2. ~~Approve 응답 body~~ → **Lock**: 최소형 `{staging_id, report_id: int|null, status: "promoted"|"rejected"}` (§2.1 D1, §3 DTO).
3. ~~`GET /staging/review` 정렬~~ → **Lock**: `ORDER BY created_at ASC, id ASC` FIFO (§2.1 D1). DQ `review.avg_latency_hours` 와 일관.
4. ~~`notes` vs `decision_reason` 저장 위치~~ → **Lock**: `decision_reason`은 `staging` 컬럼 (마이그레이션 0008), `notes`는 audit-only (`audit_log.diff_jsonb.reviewer_notes`). `staging`에 `notes` 컬럼 추가하지 않음 (§2.1 D1, §2.2 C, §3 migration).
5. ~~`api-integration` CI job required check~~ → **Lock**: required. production write path 검증 미통과 PR은 머지 불가 (§6 acceptance).

**남은 진짜 open items**: 없음. discuss-phase는 **"이 lock 세트를 최종 확정"** 한 문답 라운드만 수행하고 Group A 실행으로 넘어감.

---

## 9. Status Timeline

- **2026-04-17** Draft v1 created after Phase 2 4-PR 분할 + D1–D5 + A–E 2차 추가 사용자 승인.
- **2026-04-17** Draft v2 — 사용자 3차 리뷰 (audit 의미 충돌 2건 + notes/decision_reason 조기 lock + open items 1–5 lock) 반영.
- **2026-04-17** Plan status → **Locked**. Discuss-phase 별도 라운드 생략 (사용자 4차 승인: "지금 lock 상태로 Group A부터 시작").
- **2026-04-17** Groups A 실행 시작.
