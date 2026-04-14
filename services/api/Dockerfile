# TODO: pin to @sha256:<digest> before production
FROM python:3.12-slim

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
COPY services/api/pyproject.toml services/api/uv.lock ./

RUN pip install uv && uv sync --frozen --no-dev --no-install-project

COPY services/api/src ./src
COPY db/alembic.ini /app/alembic.ini
COPY db/migrations /app/db/migrations

RUN uv sync --frozen --no-dev

# Transfer ownership to non-root user, then drop privileges
RUN chown -R app:app /app

USER app

EXPOSE 8000

CMD ["uv", "run", "python", "-m", "uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
