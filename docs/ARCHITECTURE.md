# Comic Pile Architecture

## Overview

Comic Pile is a dice-driven comic reading tracker built with:

- **Backend**: native Rust (`native/roll-service`, axum, `tokio-postgres`), deployed through the Vercel function `api/native_roll.rs`
- **Frontend**: React 19, Vite, Tailwind CSS
- **Database**: PostgreSQL; migrations run with the Rust refinery runner (`native/migrate`)
- **Package managers**: `cargo`, `pnpm` (frontend), `uv` (Python tooling scripts and checks only)
- **Deployment**: Vercel (static frontend + one native Rust API function)

No Python application code remains. `app/`, `comic_pile/`, and the Alembic
migration tree were removed during the Rust cutover; Python dependencies are
limited to repository tooling and the hand-run QA mirror refresh script.

## Key Architectural Decisions

### 1. Repository Structure: Monorepo

**Decision**: Keep frontend, native backend, migrations and deployment ingress in a single repository

**Documented in**: [REPOSITORY_STRUCTURE_DECISION.md](REPOSITORY_STRUCTURE_DECISION.md)

**Rationale**:

- High coupling between frontend and backend through the generated OpenAPI contract
- A single Cargo workspace and root `Cargo.lock` cover the deployed ingress, the service and the migration runner
- Unified local development with `make dev`
- Atomic frontend + API deployments reduce version mismatch risks
- Strong contract consistency with immediate feedback on breaking changes

### 2. API Versioning Strategy

**Decision**: `/api/v2/*` is the current client surface; the version segment never identifies the implementation language

**Documented in**: [API.md](API.md) and `docs/api/v2-route-inventory.json`

**Key Points**:

- New client resources are added under `/api/v2/*`
- Older `/api/v1/*` and unversioned aliases survive only where the generated inventory lists an active contract
- Every deployed `/api/*` operation is served by native Rust; an API version is a wire contract, not a runtime
- `docs/api/v2-route-inventory.json` is the authoritative per-operation inventory of consumers and ingress destinations
- Route source fragments live in `docs/api/route-fragments/`; `vercel.json` and the inventory are generated and bot-owned

### 3. Frontend-Backend Communication

**Decision**: HTTP/JSON API with OpenAPI-generated frontend types

**Documented in**:

- [FRONTEND_OPENAPI_TYPES.md](FRONTEND_OPENAPI_TYPES.md)
- [REACT_ARCHITECTURE.md](REACT_ARCHITECTURE.md) (query + services layer)

**Key Points**:

- Frontend uses an Axios service layer with base URL `/api`
- Server state is managed exclusively with TanStack Query; all cache writes and
  invalidations live in `frontend/src/query/cacheEffects.ts` (`queryKeys` +
  `queryClient` in `frontend/src/query/`)
- The checked-in contract (`frontend/src/generated/openapi.json` and `openapi.ts`)
  is generated from the native Rust DTOs plus retained legacy operations
- Strong typing ensures compile-time detection of API mismatches

### 4. Deployment Architecture

**Decision**: Vercel serves the static frontend and a single native Rust API function

**Documented in**:

- [VERCEL_ARCHITECTURE.md](VERCEL_ARCHITECTURE.md)
- [DEPLOYMENT.md](DEPLOYMENT.md)

**Key Points**:

- Frontend built as static output served from `/static/react/`
- `vercel.json` routes every `/api/*` request to `api/native_roll.rs`; unknown API paths return a Rust JSON 404
- Production deployments from `main` branch only
- Vercel Preview environments intentionally unsupported
- Database hosted externally (Neon PostgreSQL)

### 5. Data Storage

**Decision**: PostgreSQL accessed asynchronously from Rust

**Documented in**:

- [DATABASE_SAVE_LOAD.md](DATABASE_SAVE_LOAD.md)
- [AGENTS.md](../AGENTS.md)

**Key Points**:

- The Rust service uses `deadpool-postgres` / `tokio-postgres`
- Schema changes are append-only SQL migrations under `native/migrate/migrations/`
  applied by the `comicpile-migrate` binary; Alembic is retired
- Production startup rejects a non-TLS database URL

### 6. Development Workflow

**Decision**: Local PostgreSQL plus the Rust and Vite dev servers

**Documented in**:

- [README.md](../README.md)
- [Makefile](../Makefile)
- [LOCAL_TESTING.md](../LOCAL_TESTING.md)

**Key Points**:

- `make setup` starts PostgreSQL, installs frontend dependencies and applies migrations
- `make dev` starts Vite (`:5173`) and the native Rust service (`:8010`)
- Vite proxies `/api` to the native service using the same ingress rules as `vercel.json`
- The native service reads `RUST_ROLL_DATABASE_URL` and `RUST_ROLL_JWT_SECRET` directly; it does not load `.env`

### 7. Backend Layering

**Decision**: Keep HTTP handling, domain logic, and persistence in distinct Rust modules

**Documented in**: [AGENTS.md](../AGENTS.md)

**Key Points**:

- Axum handlers and route registration live in `native/roll-service/src/lib.rs`
  and per-resource modules (`roll_offer.rs`, `continuity_plans.rs`, ...)
