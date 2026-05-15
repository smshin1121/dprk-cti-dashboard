# syntax=docker/dockerfile:1.7

# =============================================================================
# Stage 1: builder — install deps and run vite build
# =============================================================================
# Base image digest-pinned for supply-chain integrity (PR #48).
# Tag retained for human-readable provenance; CI gate
# `apps/frontend/tests/unit/dockerfile-digest-pin.test.ts` enforces every
# FROM line carries an `@sha256:` pin so future bumps can't silently drop it.
# Refresh procedure: `docker pull node:22-alpine` → copy the printed Digest
# line → replace below + bump the tag in lockstep if the upstream tag moves.
FROM node:22-alpine@sha256:968df39aedcea65eeb078fb336ed7191baf48f972b4479711397108be0966920 AS builder

RUN corepack enable && corepack prepare pnpm@9 --activate

WORKDIR /workspace

# Copy workspace manifest + lockfile first for better layer caching
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY apps/frontend/package.json ./apps/frontend/package.json

RUN pnpm install --frozen-lockfile --filter @dprk-cti/frontend...

# Copy the rest of the frontend source
COPY apps/frontend ./apps/frontend

RUN pnpm --filter @dprk-cti/frontend run build

# =============================================================================
# Stage 2: runtime — nginx serving static assets, non-root
# =============================================================================
# Base image digest-pinned for supply-chain integrity (PR #48).
# Refresh procedure: `docker pull nginx:1.27-alpine` → copy the printed Digest
# line → replace below + bump the tag in lockstep if the upstream tag moves.
FROM nginx:1.27-alpine@sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10 AS runtime

RUN addgroup -g 1001 -S app && adduser -u 1001 -S app -G app

# Copy built static assets
COPY --from=builder /workspace/apps/frontend/dist /usr/share/nginx/html
COPY apps/frontend/nginx.conf /etc/nginx/conf.d/default.conf

# Runtime config generator — writes /usr/share/nginx/html/config.js at startup
# from environment variables, then execs nginx. See apps/frontend/src/config.ts.
COPY apps/frontend/docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

# Prepare non-root nginx: own writable paths and flip the listen port to 8080
# (non-root cannot bind to ports < 1024). Also strip the pidfile directive so
# nginx writes its pid under a path the app user can write.
RUN sed -i 's,listen       80;,listen       8080;,' /etc/nginx/conf.d/default.conf && \
    sed -i '/user  nginx;/d' /etc/nginx/nginx.conf && \
    sed -i 's,/var/run/nginx.pid,/tmp/nginx.pid,' /etc/nginx/nginx.conf && \
    chown -R app:app /usr/share/nginx/html \
                     /var/cache/nginx \
                     /var/log/nginx \
                     /etc/nginx/conf.d

USER app

EXPOSE 8080

ENTRYPOINT ["/docker-entrypoint.sh"]
