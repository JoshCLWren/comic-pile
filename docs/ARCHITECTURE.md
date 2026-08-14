# Comic Pile Architecture

## Overview

Comic Pile is a dice-driven comic reading tracker built with:
- **Backend**: Python 3.14, FastAPI, SQLAlchemy, PostgreSQL
- **Frontend**: React 19, Vite, Tailwind CSS
- **Package managers**: `uv` (Python), `pnpm` (frontend)
- **Deployment**: Vercel (static frontend + FastAPI API function)

## Key Architectural Decisions

### 1. Repository Structure: Monorepo
**Decision**: Keep frontend and backend in a single repository
**Documented in**: [REPOSITORY_STRUCTURE_DECISION.md](REPOSITORY_STRUCTURE_DECISION.md)
**Date**: 2026-08-13

**Rationale**:
- High coupling between frontend and backend due to OpenAPI-generated types
- Backend API changes frequently require frontend updates
- Unified local development experience with `make dev`
- Atomic deployments and rollbacks reduce version mismatch risks
- Simplified CI with single pipeline validating entire system
- Strong contract consistency with immediate feedback on breaking changes

**Alternatives Considered**:
- Split repositories: Would increase complexity without solving fundamental coupling
- Conclusion: Monorepo preferred for current coupling level

### 2. API Versioning Strategy
**Decision**: Partial versioning with `/api/*` (legacy) and `/api/v1/*` (canonical)
**Documented in**: [API.md](API.md)
**Key Points**:
- All new client resources must be added under `/api/v1/*`
- Legacy paths are retained as tested backwards-compatibility aliases
- Maintained first-party consumers should use `/api/v1/*` equivalents
- Non-production tooling routes (`debug`, `test`) under bare `/api/*` are exceptions

### 3. Frontend-Backend Communication
**Decision**: HTTP/JSON API with OpenAPI-generated frontend types
**Documented in**: 
- [FRONTEND_OPENAPI_TYPES.md](FRONTEND_OPENAPI_TYPES.md)
- [REACT_ARCHITECTURE.md](REACT_ARCHITECTURE.md) (services layer)

**Key Points**:
- Frontend uses Axios service layer with base URL `/api`
- OpenAPI schema generated from backend serves as contract
- Frontend types automatically generated from OpenAPI schema
- Strong typing ensures compile-time detection of API mismatches

### 4. Deployment Architecture
**Decision**: Vercel platform serving static frontend + API function
**Documented in**: 
- [VERCEL_ARCHITECTURE.md](VERCEL_ARCHITECTURE.md)
- [DEPLOYMENT.md](DEPLOYMENT.md)

**Key Points**:
- Frontend built as static output served from `/static/react/`
- API routes served by FastAPI function at `/api/*`
- Production deployments from `main` branch only
- Vercel Preview environments intentionally unsupported
- Database hosted externally (Neon PostgreSQL)

### 5. Data Storage
**Decision**: PostgreSQL with asyncpg for application runtime
**Documented in**: 
- [AGENTS.md](../AGENTS.md) (Critical: Async PostgreSQL Only in Application Code)
- [DATABASE_SAVE_LOAD.md](DATABASE_SAVE_LOAD.md)

**Key Points**:
- Application code must use asyncpg ONLY (no synchronous drivers in `app/` or `comic_pile/`)
- Alembic migrations use synchronous psycopg (only exception)
- `app/config.py` converts any `postgresql+psycopg://` URL back to `postgresql+asyncpg://` at runtime

### 6. Development Workflow
**Decision**: Unified local development with Docker and Makefile
**Documented in**: 
- [README.md](../README.md)
- [Makefile](../Makefile)
- [LOCAL_TESTING.md](../LOCAL_TESTING.md)

**Key Points**:
- `make dev` starts both frontend (Vite) and backend (FastAPI) servers
- Frontend proxies `/api` to backend during development
- Shared database and services for authentic development experience
- Database migrations managed via Alembic

## Infrastructure Choices

