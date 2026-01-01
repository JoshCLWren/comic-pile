# Dockerization and PostgreSQL Migration Guide

## Overview

This guide documents the process of containerizing comic-pile with Docker and migrating the database from SQLite to PostgreSQL.

**Why Dockerize?**
- Consistent development and production environments
- Simplified dependency management
- Easy deployment and scaling
- Better isolation and security

**Why Migrate to PostgreSQL?**
- Better performance for concurrent connections
- More robust data integrity features
- Superior JSON support (for future features)
- Production-ready for multi-user deployments
- Better backup and replication options

## Prerequisites

- Docker Engine 20.10+
- Docker Compose 2.0+
- PostgreSQL client tools (pg_dump, psql) - for data migration
- Existing comic-pile codebase

---

## Part 1: Dockerizing the Application

### Step 1: Create Dockerfile

Create `Dockerfile` in the project root:

```dockerfile
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

# Install application
RUN uv pip install --no-cache .venv

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Step 2: Create docker-compose.yml

Create `docker-compose.yml` for local development:

```yaml
version: '3.8'

services:
  db:
    image: postgres:16-alpine
    container_name: comic-pile-db
    restart: unless-stopped
    environment:
      POSTGRES_USER: comicpile
      POSTGRES_PASSWORD: comicpile_password
      POSTGRES_DB: comicpile
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U comicpile"]
      interval: 10s
      timeout: 5s
      retries: 5

  app:
    build: .
    container_name: comic-pile-app
    restart: unless-stopped
    depends_on:
      db:
        condition: service_healthy
    environment:
      DATABASE_URL: postgresql+psycopg://comicpile:comicpile_password@db:5432/comicpile
      ENVIRONMENT: production
    ports:
      - "8000:8000"
    volumes:
      - ./app:/app/app
      - ./comic_pile:/app/comic_pile
      - ./alembic:/app/alembic
    command: ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

  # Optional: pgAdmin for database management
  pgadmin:
    image: dpage/pgadmin4:latest
    container_name: comic-pile-pgadmin
    restart: unless-stopped
    environment:
      PGADMIN_DEFAULT_EMAIL: admin@comicpile.local
      PGADMIN_DEFAULT_PASSWORD: pgadmin_password
    ports:
      - "5050:80"
    depends_on:
      - db

volumes:
  postgres_data:
```

### Step 3: Create .dockerignore

Create `.dockerignore` to exclude unnecessary files:

```gitignore
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
*.egg-info/
dist/
build/

# Virtual environments
.venv/
venv/
env/

# Database
*.db
*.sqlite
*.sqlite3

# IDE
.vscode/
.idea/
*.swp
*.swo

# Git
.git/
.gitignore

# Documentation
docs/
*.md
!README.md

# Tests
tests/
.pytest_cache/
.coverage
htmlcov/

# Logs
*.log
logs/

# Environment
.env
.env.local

# Docker
Dockerfile*
docker-compose*.yml
.dockerignore
```

### Step 4: Add .env.example

Create `.env.example` for environment variable template:

```env
# Database
DATABASE_URL=postgresql+psycopg://comicpile:comicpile_password@localhost:5432/comicpile

# Application
ENVIRONMENT=development
LOG_LEVEL=info

# Security (generate strong secrets for production)
SECRET_KEY=your-secret-key-here

# Optional: CORS settings
CORS_ORIGINS=http://localhost:3000,http://localhost:8000
```

---

## Part 2: PostgreSQL Migration

### Step 1: Update Dependencies

Add PostgreSQL driver to `pyproject.toml`:

```toml
dependencies = [
    "fastapi>=0.100.0",
    "uvicorn[standard]>=0.20.0",
    "sqlalchemy>=2.0.0",
    "alembic>=1.12.0",
    "jinja2>=3.1.0",
    "pydantic>=2.0.0",
    "python-multipart>=0.0.6",
    "psycopg[binary]>=3.1.0",  # Add this line
]
```

### Step 2: Update Database Configuration

Modify `app/database.py` to support environment-based configuration:

```python
"""Database connection and session management."""

