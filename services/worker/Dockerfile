# TODO: pin to @sha256:<digest> before production
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

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
