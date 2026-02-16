# Documentation Index

This index provides a comprehensive map of all documentation in the comic-pile project.

## Getting Started

- [README.md](../README.md) - Main project entry point, tech stack overview, quick start guide, and API documentation links.
- [CONTRIBUTING.md](../CONTRIBUTING.md) - Contribution guidelines, development workflow, code quality standards, and testing guidelines.

## Core Architecture

- [../prd.md](../prd.md) - Product Requirements Document (source of truth for project requirements).
- [API.md](API.md) - Complete API documentation with endpoints, request/response schemas, and examples.
- [REACT_ARCHITECTURE.md](REACT_ARCHITECTURE.md) - React stack details, component organization, state management, and migration notes.
- [AUTH_USERS_MULTITENANT_PLAN.md](AUTH_USERS_MULTITENANT_PLAN.md) - Step-by-step plan for JWT auth, multi-user isolation, and React-only modernization.

## Technical Documentation

- [DATABASE_SAVE_LOAD.md](DATABASE_SAVE_LOAD.md) - Database save/load functionality, export formats, and backup procedures.
- [rate_limiting.md](rate_limiting.md) - Rate limiting documentation - slowapi configuration and endpoint protection.

## Current Stack

**Backend:**
- FastAPI (Python 3.13)
- PostgreSQL with SQLAlchemy ORM
- Alembic for migrations

**Frontend:**
- React + Vite
- Tailwind CSS for styling

**Testing:**
- pytest for backend API tests
- Playwright for E2E tests
- Coverage target: 96%

**Code Quality:**
- ruff for linting
- pyright for type checking
- ESLint for JavaScript
- htmlhint for HTML

## Quick Reference

**Development:**
```bash
make dev          # Start FastAPI dev server
pytest            # Run tests
make lint         # Run linters (ruff, pyright)
make pytest       # Run tests with coverage
make seed         # Populate sample data
make migrate      # Run database migrations
```

**API Documentation:**
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

**Key Directories:**
- `app/` - FastAPI application (api/, models/, schemas/, templates/)
- `comic_pile/` - Core package (dice ladder, queue, session logic)
- `tests/` - pytest test suite
- `frontend/` - React frontend application
- `docs/` - Technical documentation
- `migrations/` - Alembic migration files

## Archived Documentation

Historical documentation is organized in [../archive/](../archive/) for reference:

- **archive/htmx-backup/** - Legacy frontend documentation (stack migrated to React)
- **archive/exploration/** - Exploratory research documents (MCP, Docker, etc.)
- **archive/historical/** - Historical summaries and audit reports
