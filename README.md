# Comic Pile

Comic Pile is a dice-driven comic-reading tracker built with FastAPI, React, Vite, Tailwind CSS, and PostgreSQL.

## Quick start

```bash
git clone https://github.com/JoshCLWren/comic-pile.git
cd comic-pile
cp .env.example .env
make setup
make dev
```

The frontend runs at `http://localhost:5173`. The FastAPI service and Swagger UI run at `http://localhost:8000` and `http://localhost:8000/docs`.

## Common development commands

```bash
make dev        # frontend + API development servers
make dev-api    # API only
make migrate    # run Alembic migrations
make seed       # seed local sample data
make lint       # repository lint/type checks
make verify     # complete local verification suite
make verify-e2e # Chromium browser validation when required
```

Application database access is async PostgreSQL via `asyncpg` and SQLAlchemy `AsyncSession`. Alembic migrations are the only supported synchronous database exception. Do not skip or weaken failing tests to force a green build.

## Production

Production deploys from `main` on Vercel. The frontend is static Vite output, API routes are served by FastAPI, and PostgreSQL is hosted by Neon. Vercel Preview environments are intentionally unsupported. Fly.io and Railway are not current deployment targets.

## Repository map

- `app/`: FastAPI application and API routes
- `comic_pile/`: core queue, roll, session, and reading logic
- `frontend/`: React/Vite frontend
- `alembic/`: database migrations
- `tests/`: pytest coverage
- `tests_e2e/`: maintained browser scenarios
- `scripts/`: operational and development utilities
- `docs/`: code-coupled documentation and the authoritative documentation index

## Documentation

Start with [`docs/README.md`](docs/README.md). It identifies the authoritative repository documentation, what must remain versioned with code, and what belongs in the GitHub Wiki.

Coding agents must also follow [`AGENTS.md`](AGENTS.md). Autonomous factory workers must follow [`docs/AUTONOMOUS_FACTORY_POLICY.md`](docs/AUTONOMOUS_FACTORY_POLICY.md) and [`docs/ISSUE_EXECUTION_PROTOCOL.md`](docs/ISSUE_EXECUTION_PROTOCOL.md).

The product changelog is assembled from `docs/changelog.d/` fragments plus the frozen historical archive at [`docs/changelog.md`](docs/changelog.md).

## License

MIT. See [`LICENSE`](LICENSE).