- Shared connection-pool and SQL helpers live in `native/roll-service/src/db.rs`
- Request and response DTOs derive `serde`/`utoipa` so the generated contract stays
  aligned with the handlers
- Every native route module requires a DB-backed HTTP test; the
  `native-route-db-test-guard` CI job enforces this
- The former Python router/service/repository layout and its conformance test
  were retired with the Python API

## Infrastructure Choices

### Build Tools

- **Frontend**: Vite (fast builds, HMR)
- **Backend**: Cargo workspace with a single root `Cargo.lock`
- **Database Migrations**: refinery runner (`native/migrate`)

### Styling

- **Framework**: Tailwind CSS 4.x (utility-first, PostCSS integration)
- **Configuration**: `frontend/tailwind.config.ts` with content scanning

### Type Safety

- **Backend**: Rust's type system plus generated `utoipa` schemas
- **Frontend**: TypeScript with strict mode
- **Contracts**: generated native OpenAPI contracts plus the same-path compatibility contract feed the checked-in client schema

### Testing

- **Backend**: `cargo test --workspace`, including DB-backed HTTP tests
- **Frontend**: Vitest unit tests plus Chromium Playwright E2E
- **Repository tooling**: focused pytest and Node test files under `tests/`
- **Contract**: generated OpenAPI freshness check in CI

## Communication Flows

### Data Flow

1. User interacts with the React frontend
2. Frontend makes HTTP requests to `/api/v2/*` resources or a retained compatibility path
3. The native Rust handler validates the request, applies auth and ownership rules, and queries PostgreSQL
4. The handler returns JSON
5. Frontend updates the TanStack Query cache and re-renders

### Development Flow

1. Developer runs `make dev`
2. Vite serves the frontend on port 5173
3. The native Rust service listens on port 8010
4. Vite proxies `/api` to the Rust service; Vite hot-reloads frontend changes
5. Frontend sees immediate updates via HMR; restart the native service after Rust changes

### Deployment Flow

1. Code pushed to `main`
2. The production workflow applies migrations to Neon with `comicpile-migrate`
3. Vercel builds the static frontend and the `api/native_roll.rs` function
4. Traffic routes to the new deployment
5. Rollback is achieved by promoting a previous deployment

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
- Integration with external services (ComicVine, GitHub factory reads, etc.)

### Shared Responsibilities

- API contract definition (via the generated OpenAPI schema)
- Database schema (via `native/migrate` SQL migrations)
- Development experience (Makefile + Cargo/pnpm tooling)
- Deployment and monitoring

## Quality Attributes

### Performance

- Frontend: code splitting, lazy loading, bounded queries
- Backend: asynchronous PostgreSQL access with a bounded connection pool
- Network: minimal payloads, cursor pagination for collections
- Build: single Cargo workspace and lockfile

### Scalability

- Backend: reader data is externalized in PostgreSQL; bounded process-local safeguards protect startup and rate limits
- Database: externalized (Neon) for independent scaling
- Frontend: static CDN delivery

### Maintainability

- Clear separation of concerns
- Strong typing on both sides of the contract
- Automated testing prevents regressions
- Documentation coupled with code changes
- Consistent coding standards (`AGENTS.md`)

### Security

- JWT authentication with refresh cookies and credential epochs
- Ownership checks scoped to the authenticated user
- CSRF protection on state-changing requests
- Secure defaults for headers and cookies
- Regular dependency updates

## Canonical Reader Order

**Decision** (#1619): `continuity_plans` is the canonical reader-owned reading
plan; `reading_orders` is a legacy compatibility view. New ordering intent
must target the canonical plan. Legacy orders remain readable and can be
adopted via the native `POST /api/v2/continuity-plans/from-reading-order`
without data loss; projection `plan → reading_order` remains only as
export/migration tooling. Within-series `Issue.position` is never compiled into
blocking `ContinuityRule` edges unless the user explicitly chooses
`strict_sequential`. See [READING_PLAN_CANONICAL_MODEL.md](READING_PLAN_CANONICAL_MODEL.md).

## Related Documentation

- [READING_PLAN_CANONICAL_MODEL.md](READING_PLAN_CANONICAL_MODEL.md): Canonical reader-order decision record for #1619
- [AGENTS.md](../AGENTS.md): Project guidelines and conventions for coding agents
- [API.md](API.md): API reference and versioning rules
- [REACT_ARCHITECTURE.md](REACT_ARCHITECTURE.md): Frontend-specific architecture
- [VERCEL_ARCHITECTURE.md](VERCEL_ARCHITECTURE.md): Deployment ingress details
- [FRONTEND_OPENAPI_TYPES.md](FRONTEND_OPENAPI_TYPES.md): Frontend type generation details
- [AUTONOMOUS_FACTORY_POLICY.md](./AUTONOMOUS_FACTORY_POLICY.md): Autonomous factory workflow
- [ISSUE_EXECUTION_PROTOCOL.md](ISSUE_EXECUTION_PROTOCOL.md): Issue execution guidelines

## Change Log

This document reflects the native-Rust architecture. The earlier Python/FastAPI
service, SQLAlchemy model layer, and Alembic migrations are historical; see Git
history and `docs/changelog.d/` (frozen provenance).