### Build Tools
- **Frontend**: Vite 7.x (fast builds, HMR)
- **Backend**: Standard Python packaging with UV
- **Database Migrations**: Alembic

### Styling
- **Framework**: Tailwind CSS 4.x (utility-first, PostCSS integration)
- **Configuration**: `tailwind.config.ts` with content scanning

### Type Safety
- **Backend**: Python with `ty` (strict type checking)
- **Frontend**: TypeScript with strict mode
- **Contracts**: OpenAPI schema as single source of truth

### Testing
- **Backend**: Pytest with coverage requirements (≥94%)
- **Frontend**: Vitest unit + Playwright E2E tests
- **Contract**: Automated OpenAPI type generation validation

## Communication Flows

### Data Flow
1. User interacts with React frontend
2. Frontend makes HTTP requests to `/api/*` endpoints
3. FastAPI backend processes requests, interacts with PostgreSQL
4. Backend returns JSON responses
5. Frontend updates React state and re-renders components

### Development Flow
1. Developer runs `make dev`
2. Vite dev server serves frontend on port 5173
3. FastAPI server serves API on port 8000 (proxied by Vite)
4. Changes to either trigger appropriate rebuilds/restarts
5. Frontend sees immediate updates via HMR

### Deployment Flow
1. Code pushed to `main` branch
2. Vercel builds frontend (static output) and deploys API function
3. Database migrations run via Alembic against production database
4. Traffic routed to new deployment
5. Rollback achieved by promoting previous deployment

## Boundary Definitions

### Frontend Responsibilities
- User interface and experience
- Client-side state management (React hooks/context)
- UI components and styling
- Local optimizations (caching, lazy loading)
- Browser compatibility and responsiveness

### Backend Responsibilities
- Business logic enforcement
- Data persistence and integrity
- API contract maintenance
- Authentication and authorization
- Background jobs and scheduled tasks
- Integration with external services (ComicVine, etc.)

### Shared Responsibilities
- API contract definition (via OpenAPI)
- Database schema (via Alembic/SQLAlchemy)
- Development experience (unified tooling)
- Deployment and monitoring

## Quality Attributes

### Performance
- Frontend: Code splitting, lazy loading, efficient bundling
- Backend: Async PostgreSQL, connection pooling, caching strategies
- Network: Minimal payloads, efficient serialization
- Build: Fast incremental builds, efficient CI

### Scalability
- Backend: Designed for horizontal scaling (stateless services)
- Database: Externalized (Neon) for independent scaling
- Frontend: Naturally scalable (static CDN delivery)
- Caching: HTTP caching for static assets, API response caching where appropriate

### Maintainability
- Clear separation of concerns
- Strong typing reduces runtime errors
- Automated testing prevents regressions
- Documentation coupled with code changes
- Consistent coding standards (AGENTS.md)

### Security
- Authentication via JWT tokens
- Input validation and sanitization
- Protection against common web vulnerabilities (CSRF, XSS, etc.)
- Secure defaults for headers and cookies
- Regular dependency updates

## Related Documentation

- [AGENTS.md](../AGENTS.md): Project guidelines and conventions for coding agents
- [API.md](API.md): Complete API reference documentation
- [REACT_ARCHITECTURE.md](REACT_ARCHITECTURE.md): Frontend-specific architecture
- [VERCEL_ARCHITECTURE.md](VERCEL_ARCHITECTURE.md): Deployment architecture details
- [FRONTEND_OPENAPI_TYPES.md](FRONTEND_OPENAPI_TYPES.md): Frontend type generation details
- [AUTONOMOUS_FACTORY_POLICY.md](AUTONOMOUS_FACTORY_POLICY.md): Autonomous factory workflow
- [ISSUE_EXECUTION_PROTOCOL.md](ISSUE_EXECUTION_PROTOCOL.md): Issue execution guidelines

## Change Log

This document reflects architectural decisions as of 2026-08-13. For historical decisions, see:
- Git commit history
- Associated issue discussions
- Documentation in `docs/changelog.d/` (frozen historical provenance)