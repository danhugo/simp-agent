# Production images. `docker compose build` builds both targets.

ARG TARGETARCH
# officecli (docx/xlsx/pptx preview): pinned + checksum per arch; bump version and both sums together
FROM scratch AS officecli-amd64
ADD --checksum=sha256:baa084b64ec634bd9d41a0592db3ed85f11658b358bab898679537ea7f3e73a9 --chmod=755 https://github.com/iOfficeAI/OfficeCLI/releases/download/v1.0.160/officecli-linux-x64 /officecli
FROM scratch AS officecli-arm64
ADD --checksum=sha256:e8f06aff6c59f11a73a1a1218bda3ce170299201fd56bce6d62ecd4d0c024e53 --chmod=755 https://github.com/iOfficeAI/OfficeCLI/releases/download/v1.0.160/officecli-linux-arm64 /officecli
FROM officecli-${TARGETARCH} AS officecli

# server: simp-server and google_mcp (same image)
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS server
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never SIMP_SERVER_HOME=/data PATH=/app/.venv/bin:$PATH
COPY --from=officecli /officecli /usr/local/bin/officecli
# ponytail: no ICU in the slim image; invariant culture is enough to render docx/xlsx/pptx to html
ENV DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1
COPY pyproject.toml uv.lock ./
COPY packages packages
COPY apps/cli apps/cli
COPY apps/server apps/server
RUN uv sync --locked --no-dev --package simp-server
CMD ["simp-server", "run"]

# web: build apps/web, serve dist with Caddy
FROM node:22-slim AS web-build
WORKDIR /web
RUN corepack enable
COPY apps/web/package.json apps/web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY apps/web .
ARG VITE_SENTRY_DSN=""
RUN VITE_SENTRY_DSN=$VITE_SENTRY_DSN pnpm build

FROM caddy:2 AS web
COPY --from=web-build /web/dist /srv/web
COPY Caddyfile /etc/caddy/Caddyfile
