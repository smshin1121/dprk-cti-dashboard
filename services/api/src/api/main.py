import os

from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from limits.errors import StorageError
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from .config import get_settings
from .deps import verify_token
from .rate_limit import (
    get_limiter,
    handle_storage_unavailable,
    rate_limit_exceeded_handler,
)
from .telemetry import setup_telemetry
from .routers import (
    actors,
    alerts,
    analytics,
    auth,
    dashboard,
    export,
    incidents,
    ingest,
    meta,
    pact_states,
    reports,
    search,
    staging,
)

_settings = get_settings()

# Expose docs only in dev; set all three to None in prod to prevent
# unauthenticated OpenAPI schema discovery.
_docs_url = "/docs" if _settings.app_env == "dev" else None
_redoc_url = "/redoc" if _settings.app_env == "dev" else None
_openapi_url = "/openapi.json" if _settings.app_env == "dev" else None

app = FastAPI(
    title="DPRK CTI API",
    version="0.1.0",
    openapi_version="3.1.0",
    description="Implementation-prep OpenAPI skeleton for the DPRK CTI platform.",
    docs_url=_docs_url,
    redoc_url=_redoc_url,
    openapi_url=_openapi_url,
)


# ---------------------------------------------------------------------------
# Rate limiting (PR #11 Group F)
# ---------------------------------------------------------------------------
#
# Build the limiter once at import time so environment-policy errors
# (plan F lock — prod requires redis://) fail the process loudly
# rather than the first request. The limiter itself does nothing
# until Group G / H decorate routes with ``@limiter.limit(...)``.
# ``/healthz``, ``/openapi.json``, ``/docs``, ``/redoc``, and any
# un-decorated route remain unrestricted — ``default_limits=[]`` in
# ``build_limiter`` makes opt-in the only path to enforcement.
_limiter = get_limiter()
app.state.limiter = _limiter
# Custom handler returns JSON (plan D13 — 429 body shape matches the
# OpenAPI `rate_limit_exceeded` example for every decorated route,
# including the auth/callback browser-redirect path).
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
# Storage backend (Redis) failure handler — 503 JSON instead of bare
# 500 when the rate-limit Redis is unreachable. Codex R1 P2 lock:
# rate_limit.py's fail-closed docstring promised a 503 path; this
# registration is what makes the promise real. Covers both limits'
# wrapper (`StorageError`) and redis-py's raw connection errors
# (which slowapi's Redis backend does not always re-wrap).
app.add_exception_handler(StorageError, handle_storage_unavailable)
app.add_exception_handler(RedisConnectionError, handle_storage_unavailable)
app.add_exception_handler(RedisTimeoutError, handle_storage_unavailable)
app.add_middleware(SlowAPIMiddleware)

# ---------------------------------------------------------------------------
# CORS — never use ["*"]; only origins declared in env are allowed.
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
)


# ---------------------------------------------------------------------------
# OpenTelemetry — instruments FastAPI, SQLAlchemy, HTTPX. No-op if
# OTEL_EXPORTER_OTLP_ENDPOINT is unset (e.g. unit tests).
# ---------------------------------------------------------------------------
from . import db as _db  # noqa: E402 — deferred to avoid eager engine build at import

setup_telemetry(app, engine=_db.engine if os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT") else None)


# ---------------------------------------------------------------------------
# Security headers middleware
# ---------------------------------------------------------------------------
@app.middleware("http")
async def add_security_headers(request: Request, call_next) -> Response:
    response: Response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if _settings.app_env == "prod":
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
    return response


# ---------------------------------------------------------------------------
# Routers
# Public (no verify_token dependency): auth, meta.
# All other routers require a valid token via Depends(verify_token).
# Each router uses relative paths; the prefix is declared here exactly once.
# ---------------------------------------------------------------------------
app.include_router(meta.router, prefix="/api/v1/meta", tags=["meta"])
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(
    ingest.router,
    prefix="/api/v1/ingest",
    tags=["ingest"],
    dependencies=[Depends(verify_token)],
)
app.include_router(
    reports.router,
    prefix="/api/v1/reports",
    tags=["reports"],
    dependencies=[Depends(verify_token)],
)
app.include_router(
    staging.router,
    prefix="/api/v1/staging",
    tags=["staging"],
    dependencies=[Depends(verify_token)],
)
app.include_router(
    actors.router,
    prefix="/api/v1/actors",
    tags=["actors"],
    dependencies=[Depends(verify_token)],
)
app.include_router(
    incidents.router,
    prefix="/api/v1/incidents",
    tags=["incidents"],
    dependencies=[Depends(verify_token)],
)
app.include_router(
    dashboard.router,
    prefix="/api/v1/dashboard",
    tags=["dashboard"],
    dependencies=[Depends(verify_token)],
)
app.include_router(
    analytics.router,
    prefix="/api/v1/analytics",
    tags=["analytics"],
    dependencies=[Depends(verify_token)],
)
app.include_router(
    search.router,
    prefix="/api/v1/search",
    tags=["search"],
    dependencies=[Depends(verify_token)],
)
app.include_router(
    alerts.router,
    prefix="/api/v1/alerts",
    tags=["alerts"],
    dependencies=[Depends(verify_token)],
)
app.include_router(
    export.router,
    prefix="/api/v1/export",
    tags=["export"],
    dependencies=[Depends(verify_token)],
)


# ---------------------------------------------------------------------------
# Pact provider-state handler — dev/test envs only.
# Registering in prod would expose an unauthenticated session minter;
# the APP_ENV guard scopes it to the contract-verify CI job and local
# devs reproducing that suite.
# ---------------------------------------------------------------------------
if _settings.app_env != "prod":
    app.include_router(
        pact_states.router,
        prefix="/_pact/provider_states",
        tags=["pact-states-dev-only"],
        include_in_schema=False,
    )


@app.get("/healthz", tags=["ops"])
def healthcheck() -> dict[str, str]:
    return {"status": "ok", "service": "api"}
