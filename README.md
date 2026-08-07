# ComicPile

ComicPile is a dice-driven comic reading tracker built with FastAPI, React, Vite, Tailwind CSS, PostgreSQL, and SQLAlchemy.

## Start here

- [Documentation hub](docs/README.md): authoritative index for repository documentation and documentation ownership.
- [AGENTS.md](AGENTS.md): mandatory engineering rules for coding agents.
- [CONTRIBUTING.md](CONTRIBUTING.md): development workflow and quality requirements.
- [Product changelog](docs/changelog.md): historical What’s New archive; new entries live in `docs/changelog.d/`.

## Local development

```bash
git clone https://github.com/JoshCLWren/comic-pile.git
cd comic-pile
cp .env.example .env
make setup
make dev
```

Open the frontend at `http://localhost:5173`. The FastAPI service and Swagger UI are available at `http://localhost:8000` and `http://localhost:8000/docs`.

Common commands:

```bash
make dev          # frontend + API development servers
make dev-api      # API only
make verify       # complete local verification suite
make verify-e2e   # maintained browser tests
make lint         # lint and type checks
make migrate      # run Alembic migrations
make seed         # seed local sample data
```

Tests are requirements, not obstacles. Fix failures rather than skipping, disabling, or weakening meaningful coverage.

## Architecture

- **Frontend:** React + Vite + Tailwind CSS, built as static output.
- **API:** FastAPI on Python 3.14.
- **Database:** PostgreSQL hosted by Neon in production.
- **Application database access:** async SQLAlchemy via `asyncpg`.
- **Migrations:** Alembic; synchronous `psycopg` is limited to migration tooling.
- **Production deployment:** Vercel from `main` only. Preview environments are intentionally unsupported.

Fly.io and Railway are not current deployment targets.

## Repository layout

```text
app/          FastAPI application and API routes
comic_pile/   core reading, queue, roll, and session logic
frontend/     React/Vite frontend
docs/         authoritative code-coupled documentation
alembic/      database migrations
scripts/      repository and operational tooling
tests/        Python tests
tests_e2e/    Playwright browser coverage
```

See [docs/README.md](docs/README.md) before adding or moving Markdown. Code-coupled contracts stay in the repository; owner-facing explanations, FAQs, longer troubleshooting narratives, and durable history belong in the GitHub Wiki when they do not need to change atomically with code.

## Database rule

Application code is async-only for PostgreSQL. Use `asyncpg`, `create_async_engine()`, and `AsyncSession` in application paths. Do not introduce synchronous SQLAlchemy sessions or `psycopg2` into `app/` or `comic_pile/`.

## Quality

The project uses pytest, Ruff, and `ty`. Run `make verify` before treating a change as complete. Coverage and additional repository-specific requirements are defined by the checked-in project configuration and [AGENTS.md](AGENTS.md), which take precedence over duplicated prose here.

## License

MIT. See [LICENSE](LICENSE).
