# Worker Scaffold

Prefect 2 기반 플로우 골격이다. 실제 수집기와 LLM enrichment는 아직 구현하지 않는다.

## Included

- Prefect flow entrypoint
- bootstrap / ingest / enrich / anomaly placeholder flows
- health-style CLI entry

## Next Tasks

- RSS/Atom/TAXII 소스별 flow 분리
- DLQ/재시도 정책 연결
- staging-review-production 게이트 구현
- Slack/webhook 알림 sink 추가
- 배치/스케줄 정의

## Data Quality Gate (Phase 1.2 / PR #7)

`worker.data_quality` 패키지는 Bootstrap ETL로 적재된 스키마에 대해 11개의
expectation(4 value_domain + 2 year_range + 2 referential_integrity +
2 null_rate + 1 dedup_rate)을 실행하고 결과를 `dq_events` 테이블, stdout,
선택적 JSONL 파일에 기록한다. 전체 결정 기록(D1–D13)과 각 expectation의
threshold는 `docs/plans/pr7-data-quality.md`에 있다.

### CLI 호출

```bash
# 기본 실행 — 로컬 bootstrap 스키마에 DQ gate 적용
python -m worker.data_quality check \
  --database-url postgresql+psycopg://postgres:postgres@localhost:5432/dprk_cti

# 특정 bootstrap run과 lineage 공유 — 같은 run_id 지정
python -m worker.data_quality check \
  --database-url "$DATABASE_URL" \
  --run-id 01JGXXXXXXXXXXXXXXXXXXXX \
  --workbook-sha256 a9b3c0d1e2f3...

# JSONL mirror artifact 생성 (CI용)
python -m worker.data_quality check \
  --database-url "$DATABASE_URL" \
  --report-path artifacts/dq_report.jsonl \
  --fail-on error

# 환경 변수 기반 호출 — DQ_DATABASE_URL이 --database-url fallback
DQ_DATABASE_URL="$DATABASE_URL" python -m worker.data_quality check

# report 서브커맨드 (PR #7에서는 stub, exit code 3 반환)
python -m worker.data_quality report --since 1d
```

### 플래그 요약

| 플래그 | 필수 | 기본값 | 용도 |
|:---|:---:|:---|:---|
| `--database-url` | O | `$DQ_DATABASE_URL` fallback | 적재 완료된 Postgres의 async SQLAlchemy URL. DQ gate는 스키마를 provisioning 하지 않음. |
| `--run-id` |  | 새 uuid7 자동 생성 | `dq_events.run_id`에 쓰일 UUID. `audit_log.diff_jsonb.meta.run_id`와 맞추면 lineage join 가능. |
| `--workbook-sha256` |  | 없음 | 사람이 읽을 pre-run 헤더 전용. `dq_events`에 저장되지 않음. |
| `--aliases-path` |  | repo `data/dictionaries/aliases.yml` | D8 referential integrity의 truth source. 설치 wheel 환경에서는 패키지 내 fallback. |
| `--report-path` |  | 없음 (JSONL sink 비활성) | Decimal-exact JSONL mirror 파일 경로. CI artifact 업로드에 사용. |
| `--fail-on` |  | `error` | 실패 threshold: `error` / `warn` / `none`. Sink 실패는 정책과 무관하게 항상 실패. |

### Exit code

| 코드 | 의미 | 해석 |
|:---:|:---|:---|
| 0 | OK | `--fail-on` 기준으로 worst severity가 임계 이하이고 모든 sink 쓰기 성공. |
| 1 | CONFIG_ERROR | `--database-url` 누락, UUID 파싱 실패, aliases 로드 실패, engine 생성 예외. |
| 2 | CHECK_FAILED | expectation이 threshold 초과 OR sink 실패. Infra 실패는 `--fail-on none`으로도 억제 불가. |
| 3 | REPORT_STUB | `report` 서브커맨드 호출. PR #7은 argparse 표면만 제공. |

### dq_events 조회 예제

```sql
-- 특정 run의 failure만
SELECT expectation, severity, observed, threshold, observed_rows, detail_jsonb
FROM dq_events
WHERE run_id = '01JGXXXXXXXXXXXXXXXXXXXX'
  AND severity IN ('warn', 'error')
ORDER BY severity DESC, expectation;

-- 최근 24시간 error 이벤트만
SELECT observed_at, run_id, expectation, observed, threshold
FROM dq_events
WHERE severity = 'error'
  AND observed_at >= NOW() - INTERVAL '24 hours'
ORDER BY observed_at DESC;

-- bootstrap run과 DQ run을 lineage join
SELECT
  a.actor,
  a.action,
  a.entity,
  d.expectation,
  d.severity,
  d.observed_rows
FROM audit_log a
JOIN dq_events d
  ON (a.diff_jsonb #>> '{meta,run_id}')::uuid = d.run_id
WHERE a.action = 'etl_run_started'
  AND d.severity = 'error';
```

### D8 forward-violation 복구 플레이북

D8의 `groups.canonical_name.forward_check` expectation은 DB에 저장된
`groups.canonical_name` 중 `aliases.yml`의 canonical set에 없는 이름을
찾는다. 실패는 "이 검사가 잡으려던 바로 그 상황"으로, normalize 단계가
알 수 없는 그룹 이름을 통과시켰다는 뜻이다.

1. **offending rows 식별**:

   ```sql
   SELECT expectation, detail_jsonb
   FROM dq_events
   WHERE expectation = 'groups.canonical_name.forward_check'
     AND severity = 'error'
   ORDER BY observed_at DESC
   LIMIT 1;
   ```

   `detail_jsonb.offending_db_canonicals` 배열에 DB에는 존재하지만
   `aliases.yml`의 canonical set에는 없는 이름 목록이 들어있다.
   (`detail_jsonb.db_canonical_count` / `yaml_canonical_count` 는
   양쪽 집합 크기를 함께 기록해 참고용으로 남긴다.)

2. **원인 분류** — `offending_db_canonicals` 의 각 엔트리에 대해:
   - **오타/변형**: `aliases.yml`의 `groups:` 섹션에 alias로 추가.
   - **새 그룹**: `aliases.yml`의 `groups:` 섹션에 canonical entry 신설.
   - **이름 표기 변경(예: Lazarus → Lazarus Group)**: canonical 이름 자체를
     수정하고 이전 표기를 alias로 이관.

3. **재실행**:

   ```bash
   # bootstrap은 재실행 후 멱등 (url_canonical UNIQUE + upsert)
   python -m worker.bootstrap \
     --workbook path/to/workbook.xlsx \
     --database-url "$DATABASE_URL"

   # DQ 재검증
   python -m worker.data_quality check \
     --database-url "$DATABASE_URL"
   ```

4. **확인**: 같은 쿼리로 이번 run의 `groups.canonical_name.forward_check`
   row가 `severity = 'pass'`인지 재확인. `pass` 결과에는
   `offending_db_canonicals` 키가 포함되지 않고 `db_canonical_count` /
   `yaml_canonical_count` 만 남는다.

Reverse check (`groups.canonical_name.reverse_check`, severity `warn`)는
반대 방향 — `aliases.yml`에는 있는데 DB에는 안 나타나는 canonical
이름이다. 이름 목록은 `detail_jsonb.unused_yaml_canonicals` 에 담기며,
blocker가 아니라 "dictionary가 실제 데이터를 앞서 나감"을 알리는 신호라
CI를 차단하지 않는다.
