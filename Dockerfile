# ============================
# Builder stage
# ============================
FROM python:3.13-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# System deps needed to build wheels and frontend
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy uv binary
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy Python dependency metadata
COPY pyproject.toml uv.lock ./

# Install Python deps into a local venv
RUN uv sync --frozen --no-dev

# Install Node.js for frontend build
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

# Copy frontend files
COPY frontend/ ./frontend/

# Install frontend dependencies and build
WORKDIR /app/frontend
RUN npm ci --legacy-peer-deps && \
    npm run build

WORKDIR /app

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

# Copy venv from builder
COPY --from=builder /app/.venv /app/.venv

# Copy application code (excluding frontend source since it's already built)
COPY . .
COPY --from=builder /app/static ./static

# Fix ownership
RUN chown -R appuser:appuser /app

USER appuser

# Railway injects PORT
EXPOSE 8000

# IMPORTANT:
# - no `activate`
# - no PATH reliance
# - absolute interpreter path
CMD ["sh", "-c", "exec /app/.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 4"]
