# Base image digest-pinned for supply-chain integrity (PR #48).
# Tag retained for human-readable provenance; CI gate
# `services/worker/tests/unit/test_dockerfile_digest_pin.py` enforces every
# FROM line carries an `@sha256:` pin so future bumps can't silently drop it.
# Refresh procedure: `docker pull python:3.12-slim` → copy the printed Digest
# line → replace below + bump the tag in lockstep if the upstream tag moves.
FROM python:3.12-slim@sha256:401f6e1a67dad31a1bd78e9ad22d0ee0a3b52154e6bd30e90be696bb6a3d7461

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
COPY services/worker/pyproject.toml services/worker/uv.lock ./

RUN pip install uv && uv sync --frozen --no-dev --no-install-project

COPY services/worker/src ./src

RUN uv sync --frozen --no-dev

# Transfer ownership to non-root user, then drop privileges
RUN chown -R app:app /app

USER app

CMD ["uv", "run", "python", "src/worker/main.py"]
