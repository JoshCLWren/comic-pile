# Global ARGs (available to all stages when redeclared)
ARG USER_ID=1000
ARG GROUP_ID=1000
ARG BUILD_TIMESTAMP=unknown

# ============================
# Frontend build stage
# ============================
FROM node:22.23.1-trixie-slim AS frontend-builder

WORKDIR /app

RUN npm install -g pnpm@10.15.0

# Copy workspace and dependency files first for layer caching
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY frontend/package.json frontend/

RUN pnpm install --frozen-lockfile

# Copy source files - this layer invalidates when any source changes
COPY frontend/ ./frontend/

# Force cache invalidation by using build arg
ARG BUILD_TIMESTAMP
RUN echo "Build timestamp: ${BUILD_TIMESTAMP:-$(date -u +%s)}" && pnpm --filter frontend run build

# Vite writes to /app/static/react based on outDir in vite config

# ============================
# Rust build stage
# ============================
FROM rust:1.99.1-slim-trixie AS rust-builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    pkg-config \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

COPY Cargo.toml Cargo.lock build.rs ./
COPY api/ ./api/
COPY native/ ./native/

RUN cargo build --release --locked -p comicpile-roll-service -p comicpile-migrate

# ============================
# Runtime stage
# ============================
FROM debian:trixie-slim

ARG USER_ID=1000
ARG GROUP_ID=1000

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    libpq5 \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user with host UID/GID to avoid permission issues
RUN groupadd -g ${GROUP_ID} appuser && \
    useradd -u ${USER_ID} -g ${GROUP_ID} --create-home --shell /bin/bash appuser

WORKDIR /app

# Native Rust ingress and migration runner; no Python runtime is present.
COPY --from=rust-builder /app/target/release/comicpile-roll-service ./bin/comicpile-roll-service
COPY --from=rust-builder /app/target/release/comicpile-migrate ./bin/comicpile-migrate

# Copy static directory structure (without react build artifacts)
COPY static/assets ./static/assets
COPY static/css ./static/css
COPY static/favicon.svg ./static/favicon.svg
COPY static/index.html ./static/index.html
COPY static/vite.svg ./static/vite.svg

# Copy compiled frontend assets produced by Vite (ALWAYS do this last)
COPY --from=frontend-builder /app/static/react ./static/react

# Fix ownership
RUN chown -R ${USER_ID}:${GROUP_ID} /app

USER ${USER_ID}

EXPOSE 8000

CMD ["/app/bin/comicpile-roll-service"]
