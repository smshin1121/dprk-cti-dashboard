# DPRK CTI Monorepo

설계서 v2.0 기준의 "구현 준비" 스캐폴드 저장소다. 실제 기능 구현 전, 개발 컨테이너와 서비스 경계, 의존성 매니페스트, 마이그레이션, OpenAPI 골격을 맞추는 데 초점을 둔다.

## Default Decisions

- Monorepo: simple directory layout
- Frontend package manager: `pnpm`
- Python toolchain: `uv`
- Branch strategy: `feat/scaffold` 권장

## Layout

```text
apps/
  frontend/
services/
  api/
  worker/
  llm-proxy/
db/
  migrations/
  seeds/
.github/workflows/
```

## Quick Start

1. `.env.example`를 복사해 `.env`를 만든다.
2. Docker Desktop을 실행한다.
3. `docker compose up --build`로 개발 스택을 올린다.
4. `frontend`, `api`, `llm-proxy`의 health/hello 엔드포인트로 컨테이너 연결을 확인한다.

> Copy `.env.example` → `.env` and each `envs/*.env.example` → `envs/*.env` before running `docker compose up`. Never commit non-example env files.

## Services

- `apps/frontend`: Vite + React + TypeScript + Tailwind + Zustand + TanStack Query 준비
- `services/api`: FastAPI + SQLAlchemy + Alembic + Authlib(OIDC) 준비
- `services/worker`: Prefect 2 기반 수집/정규화/알림 플로우 준비
- `services/llm-proxy`: LLM 호출 프록시, 키 경계, 사용량 관측 준비
- `db`: PostgreSQL 16 + `pgvector` + `pg_trgm` 마이그레이션/시드

## Next Tasks

- OIDC 로그인 플로우와 RBAC 미들웨어 추가
- Bootstrap ETL과 시드 적재 분리
- Pact/OpenAPI 계약 검증 배선
- 관측성 스택(OTel/Loki/Grafana) 연결
- CI에서 lint/test/build 매트릭스 활성화
