# Comic Pile

[![Comic Pile Roll page: a large 3D die showing the faces 4 and 1 above a "Roll Again" button, with the in-play queue listing Superman, Batman, The Flash, and Aquaman](docs/images/roll-hero.png)](https://comic-pile.vercel.app)

**[▶ Try the live demo at comic-pile.vercel.app](https://comic-pile.vercel.app)**

**Roll to read. Rotate your stack.**

[![GitHub stars](https://img.shields.io/github/stars/JoshCLWren/comic-pile?style=social&label=Stars)](https://github.com/JoshCLWren/comic-pile)

If Comic Pile helps you pick your next read, star the repo ⭐

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

## Self-hosting / local quickstart

Comic Pile runs from source against a standard PostgreSQL database. The local path below uses the repository's bundled Docker Compose PostgreSQL service (host port **5435**) and does not require Neon. For a hosted Neon database instead, see [Self-hosting with Neon](docs/DEPLOYMENT.md#self-hosting-with-neon).

### Prerequisites

- Docker (for PostgreSQL)
- Python 3.14 and `uv`
- Node.js and `pnpm`

### 1. Clone and configure

```bash
git clone https://github.com/JoshCLWren/comic-pile.git
cd comic-pile
cp .env.example .env
```

Edit `.env` as needed. The local defaults in `.env.example` already point at the bundled database:

```dotenv
DATABASE_URL=postgresql+asyncpg://comicpile:comicpile_password@localhost:5435/comicpile
```

### 2. Environment variables

| Variable | Required? | Notes |
| --- | --- | --- |
| `DATABASE_URL` | Yes | Default local: `postgresql+asyncpg://comicpile:comicpile_password@localhost:5435/comicpile` |
| `SECRET_KEY` | Yes | Generate with `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `ENVIRONMENT` | No (defaults) | `development` / `production` / `test` |
| `CORS_ORIGINS` | Required in production | Comma-separated origins |
| `COMICVINE_API_KEY` | Optional | Used by ComicVine hydrator/backfill scripts (`docs/COMICVINE_HYDRATOR.md`); not listed in `.env.example` |

See `.env.example` for additional optional settings (access-token lifetime, logging, rating system, etc.). Do not invent variable names; only names present in `.env.example` or existing docs are supported.

### 3. Start PostgreSQL and bootstrap

`make setup` starts the local PostgreSQL container, waits for it to be ready, installs Python and frontend dependencies, runs Alembic migrations, and seeds deterministic demo data:

```bash
make setup
```

This uses `docker compose up -d db`, which exposes PostgreSQL on host port **5435** (container port 5432). Data persists in the `postgres_data` Docker volume.

If you prefer to manage containers yourself, the equivalent is:

```bash
docker compose up -d db
# wait for readiness, then:
uv sync --all-extras
pnpm install --frozen-lockfile
make migrate
make seed-dev
```

The full Compose stack is also available (`docker compose up -d`), which additionally runs the API on `http://localhost:8003` and pgAdmin on `http://localhost:5051`. The frontend is not served by Compose; run it separately (step 4).

### 4. Run the app

```bash
make dev
```

This starts the Vite frontend and the FastAPI API together. Alternatively, run only the API with `make dev-api`.

### ComicVine API key (optional)

Comic Vine integration is optional for a basic local run; the app works without it. A key is only needed for live ComicVine hydration/backfill (see [`docs/COMICVINE_HYDRATOR.md`](docs/COMICVINE_HYDRATOR.md)).

To obtain a key:

1. Create an account and sign in at [comicvine.gamespot.com](https://comicvine.gamespot.com).
2. Open your account/API key page and request an API key.
3. Set it in your environment when running the hydrator/backfill scripts:

```bash
COMICVINE_API_KEY=your-key uv run python scripts/hydrate_comicvine_issues.py --user-id 1 --live-refresh --output .cache/comicvine-hydrator/user-1-live.json
```

For local-first runs with the hydrator script, use the `--comicvine-db` parameter and omit `--live-refresh` to avoid requiring an API key:

```bash
uv run python scripts/hydrate_comicvine_issues.py --user-id 1 --comicvine-db ./localcv.db --output .cache/comicvine-hydrator/user-1-report.json
```

Other scripts use environment variables for local snapshots:
- `scripts/backfill_read_comicvine.py` uses `COMICVINE_LOCAL_DB`
- `comic_pile/local_comicvine.py` uses `COMICPILE_COMICVINE_SQLITE_PATH`

### 5. Verify the app is up

After `make setup` + `make dev` (or the Compose equivalent):

- Frontend: [http://localhost:5173](http://localhost:5173)
- API / Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)
- Dependency health: `GET http://localhost:8000/api/v1/health/dependencies`

A healthy local response from the dependency endpoint confirms the API can reach PostgreSQL. The endpoint is open whenever `HEALTH_CHECK_TOKEN` is unset, regardless of `ENVIRONMENT`. In production, set `HEALTH_CHECK_TOKEN` in the server's environment and send its value in the `X-Health-Token` header.

### Neon (hosted) path

Neon remains the maintained production database. For self-hosting on Neon, follow [Self-hosting with Neon](docs/DEPLOYMENT.md#self-hosting-with-neon). The local path above stands on its own without Neon.

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
