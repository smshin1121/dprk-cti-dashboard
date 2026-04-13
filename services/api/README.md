# API Scaffold

FastAPI 3.12 준비 상태다. 실제 비즈니스 로직 대신 헬스체크, 메타데이터, OpenAPI 스켈레톤 라우트만 포함한다.

## Included

- FastAPI app factory
- `/healthz`
- `/api/v1/meta`
- auth/report/alert skeleton routers
- Alembic wiring

## Next Tasks

- SQLAlchemy 모델과 세션 관리 추가
- Authlib OIDC login/callback/session 검증 연결
- RBAC scope 검사 미들웨어
- 핵심 엔드포인트 구현
- Pact/OpenAPI 계약 테스트
