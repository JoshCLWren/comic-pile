# Global ARGs (available to all stages when redeclared)
ARG USER_ID=1000
ARG GROUP_ID=1000

# ============================
# Python dependency stage
# ============================
FROM python:3.13-slim AS python-builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# System deps needed to build Python wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy uv binary from a pinned tag for reproducible builds.
COPY --from=ghcr.io/astral-sh/uv:0.6.3 /uv /usr/local/bin/uv

WORKDIR /app

# Copy Python dependency metadata
COPY pyproject.toml uv.lock ./

# Install Python deps into a local venv
RUN uv sync --frozen --no-dev

# ============================
# Frontend build stage
# ============================
FROM node:22.13.1-bookworm-slim AS frontend-builder

WORKDIR /app/frontend

# Copy dependency files first for layer caching
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

# Copy source files - this layer invalidates when any source changes
COPY frontend/ ./

# Build with explicit cache bust by touching a file that changes each build
# This ensures npm run build always executes when source changes
RUN echo "Build timestamp: $(date -u +%s)" > /tmp/build-stamp && npm run build

# Vite writes to /app/static/react based on outDir in vite config

# ============================
# Runtime stage
# ============================
FROM python:3.13-slim

ARG USER_ID=1000
ARG GROUP_ID=1000

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Runtime system deps only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user with host UID/GID to avoid permission issues
RUN groupadd -g ${GROUP_ID} appuser && \
    useradd -u ${USER_ID} -g ${GROUP_ID} --create-home --shell /bin/bash appuser

WORKDIR /app

# Copy Python runtime environment
COPY --from=python-builder /app/.venv /app/.venv

# Copy only runtime application files
COPY app/ ./app/
COPY comic_pile/ ./comic_pile/
COPY alembic/ ./alembic/
COPY alembic.ini ./alembic.ini

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

# Railway injects PORT
EXPOSE 8000

# IMPORTANT:
# - no `activate`
# - no PATH reliance
# - absolute interpreter path
CMD ["sh", "-c", "exec /app/.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers ${WEB_CONCURRENCY:-2}"]
