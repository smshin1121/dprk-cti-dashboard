import os

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from .config import get_settings
from .error_handlers import register_exception_handlers
from .rate_limit import get_limiter
from .routers import embedding, provider
from .telemetry import setup_telemetry

# ---------------------------------------------------------------------------
# Startup fail-closed (plan D3 Draft v2).
#
# Evaluating ``get_settings()`` here — at import time, before
# ``FastAPI(...)`` is constructed — forces both Settings validators
# to run BEFORE uvicorn starts accepting requests. Any validation
# failure (``provider=openai`` with empty ``OPENAI_API_KEY`` OR
# ``provider=mock`` with ``APP_ENV=prod``) raises ``ValidationError``
# out of this import and the process dies without binding the port.
#
# Without this eager call the validators would only run on the
# first request (when ``Depends(get_settings)`` evaluates), which
# means a misconfigured prod pod would stay alive and respond 503
# per request — the plan locks "refuses to boot", not "first-request
# fail".
# ---------------------------------------------------------------------------
get_settings()

# ---------------------------------------------------------------------------
# Internal shared-secret guard.
# LLM_PROXY_INTERNAL_TOKEN must be set in the environment; the proxy is
# internal-network-only but we still enforce a shared secret so that a
# misconfigured network rule cannot expose the OpenAI key publicly.
# ---------------------------------------------------------------------------
_INTERNAL_TOKEN = os.environ.get("LLM_PROXY_INTERNAL_TOKEN", "")
_APP_ENV = os.environ.get("APP_ENV", "dev")

# Expose docs only in dev.
_docs_url = "/docs" if _APP_ENV == "dev" else None
_redoc_url = "/redoc" if _APP_ENV == "dev" else None
_openapi_url = "/openapi.json" if _APP_ENV == "dev" else None

app = FastAPI(
    title="DPRK CTI LLM Proxy",
    version="0.1.0",
    openapi_version="3.1.0",
    docs_url=_docs_url,
    redoc_url=_redoc_url,
    openapi_url=_openapi_url,
)

# OTel — no-op if OTEL_EXPORTER_OTLP_ENDPOINT is unset.
setup_telemetry(app)


@app.middleware("http")
async def require_internal_token(request: Request, call_next) -> Response:
    """Fail-closed shared-secret check for all non-health routes.

    Requests must carry the header:  X-Internal-Token: <LLM_PROXY_INTERNAL_TOKEN>

    If LLM_PROXY_INTERNAL_TOKEN is empty the service refuses ALL requests so
    that a missing env var is caught immediately at runtime rather than silently
    allowing unauthenticated access.
    """
    # Allow health probe without a token.
    if request.url.path == "/healthz":
        return await call_next(request)

    if not _INTERNAL_TOKEN:
        return JSONResponse(
            status_code=503,
            content={"detail": "LLM_PROXY_INTERNAL_TOKEN not configured — service unavailable."},
        )

    provided = request.headers.get("X-Internal-Token", "")
    if provided != _INTERNAL_TOKEN:
        return JSONResponse(
            status_code=401,
            content={"detail": "Missing or invalid X-Internal-Token header."},
        )

    return await call_next(request)


# PR #18 Group C: slowapi limiter + D7 / D5 exception handlers.
# ``app.state.limiter`` is read by slowapi's decorator machinery at
# request time; registering the handlers here covers every D7
# branch (502 / 504 / 429 / 422 / 503) plus the local 429 from
# ``RateLimitExceeded``.
app.state.limiter = get_limiter()
register_exception_handlers(app)


app.include_router(provider.router, prefix="/api/v1/provider", tags=["provider"])
app.include_router(embedding.router, prefix="/api/v1/embedding", tags=["embedding"])


@app.get("/healthz", tags=["ops"])
def healthcheck() -> dict[str, str]:
    return {"status": "ok", "service": "llm-proxy"}
