# Documentation Index

This index provides a comprehensive map of all documentation in the comic-pile project.

## Getting Started

- [README.md](../README.md) - Main project entry point, tech stack overview, quick start guide, and API documentation links.
- [CONTRIBUTING.md](../CONTRIBUTING.md) - Contribution guidelines, development workflow, code quality standards, and testing guidelines.

## Core Architecture

- [../prd.md](../prd.md) - Product Requirements Document (source of truth for project requirements).
- [API.md](API.md) - Complete API documentation with endpoints, request/response schemas, and examples.
- [REACT_ARCHITECTURE.md](REACT_ARCHITECTURE.md) - React stack details, component organization, state management, and migration notes.
- [TASK_API.md](TASK_API.md) - Task API reference for agent system - endpoints for claiming, updating, and managing tasks.

## Agent Systems

Documentation for the multi-agent coordination system used for automated development.

- [../AGENTS.md](../AGENTS.md) - Repository guidelines, RALPH_MODE configuration, git worktree management, and agent workflows.
- [RALPH_MODE.md](RALPH_MODE.md) - Ralph mode autonomous iteration guide - single agent workflow using GitHub Issues.
- [RALPH_GITHUB_SETUP.md](RALPH_GITHUB_SETUP.md) - GitHub setup guide for Ralph mode - Personal Access Token configuration and usage.
- [../MANAGER_DAEMON.md](../MANAGER_DAEMON.md) - Manager daemon responsibilities, setup, and integration with Worker Pool Manager.
- [../WORKER_WORKFLOW.md](../WORKER_WORKFLOW.md) - Worker workflow using Task API - complete end-to-end guide from claim to merge.
- [../MANAGER-7-PROMPT.md](../MANAGER-7-PROMPT.md) - Current manager agent coordination prompt with active monitoring and task handling.
- [../WORKFLOW_PATTERNS.md](../WORKFLOW_PATTERNS.md) - Proven successful patterns and critical failures to avoid from manager sessions.
- [../worker-pool-manager-prompt.txt](../worker-pool-manager-prompt.txt) - Worker Pool Manager agent prompt for automated worker spawning.

## Technical Documentation

- [DATABASE_SAVE_LOAD.md](DATABASE_SAVE_LOAD.md) - Database save/load functionality, export formats, and backup procedures.
- [rate_limiting.md](rate_limiting.md) - Rate limiting documentation - slowapi configuration and endpoint protection.
- [SQLITE_CLEANUP.md](SQLITE_CLEANUP.md) - SQLite cleanup notes and migration considerations.
- [OPENCODE_PERMISSIONS.md](OPENCODE_PERMISSIONS.md) - Permissions documentation for the opencode CLI tool.

## Exploratory Documentation

Technical explorations and research documents (may be superseded by implementation):

- [ANTI_BINGE_GOAL_TRACKING_EXPLORATION.md](ANTI_BINGE_GOAL_TRACKING_EXPLORATION.md) - Anti-binge goal tracking feature exploration.
- [SHARING_COLLABORATION_EXPLORATION.md](SHARING_COLLABORATION_EXPLORATION.md) - Sharing and collaboration feature exploration.

## Retrospectives

- [../retro/INDEX.md](../retro/INDEX.md) - Complete retrospective index with manager, worker, and audit retrospectives.
- [../retro.md](../retro.md) - Meta-retrospective file with project-wide retrospective analysis.

## Archived Documentation

Historical documentation is organized in [../archive/](../archive/) for reference:

- **archive/old-prompts/** - Superseded agent prompt files
- **archive/phase1/** - Phase 1 agent task documentation
- **archive/htmx-backup/** - Legacy frontend documentation (stack migrated to React)
- **archive/sessions/** - Session handoff and context documents
- **archive/exploration/** - Exploratory research documents (MCP, Docker, etc.)
- **archive/historical/** - Historical summaries and audit reports

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
- `retro/` - Agent retrospectives
- `migrations/` - Alembic migration files
