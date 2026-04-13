# Database Scaffold

PostgreSQL 16 기준 초기 스키마와 마이그레이션 골격이다.

## Included

- Alembic config
- pgvector / pg_trgm extension enablement
- v2.0 §2.5 기반 핵심 테이블
- seed placeholder

## Next Tasks

- SQLAlchemy 메타데이터 정합화
- materialized views 추가
- bootstrap ETL용 staging 테이블 추가
- seed 데이터와 alias dictionary 적재
- data quality test 배선
