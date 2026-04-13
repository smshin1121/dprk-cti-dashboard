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
