# syntax=docker/dockerfile:1.7

# =============================================================================
# Stage 1: builder — install deps and run vite build
# =============================================================================
# TODO: pin to @sha256:<digest> before production
FROM node:22-alpine AS builder

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
# TODO: pin to @sha256:<digest> before production
FROM nginx:1.27-alpine AS runtime

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
