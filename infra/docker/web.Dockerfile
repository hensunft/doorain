# syntax=docker/dockerfile:1.7
# web: собранный frontend + Caddy (статические файлы, reverse proxy /api, HTTPS в интернет-режиме).
FROM node:24-alpine@sha256:ebfe2f90462722a7a4de65e91990e97fe0d401c70e0e762c5b53302f905ec1c1 AS ui
WORKDIR /ui
RUN corepack enable
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN --mount=type=cache,target=/root/.local/share/pnpm/store pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm run build

FROM caddy:2-alpine@sha256:de23def33b17fb5d1290b0f6c2add1d70780e52341896c00a4c8a2a2fe9d355e
COPY --from=ui /ui/dist /srv
COPY infra/caddy/Caddyfile /etc/caddy/Caddyfile
COPY infra/caddy/entrypoint.sh /usr/local/bin/doorain-entrypoint
RUN chmod +x /usr/local/bin/doorain-entrypoint && addgroup -S caddy2 2>/dev/null; true
EXPOSE 80 443
ENTRYPOINT ["/usr/local/bin/doorain-entrypoint"]
CMD ["caddy", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]
