#!/bin/sh
set -eu

# Runtime config generator. Writes /usr/share/nginx/html/config.js from env vars
# at container startup so the static bundle can read runtime values via
# window.__APP_CONFIG__. See apps/frontend/src/config.ts for the consumer.

CONFIG_PATH="${CONFIG_PATH:-/usr/share/nginx/html/config.js}"

cat > "$CONFIG_PATH" <<EOF
window.__APP_CONFIG__ = {
  apiUrl: "${API_URL:-/api/v1}",
  llmProxyUrl: "${LLM_PROXY_URL:-}",
  appEnv: "${APP_ENV:-prod}"
};
EOF

exec nginx -g 'daemon off;'
