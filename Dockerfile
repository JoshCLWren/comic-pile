# Multi-stage build for production optimization
FROM python:3.13-slim AS builder

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_CACHE_DIR=/tmp/uv-cache

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Set working directory
WORKDIR /app

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync --frozen --no-dev

# Production stage
FROM python:3.13-slim

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd --create-home --shell /bin/bash appuser

# Copy uv and dependencies from builder
COPY --from=builder /usr/local/bin/uv /usr/local/bin/uv
COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv

# Set working directory
WORKDIR /app

# Copy application code
COPY --chown=appuser:appuser . .

# Switch to non-root user
USER appuser

# Expose port (Railway provides PORT environment variable)
EXPOSE 8080

# Health check optimized for Railway
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:\$PORT/health')" || exit 1

# Run application using uv
# - Bind to 0.0.0.0 to accept external connections
# - PORT is set by Railway
# - Set log level from environment
CMD ["sh", "-c", ". /app/.venv/bin/activate && exec uvicorn app.main:app --host 0.0.0.0 --port $PORT --log-level ${LOG_LEVEL:-info}"]
# Force rebuild Thu Jan 22 08:10:05 AM CST 2026
