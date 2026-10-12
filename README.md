# Comic Pile

**Roll to read. Rotate your stack.**

Comic Pile is an open-source, dice-driven comic-reading tracker for turning a comic backlog into an actual reading habit. It manages the reading queue, tracks sessions and ratings, and makes "what should I read next?" a roll instead of another round of sorting the pile.

[Live app](https://comic-pile.vercel.app) · [Deployment and Neon](docs/DEPLOYMENT.md) · [Contributing](CONTRIBUTING.md) · [Code of Conduct](CODE_OF_CONDUCT.md) · [MIT License](LICENSE)

## What Comic Pile does

- Uses dice-driven selection to rotate through a comic reading queue.
- Tracks reading sessions, issue progress, and ratings.
- Provides a React/Vite frontend backed by a FastAPI API.
- Stores application state in PostgreSQL and can be run from source with your own database.
- Uses Vercel and Neon for the maintained production deployment.

## Quick start

```bash
git clone https://github.com/JoshCLWren/comic-pile.git
cd comic-pile
cp .env.example .env
make setup
make dev
```

The frontend runs at `http://localhost:5173`. The FastAPI service and Swagger UI run at `http://localhost:8000` and `http://localhost:8000/docs`.

## Run with Neon

Comic Pile is a PostgreSQL application, so local development can use the bundled local database while a hosted installation can use Neon. The maintained production deployment runs on Neon.

The application accepts standard `postgresql://` or `postgres://` connection strings and normalizes them to the `asyncpg` driver at runtime. Alembic migrations use the synchronous `psycopg` driver. See [the deployment guide](docs/DEPLOYMENT.md#self-hosting-with-neon) for a complete Neon setup path, including runtime and migration connection guidance.

## Stack

- **Frontend:** React, Vite, Tailwind CSS
- **API:** FastAPI
- **Database:** PostgreSQL with SQLAlchemy and `asyncpg`
- **Migrations:** Alembic with `psycopg`
- **Production database:** Neon
- **Production hosting:** Vercel

## Common development commands

```bash
make dev        # frontend + API development servers
make dev-api    # API only
make migrate    # run Alembic migrations
make seed       # seed local sample data
make lint       # repository lint/type checks
make verify     # complete local verification suite
make verify-e2e # Chromium browser validation when required
make tidy       # sweep local generated artifacts
```

Application database access is async PostgreSQL via `asyncpg` and SQLAlchemy `AsyncSession`. Alembic migrations are the only supported synchronous database exception. Do not skip or weaken failing tests to force a green build.

## Production

Production deploys from `main` on Vercel. The frontend is static Vite output, API routes are served by FastAPI, and PostgreSQL is hosted by Neon. The production workflow runs database migrations against Neon before deploying the application.

Vercel Preview environments are intentionally unsupported. Fly.io and Railway are not current deployment targets.

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

For architectural decisions and system overview, see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). For deployment and self-hosting with Neon, see [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

Coding agents must also follow [`AGENTS.md`](AGENTS.md). Autonomous factory workers must follow [`docs/AUTONOMOUS_FACTORY_POLICY.md`](docs/AUTONOMOUS_FACTORY_POLICY.md) and [`docs/ISSUE_EXECUTION_PROTOCOL.md`](docs/ISSUE_EXECUTION_PROTOCOL.md).

What's New reads the database-backed release ledger. User-facing release notes are published after merge by the dedicated release writer. [`docs/changelog.md`](docs/changelog.md) and `docs/changelog.d/` are frozen historical migration sources retained only for provenance.

## Contributing

Comic Pile is actively developed in public. Bug reports, focused improvements, documentation fixes, and pull requests are welcome. Start with [`CONTRIBUTING.md`](CONTRIBUTING.md) and follow the project's [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).

## License

MIT. See [`LICENSE`](LICENSE).
