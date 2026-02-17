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

# Copy uv binary
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy Python dependency metadata
COPY pyproject.toml uv.lock ./

# Install Python deps into a local venv
RUN uv sync --frozen --no-dev

# ============================
# Frontend build stage
# ============================
FROM node:22.11.0-bookworm-slim AS frontend-builder

WORKDIR /app/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# Vite writes to /app/static/react based on outDir in vite config

# ============================
# Runtime stage
# ============================
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Runtime system deps only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd --create-home --shell /bin/bash appuser

WORKDIR /app

# Copy Python runtime environment
COPY --from=python-builder /app/.venv /app/.venv

# Copy only runtime application files
COPY app/ ./app/
COPY comic_pile/ ./comic_pile/
COPY alembic/ ./alembic/
COPY alembic.ini ./alembic.ini
COPY static/ ./static/

# Copy compiled frontend assets produced by Vite
COPY --from=frontend-builder /app/static/react ./static/react

# Fix ownership
RUN chown -R appuser:appuser /app

USER appuser

# Railway injects PORT
EXPOSE 8000

# IMPORTANT:
# - no `activate`
# - no PATH reliance
# - absolute interpreter path
CMD ["sh", "-c", "exec /app/.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers ${WEB_CONCURRENCY:-2}"]
