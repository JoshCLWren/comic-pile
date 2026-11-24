# Comic Pile

[![Comic Pile Roll page: a large 3D die showing the faces 4 and 1 above a "Roll Again" button, with the in-play queue listing Superman, Batman, The Flash, and Aquaman](docs/images/roll-hero.png)](https://comic-pile.vercel.app)

**[▶ Try the live demo at comic-pile.vercel.app](https://comic-pile.vercel.app)**

**Data provided by [ComicVine](https://comicvine.gamespot.com)**

**Roll to read. Rotate your stack.**

[![GitHub stars](https://img.shields.io/github/stars/JoshCLWren/comic-pile?style=social&label=Stars)](https://github.com/JoshCLWren/comic-pile)

If Comic Pile helps you pick your next read, star the repo ⭐

Comic Pile is an open-source, dice-driven comic-reading tracker for turning a comic backlog into an actual reading habit. It manages the reading queue, tracks sessions and ratings, and makes "what should I read next?" a roll instead of another round of sorting the pile.

[Live app](https://comic-pile.vercel.app) · [Deployment and Neon](docs/DEPLOYMENT.md) · [Contributing](CONTRIBUTING.md) · [Code of Conduct](CODE_OF_CONDUCT.md) · [MIT License](LICENSE)

## What Comic Pile does

- Uses dice-driven selection to rotate through a comic reading queue.
- Tracks reading sessions, issue progress, and ratings.
- Provides a React/Vite frontend backed by a native Rust API.
- Stores application state in PostgreSQL and can be run from source with your own database.
- Uses Vercel and Neon for the maintained production deployment.

## Quick start

Prerequisites:

- Docker (for PostgreSQL)
- A Rust toolchain (`rustup`; the workspace pins its toolchain in `rust-toolchain.toml`)
- Node.js and `pnpm` (the repository pins `pnpm@10.15.0`)
- Python 3.14 and `uv` only for the repository's Python lint/type/tooling checks

```bash
git clone https://github.com/JoshCLWren/comic-pile.git
cd comic-pile
cp .env.example .env
# edit .env and set SECRET_KEY (python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
set -a; . ./.env; set +a
export RUST_ROLL_DATABASE_URL=postgresql://comicpile:comicpile_password@localhost:5435/comicpile
export RUST_ROLL_JWT_SECRET="$SECRET_KEY"
make setup
make dev
```

The frontend runs at `http://localhost:5173`. The native Rust API runs at
`http://localhost:8010`, with liveness at
`http://localhost:8010/api/v2/health`. Vite proxies `/api` to the native
service, so the browser uses one origin.

Neither `make setup` nor the native service reads `.env` automatically:

- `make migrate` (run by `make setup`) reads `MIGRATE_DATABASE_URL`, falling back
  to `DATABASE_URL`, and accepts the SQLAlchemy `+asyncpg`/`+psycopg` suffixes.
- The native service reads `RUST_ROLL_DATABASE_URL` and `RUST_ROLL_JWT_SECRET`
  directly and does not strip driver suffixes, so the exported URL above is a
  plain `postgresql://` URL.

Re-run the `set -a; . ./.env; set +a` and `export` lines in any new shell that
runs `make setup` or `make dev`.

There is no seed command and no Swagger UI. Register an account in the running
app to build your first queue, or use the read-only guest Demo page at `/demo`.

## Self-hosting / local quickstart

Comic Pile runs from source against a standard PostgreSQL database. The local
path below uses the repository's bundled Docker Compose PostgreSQL service
(host port **5435**) and does not require Neon. For a hosted Neon database
instead, see [Self-hosting with Neon](docs/DEPLOYMENT.md#self-hosting-with-neon).

### Prerequisites

- Docker (for PostgreSQL)
- Rust and Cargo
- Node.js and `pnpm`
- Python 3.14 and `uv` for repository checks (optional for running the app)

### 1. Clone and configure

```bash
git clone https://github.com/JoshCLWren/comic-pile.git
cd comic-pile
cp .env.example .env
```

Edit `.env` as needed. The local defaults in `.env.example` already point at
the bundled database:

```dotenv
DATABASE_URL=postgresql+asyncpg://comicpile:comicpile_password@localhost:5435/comicpile
```

### 2. Environment variables

| Variable | Required? | Notes |
| --- | --- | --- |
| `DATABASE_URL` | Yes | Used by the migration runner. Default local: `postgresql+asyncpg://comicpile:comicpile_password@localhost:5435/comicpile` |
| `RUST_ROLL_DATABASE_URL` | Yes, for the local native service | Must use a plain `postgresql://` URL; the native config does not strip driver suffixes |
| `SECRET_KEY` / `RUST_ROLL_JWT_SECRET` | Yes | JWT signing secret. Generate with `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `RUST_ROLL_ENV` | No (defaults) | `development` / `production`; development must bind to a loopback address |
| `RUST_ROLL_BIND` | No | Defaults to `127.0.0.1:8010` |
| `COMICVINE_API_KEY` | Optional | Enables live ComicVine provider calls from the native service; not listed in `.env.example` |

Production startup also accepts the existing `DATABASE_URL` and `SECRET_KEY`
names in the Vercel entrypoint. The standalone native binary instead requires
`RUST_ROLL_DATABASE_URL` and `RUST_ROLL_JWT_SECRET`; it does not read `.env` or
normalize SQLAlchemy URL prefixes. The migration runner accepts
`MIGRATE_DATABASE_URL` or `DATABASE_URL` and normalizes the supported driver
prefixes. Do not invent variable names; use only names present in `.env.example`,
the native configuration, or current docs.

### 3. Start PostgreSQL and bootstrap

`make setup` starts the local PostgreSQL container, waits for it to be ready,
installs frontend dependencies, and applies the migrations with the Rust
refinery runner (`native/migrate`):

```bash
set -a; . ./.env; set +a
make setup
```

This uses `docker compose up -d db`, which exposes PostgreSQL on host port
**5435** (container port 5432). Data persists in the `postgres_data` Docker
volume.

If you prefer to manage containers yourself, the equivalent is:

```bash
docker compose up -d db
# wait for readiness, then:
pnpm install --frozen-lockfile
make migrate
```

The Compose file also defines pgAdmin on `http://localhost:5051`. The frontend
and API are not served by Compose; run them with `make dev`.

### 4. Run the app

```bash
export RUST_ROLL_DATABASE_URL=postgresql://comicpile:comicpile_password@localhost:5435/comicpile
export RUST_ROLL_JWT_SECRET="$SECRET_KEY"
make dev
```

`make dev` starts the Vite frontend and the native Rust Roll/auth service
together. Use `make dev-frontend` or `make dev-native` to run either half on
its own. See [`docs/E2E_CHROMIUM_REGRESSION.md`](docs/E2E_CHROMIUM_REGRESSION.md)
for the same-origin ingress used by Playwright.

### ComicVine API key (optional)

ComicVine integration is optional for a basic local run. Set `COMICVINE_API_KEY`
in the native service environment to enable live provider calls used by the
in-app search, import, identity and metadata endpoints. Without a key, those
provider-dependent operations are unavailable, but local reading and Roll still
work.

The former Python hydrator/backfill CLIs and local SQLite snapshot workflow were
retired with the Python application. No replacement operator CLI is shipped;
do not follow historical hydrator commands as current instructions.

### 5. Verify the app is up

After `make setup` + `make dev`:

- Frontend: [http://localhost:5173](http://localhost:5173)
- Native API liveness: `GET http://localhost:8010/api/v2/health` (HTTP 200, `{"status":"ok"}`)
- Same-origin through Vite: `GET http://localhost:5173/api/v2/health`

The liveness endpoint does not open a database connection. If it answers but
data requests fail, check the database URL exported to the native service and
run `make migrate`.

### Neon (hosted) path

Neon remains the maintained production database. For self-hosting on Neon, follow [Self-hosting with Neon](docs/DEPLOYMENT.md#self-hosting-with-neon). The local path above stands on its own without Neon.

## Run with Neon

Comic Pile is a PostgreSQL application, so local development can use the bundled local database while a hosted installation can use Neon. The maintained production deployment runs on Neon.

The Vercel entrypoint accepts standard `postgresql://`, `postgres://`, and
SQLAlchemy-style URLs and normalizes them for the Rust runtime. The standalone
native binary requires a plain `postgresql://` URL in
`RUST_ROLL_DATABASE_URL`. The migration runner accepts the supported driver
prefixes through `MIGRATE_DATABASE_URL` or `DATABASE_URL`. See
[the deployment guide](docs/DEPLOYMENT.md#self-hosting-with-neon) for the complete
Neon setup path.

## Stack

- **Frontend:** React, Vite, Tailwind CSS
- **API:** native Rust (axum) in a single Cargo workspace, deployed through `api/native_roll.rs`
- **Database:** PostgreSQL via `tokio-postgres`/`deadpool-postgres`
- **Migrations:** refinery runner (`native/migrate`), append-only SQL under `native/migrate/migrations/`
- **Production database:** Neon
- **Production hosting:** Vercel

## Common development commands

```bash
make dev        # Vite frontend + native Rust API together
make dev-frontend  # Vite only, on :5173
make dev-native    # native Rust Roll/auth service only, on :8010
make migrate    # run migrations (refinery runner, native/migrate)
make db-up      # start local PostgreSQL
make db-down    # stop local PostgreSQL without deleting data
make lint       # repository static checks + frontend ESLint
make verify-e2e # full Chromium suite only when explicitly requested (set BASE_URL)
make tidy       # sweep local generated artifacts
```

There is no Python application runtime. `app/`, `comic_pile/`, and the Alembic
migration tree were removed by the Rust cutover; Python dependencies remain
only for repository tooling and the hand-run QA mirror refresh script
(`scripts/ops/refresh_torque_qa_mirror.py`). Application database access is
asynchronous through the Rust connection pool.

## Production

Production deploys from `main` on Vercel. The frontend is static Vite output, every deployed `/api/*` route is served by the native Rust handler, and PostgreSQL is hosted by Neon. The production workflow runs database migrations against Neon before deploying the application.

Vercel Preview environments are intentionally unsupported. Fly.io and Railway are not current deployment targets.

## Repository map

- `api/`: the Vercel entrypoint, `native_roll.rs`
- `native/`: the Rust Cargo workspace — `roll-service` (API) and `migrate` (migration runner)
- `frontend/`: React/Vite frontend
- `static/`: built frontend assets served by Vercel
- `tests/`: Python tooling and repository-contract tests
- `tests_e2e/`: pointer to the maintained browser suite in `frontend/src/test/`
- `scripts/`: operational and development utilities
- `docs/`: code-coupled documentation and the authoritative documentation index

## Documentation

Start with [`docs/README.md`](docs/README.md). It identifies the authoritative repository documentation, what must remain versioned with code, and what belongs in the GitHub Wiki.

For architectural decisions and system overview, see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). For deployment and self-hosting with Neon, see [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md). For the authoritative per-route runtime and caller inventory, see [`docs/api/v2-route-inventory.json`](docs/api/v2-route-inventory.json).

Coding agents must also follow [`AGENTS.md`](AGENTS.md). Autonomous factory workers must follow [docs/AUTONOMOUS_FACTORY_POLICY.md](docs/AUTONOMOUS_FACTORY_POLICY.md) and [`docs/ISSUE_EXECUTION_PROTOCOL.md`](docs/ISSUE_EXECUTION_PROTOCOL.md).

What's New reads the database-backed release ledger. User-facing release notes are published after merge by the dedicated release writer. [`docs/changelog.md`](docs/changelog.md) and `docs/changelog.d/` are frozen historical migration sources retained only for provenance.

## Contributing

Comic Pile is actively developed in public. Bug reports, focused improvements, documentation fixes, and pull requests are welcome. Start with [`CONTRIBUTING.md`](CONTRIBUTING.md) and follow the project's [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).

## License

MIT. See [`LICENSE`](LICENSE).
