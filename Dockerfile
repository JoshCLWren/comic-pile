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
...
# Install Python deps into a local venv
RUN uv sync --frozen --no-dev

# ============================
# Frontend stage
# ============================
FROM python:3.13-slim AS builder
...
# Copy frontend source
COPY frontend/ ./frontend/

# Install frontend dependencies and build
RUN npm ci --legacy-peer-deps
RUN npm ci
# Build frontend (creates frontend/dist/ including static files)
RUN npm run build

# ============================
# Runtime stage
# ============================
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Runtime system deps only
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    git \
    gpg \
    python3.13 \
    python3.13-venv \
    python3-pip \
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

# Install frontend dependencies
RUN npm ci --legacy-peer-deps

# Build frontend
RUN npm ci

# ============================
# Runtime stage
# ============================
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Runtime system deps only
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    git \
    gpg \
    python3.13 \
    python3.13-venv \
    python3-pip \
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

# Install frontend dependencies
RUN npm ci --legacy-peer-deps

# Build frontend (creates frontend/dist/ including static files)
RUN npm ci
RUN npm run build

# Copy built frontend to runtime
COPY --from=builder /app/frontend/dist /app/static

# Copy application code (excluding frontend source since it's already built)
COPY . .