import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///./comic_pile.db"
)

# For SQLite, we need special connect args
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""


def get_db() -> Generator[Session]:
    """Get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

### Step 3: Update Alembic Configuration

Update `alembic.ini`:

```ini
# Change from SQLite to PostgreSQL
# sqlalchemy.url = sqlite:///./comic_pile.db
sqlalchemy.url = postgresql+psycopg://comicpile:comicpile_password@localhost:5432/comicpile
```

Update `alembic/env.py` to use environment variable:

```python
"""Alembic environment configuration."""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

import app.models  # noqa: F401
from alembic import context
from app.database import Base

config = context.config

# Override sqlalchemy.url from environment variable
import os
if os.getenv("DATABASE_URL"):
    config.set_main_option("sqlalchemy.url", os.getenv("DATABASE_URL"))

# ... rest of the file remains the same
```

### Step 4: Data Migration Strategy

#### Option A: Fresh Start (Recommended for New Deployments)

```bash
# 1. Backup existing SQLite database
cp comic_pile.db comic_pile.db.backup

# 2. Start PostgreSQL
docker-compose up -d db

# 3. Wait for PostgreSQL to be ready
docker-compose logs -f db  # Wait until "database system is ready to accept connections"

# 4. Run migrations
DATABASE_URL="postgresql+psycopg://comicpile:comicpile_password@localhost:5432/comicpile" \
  alembic upgrade head

# 5. Seed fresh data (optional)
docker-compose exec app python -m scripts.seed_data
```

#### Option B: Migrate Existing Data

Create `scripts/migrate_sqlite_to_postgres.py`:

```python
"""Migrate data from SQLite to PostgreSQL."""

import sqlite3
import os
import sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.models import User, Thread, Session, Event, Task

# SQLite connection
sqlite_conn = sqlite3.connect('comic_pile.db')
sqlite_conn.row_factory = sqlite3.Row

# PostgreSQL connection
pg_url = os.getenv("DATABASE_URL", "postgresql+psycopg://comicpile:comicpile_password@localhost:5432/comicpile")
pg_engine = create_engine(pg_url)
pg_session = sessionmaker(bind=pg_engine)()

def migrate_users():
    """Migrate users table."""
    cursor = sqlite_conn.execute("SELECT * FROM users")
    for row in cursor:
        user = User(
            id=row['id'],
            name=row['name'],
            created_at=row['created_at'],
            updated_at=row['updated_at'],
        )
        pg_session.merge(user)
    pg_session.commit()
    print(f"Migrated {cursor.rowcount} users")

def migrate_threads():
    """Migrate threads table."""
    cursor = sqlite_conn.execute("SELECT * FROM threads")
    for row in cursor:
        thread = Thread(
            id=row['id'],
            name=row['name'],
            publisher=row['publisher'],
            current_volume=row['current_volume'],
            current_issue=row['current_issue'],
            dice_value=row['dice_value'],
            last_rating=row['last_rating'],
            last_review_at=row['last_review_at'],
            created_at=row['created_at'],
            updated_at=row['updated_at'],
        )
        pg_session.merge(thread)
    pg_session.commit()
    print(f"Migrated {cursor.rowcount} threads")

def migrate_sessions():
    """Migrate sessions table."""
    cursor = sqlite_conn.execute("SELECT * FROM sessions")
    for row in cursor:
        session = Session(
            id=row['id'],
            thread_id=row['thread_id'],
            started_at=row['started_at'],
            ended_at=row['ended_at'],
            status=row['status'],
            dice_roll=row['dice_roll'],
            completed=row['completed'],
            skipped=row['skipped'],
            read=row['read'],
            created_at=row['created_at'],
            updated_at=row['updated_at'],
        )
        pg_session.merge(session)
    pg_session.commit()
    print(f"Migrated {cursor.rowcount} sessions")

def migrate_events():
    """Migrate events table."""
    cursor = sqlite_conn.execute("SELECT * FROM events")
    for row in cursor:
        event = Event(
            id=row['id'],
            session_id=row['session_id'],
            event_type=row['event_type'],
            issue=row['issue'],
            rating=row['rating'],
            timestamp=row['timestamp'],
            created_at=row['created_at'],
            updated_at=row['updated_at'],
        )
        pg_session.merge(event)
    pg_session.commit()
    print(f"Migrated {cursor.rowcount} events")

def migrate_tasks():
    """Migrate tasks table."""
    cursor = sqlite_conn.execute("SELECT * FROM tasks")
    for row in cursor:
        task = Task(
            id=row['id'],
            task_id=row['task_id'],
            title=row['title'],
            description=row['description'],
            priority=row['priority'],
            status=row['status'],
            dependencies=row['dependencies'],
            assigned_agent=row['assigned_agent'],
            worktree=row['worktree'],
            status_notes=row['status_notes'],
            estimated_effort=row['estimated_effort'],
            completed=row['completed'],
            blocked_reason=row['blocked_reason'],
            blocked_by=row['blocked_by'],
            last_heartbeat=row['last_heartbeat'],
            instructions=row['instructions'],
            created_at=row['created_at'],
            updated_at=row['updated_at'],
        )
        pg_session.merge(task)
    pg_session.commit()
    print(f"Migrated {cursor.rowcount} tasks")

if __name__ == "__main__":
    print("Starting migration from SQLite to PostgreSQL...")
    migrate_users()
    migrate_threads()
    migrate_sessions()
    migrate_events()
    migrate_tasks()
    print("Migration complete!")
    sqlite_conn.close()
    pg_session.close()
```

Run the migration:

```bash
# 1. Ensure PostgreSQL is running and schema is created
docker-compose up -d db
DATABASE_URL="postgresql+psycopg://comicpile:comicpile_password@localhost:5432/comicpile" \
  alembic upgrade head

# 2. Run migration script
DATABASE_URL="postgresql+psycopg://comicpile:comicpile_password@localhost:5432/comicpile" \
  python -m scripts.migrate_sqlite_to_postgres
```

---

## Part 3: Development Workflow

### Docker Development Mode

```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f app

# Run migrations in container
docker-compose exec app alembic upgrade head

# Seed data in container
docker-compose exec app python -m scripts.seed_data

# Run tests in container
docker-compose exec app pytest

# Stop services
docker-compose down

# Stop and remove volumes (WARNING: destroys data)
docker-compose down -v
```

### Local Development with Docker PostgreSQL

```bash
# Start only PostgreSQL
docker-compose up -d db

# Run app locally
export DATABASE_URL="postgresql+psycopg://comicpile:comicpile_password@localhost:5432/comicpile"
uvicorn app.main:app --reload
```

---

## Part 4: Production Deployment

### Production Docker Compose

Create `docker-compose.prod.yml`:

```yaml
version: '3.8'

services:
  db:
    image: postgres:16-alpine
    container_name: comic-pile-db-prod
    restart: always
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER}"]
      interval: 10s
      timeout: 5s
      retries: 5

  app:
    build: .
    container_name: comic-pile-app-prod
    restart: always
    depends_on:
      db:
        condition: service_healthy
    environment:
      DATABASE_URL: postgresql+psycopg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB}
      ENVIRONMENT: production
      SECRET_KEY: ${SECRET_KEY}
    ports:
      - "8000:8000"
    # No volume mounts in production - use the copied code

  # Optional: Nginx reverse proxy
  nginx:
    image: nginx:alpine
    container_name: comic-pile-nginx-prod
    restart: always
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
      - ./ssl:/etc/nginx/ssl:ro
    depends_on:
      - app

volumes:
  postgres_data:
```

### Environment Variables for Production

Create `.env.production`:

```env
POSTGRES_USER=comicpile_prod
POSTGRES_PASSWORD=<strong-random-password>
POSTGRES_DB=comicpile_prod
SECRET_KEY=<strong-random-secret-key>
```

### Build and Deploy

```bash
# Build production image
docker build -t comic-pile:latest .

# Deploy
docker-compose -f docker-compose.prod.yml up -d

# Run migrations
docker-compose -f docker-compose.prod.yml exec -T app alembic upgrade head
```

---

## Part 5: Rollback Plan

### Rolling Back to SQLite

```bash
# 1. Stop Docker services
docker-compose down

# 2. Revert database.py changes (remove environment variable logic)
git checkout app/database.py

# 3. Revert alembic.ini
git checkout alembic.ini

# 4. Restore from backup if needed
cp comic_pile.db.backup comic_pile.db

# 5. Remove PostgreSQL dependency from pyproject.toml
# Edit pyproject.toml and remove "psycopg[binary]>=3.1.0"

# 6. Run locally
make migrate  # Runs SQLite migrations
make dev
```

### Rolling Back PostgreSQL Migration

```bash
# 1. Take PostgreSQL backup
docker-compose exec db pg_dump -U comicpile comicpile > backup_$(date +%Y%m%d_%H%M%S).sql

# 2. If data corruption, restore from backup
docker-compose exec -T db psql -U comicpile comicpile < backup_20240101_120000.sql

# 3. Or rollback Alembic migration
docker-compose exec app alembic downgrade base
```

---

## Part 6: Testing Checklist

### Pre-Migration Testing

- [ ] All tests pass with SQLite
- [ ] Database backup created
- [ ] Dependencies documented

### Docker Testing

- [ ] Docker image builds successfully
- [ ] Containers start without errors
- [ ] Health checks pass
- [ ] Application accessible at http://localhost:8000
- [ ] API docs accessible at http://localhost:8000/docs
- [ ] Static files served correctly

### PostgreSQL Migration Testing

- [ ] PostgreSQL container healthy
- [ ] Alembic migrations run successfully
- [ ] Data migration completes without errors
- [ ] All API endpoints work with PostgreSQL
- [ ] Tests pass with PostgreSQL
- [ ] Concurrent connections handled properly

### Integration Testing

- [ ] Create user via API
- [ ] Create thread via API
- [ ] Create session via API
- [ ] Roll dice functionality works
- [ ] Queue management works
- [ ] Task system works

---

## Part 7: Known Gotchas and Troubleshooting

### Common Issues

#### 1. Connection Pool Exhaustion

**Symptom:** "server closed the connection unexpectedly" errors

**Solution:** Increase pool size in database.py:

```python
engine = create_engine(
    DATABASE_URL,
    pool_size=20,
    max_overflow=40,
    pool_pre_ping=True
)
```

#### 2. Timezone Issues

**Symptom:** Timestamps appear incorrect

**Solution:** Ensure PostgreSQL timezone is set:

```sql
ALTER DATABASE comicpile SET timezone TO 'UTC';
```

#### 3. Permission Errors

**Symptom:** "permission denied for table" errors

**Solution:** Grant proper permissions:

```sql
GRANT ALL PRIVILEGES ON DATABASE comicpile TO comicpile;
GRANT ALL PRIVILEGES ON SCHEMA public TO comicpile;
```

#### 4. Docker Volume Permission Issues

**Symptom:** Can't write to mounted volumes

**Solution:** Fix volume permissions:

```bash
docker-compose down
sudo chown -R 1000:1000 ./data  # Replace with user ID
docker-compose up -d
```

#### 5. Migration Conflicts

**Symptom:** Alembic detects schema drift

**Solution:** Generate new migration:

```bash
alembic revision --autogenerate -m "sync_with_postgresql"
```

### Debugging Commands

```bash
# Check PostgreSQL logs
docker-compose logs db

# Check application logs
docker-compose logs app

# Enter database shell
docker-compose exec db psql -U comicpile -d comicpile

# Check database size
docker-compose exec db psql -U comicpile -d comicpile -c "SELECT pg_size_pretty(pg_database_size('comicpile'));"

# Check active connections
docker-compose exec db psql -U comicpile -d comicpile -c "SELECT count(*) FROM pg_stat_activity;"

# Run Alembic in verbose mode
docker-compose exec app alembic upgrade head -v

# Check container health
docker-compose ps
```

---

## Part 8: Performance Optimization

### PostgreSQL Tuning

Add to `docker-compose.yml` under db service:

```yaml
command:
  - postgres
  - -c
  - shared_buffers=256MB
  - -c
  - max_connections=200
  - -c
  - effective_cache_size=1GB
  - -c
  - maintenance_work_mem=64MB
  - -c
  - checkpoint_completion_target=0.9
  - -c
  - wal_buffers=16MB
  - -c
  - default_statistics_target=100
  - -c
  - random_page_cost=1.1
  - -c
  - effective_io_concurrency=200
  - -c
  - work_mem=1310kB
  - -c
  - min_wal_size=1GB
  - -c
  - max_wal_size=4GB
```

### Application Optimization

Enable connection pooling:

```python
from sqlalchemy.pool import QueuePool

engine = create_engine(
    DATABASE_URL,
    poolclass=QueuePool,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    echo=False
)
```

---

## Part 9: Backup and Restore

### Automated Backups

Create `scripts/backup_postgres.sh`:

```bash
#!/bin/bash
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="./backups"
mkdir -p $BACKUP_DIR

docker-compose exec -T db pg_dump -U comicpile comicpile > $BACKUP_DIR/backup_$DATE.sql

echo "Backup created: $BACKUP_DIR/backup_$DATE.sql"

# Keep only last 7 backups
find $BACKUP_DIR -name "backup_*.sql" -mtime +7 -delete
```

Add to crontab:

```bash
# Daily backup at 2 AM
0 2 * * * /path/to/comic-pile/scripts/backup_postgres.sh
```

### Manual Restore

```bash
# Restore from backup
docker-compose exec -T db psql -U comicpile -d comicpile < backup_20240101_120000.sql
```

---

## Part 10: Security Considerations

### Database Security

- Change default passwords in production
- Use strong secrets (32+ random characters)
- Enable SSL for database connections (production)
- Restrict network access (don't expose port 5432 publicly)
- Use environment variables for sensitive data

### Container Security

- Use official base images
- Run as non-root user
- Scan images for vulnerabilities: `docker scan comic-pile:latest`
- Keep images updated: `docker-compose pull && docker-compose up -d`
- Use `.dockerignore` to exclude sensitive files

### Application Security

- Validate all inputs
- Use prepared statements (SQLAlchemy handles this)
- Enable CORS only for trusted origins
- Use HTTPS in production
- Set secure cookie flags
- Implement rate limiting

---

## Appendix: Quick Reference

### Essential Commands

```bash
# Docker
docker-compose up -d                    # Start services
docker-compose down                     # Stop services
docker-compose logs -f [service]         # View logs
docker-compose exec [service] [cmd]      # Run command in container
docker-compose ps                        # List containers

# Database
docker-compose exec db psql -U comicpile -d comicpile  # DB shell
alembic upgrade head                                     # Run migrations
alembic revision --autogenerate -m "message"            # Create migration
alembic downgrade base                                  # Rollback all

# Application
docker-compose exec app python -m scripts.seed_data      # Seed data
docker-compose exec app pytest                           # Run tests
```

### File Locations

- Dockerfile: `./Dockerfile`
- Docker Compose: `./docker-compose.yml`
- Migration script: `./scripts/migrate_sqlite_to_postgres.py`
- Environment example: `./.env.example`
- Database config: `./app/database.py`

---

## Resources

- [Docker Documentation](https://docs.docker.com/)
- [PostgreSQL Documentation](https://www.postgresql.org/docs/)
- [SQLAlchemy Documentation](https://docs.sqlalchemy.org/)
- [Alembic Documentation](https://alembic.sqlalchemy.org/)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [psycopg Documentation](https://www.psycopg.org/)
