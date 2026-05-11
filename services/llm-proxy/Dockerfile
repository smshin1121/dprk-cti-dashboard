# Base image digest-pinned for supply-chain integrity (PR #48).
# Tag retained for human-readable provenance; CI gate
# `services/llm-proxy/tests/unit/test_dockerfile_digest_pin.py` enforces every
# FROM line carries an `@sha256:` pin so future bumps can't silently drop it.
# Refresh procedure: `docker pull python:3.12-slim` → copy the printed Digest
# line → replace below + bump the tag in lockstep if the upstream tag moves.
FROM python:3.12-slim@sha256:ec948fa5f90f4f8907e89f4800cfd2d2e91e391a4bce4a6afa77ba265bc3a2fe

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
# uv writes its cache to $HOME/.cache/uv by default; the non-root `app` user
# (uid 1001, no real home) can't write there. Put the cache under /app so
# the existing chown -R app:app /app step grants write access.
ENV UV_CACHE_DIR=/app/.uv-cache

# Create non-root user before any app setup
RUN groupadd --system --gid 1001 app && \
    useradd --system --uid 1001 --gid app --shell /bin/bash app

WORKDIR /app

# Copy and install as root (requires write access to /app)
COPY services/llm-proxy/pyproject.toml services/llm-proxy/uv.lock ./

RUN pip install uv && uv sync --frozen --no-dev --no-install-project

COPY services/llm-proxy/src ./src

RUN uv sync --frozen --no-dev

# Transfer ownership to non-root user, then drop privileges
RUN chown -R app:app /app

USER app

EXPOSE 8010

CMD ["uv", "run", "python", "-m", "uvicorn", "src.llm_proxy.main:app", "--host", "0.0.0.0", "--port", "8010"]
