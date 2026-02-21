# Documentation Index

This index provides a comprehensive map of all documentation in the comic-pile project.

## Getting Started

- [README.md](../README.md) — Project overview, quick start, and development workflow.
- [CONTRIBUTING.md](../CONTRIBUTING.md) — Development workflow, code quality standards, and testing guidelines.
- [LOCAL_TESTING.md](../LOCAL_TESTING.md) — Local test environment setup with sample data and fixtures.

## Architecture & Design

- [prd.md](../prd.md) — Product Requirements Document (source of truth for product rules and design).
- [REACT_ARCHITECTURE.md](REACT_ARCHITECTURE.md) — React frontend architecture, component hierarchy, hooks, and build pipeline.
- [API.md](API.md) — Complete REST API documentation with endpoints, schemas, and examples.
- [AUTH_USERS_MULTITENANT_PLAN.md](AUTH_USERS_MULTITENANT_PLAN.md) — JWT auth implementation plan and multi-tenant isolation (Phases 1-7 complete).

## Operations & Infrastructure

- [DATABASE_SAVE_LOAD.md](DATABASE_SAVE_LOAD.md) — PostgreSQL backups, JSON export/import, and disaster recovery.
- [rate_limiting.md](rate_limiting.md) — slowapi rate limiting configuration and per-endpoint limits.
- [GIT_HOOKS.md](GIT_HOOKS.md) — Pre-commit and pre-push hook setup for code quality enforcement.
- [frontend-backend-asset-coupling-audit.md](frontend-backend-asset-coupling-audit.md) — Asset pipeline audit findings and remediation plan.
- [../ROLLBACK.md](../ROLLBACK.md) — Database, Docker, and git rollback procedures.
- [../SECURITY.md](../SECURITY.md) — Docker security, SSL/TLS, secrets management, and container hardening.

## Project Health

- [../TECH_DEBT.md](../TECH_DEBT.md) — Technical debt tracker with prioritized items and resolution history.
- [../AGENTS.md](../AGENTS.md) — AI agent guidelines and project conventions.

## Testing

- [../tests_e2e/README.md](../tests_e2e/README.md) — E2E test suites (Python Playwright and TypeScript Playwright).
- [../frontend/src/test/README.md](../frontend/src/test/README.md) — TypeScript Playwright test structure and usage.
- [../scripts/README_thread_management.md](../scripts/README_thread_management.md) — Thread queue audit and fix scripts.

## Archived

Historical documentation is in [../archive/](../archive/) for reference:
- **archive/historical/** — Audit reports, implementation summaries, and PRD compliance reviews.
- **archive/exploration/** — Exploratory research (MCP, sharing, anti-binge features).
