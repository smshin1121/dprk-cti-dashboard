# LLM Proxy Scaffold

LLM 제공자 호출을 직접 노출하지 않기 위한 프록시 골격이다. 키 접근 경계와 캐시 경계만 먼저 만든다.

## Included

- FastAPI hello/health endpoints
- provider metadata endpoint
- prompt caching boundary placeholder

## Next Tasks

- provider adapter 계층 추가
- Redis 캐시와 사용량 계측 연결
- 정책 기반 모델 허용 목록
- prompt redaction / audit trail
- rate limit and retry policy
