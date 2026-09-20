# Deployment

ComicPile's maintained production deployment runs on Vercel from the `main` branch, with PostgreSQL hosted by Neon. The application remains self-hostable from source because its persistence layer is standard PostgreSQL.

## Production architecture

- Vercel serves the built React/Vite frontend as static output.
- FastAPI handles the intentional API routes and OpenAPI document.
- Neon provides PostgreSQL.
- The cache provider is Postgres by default (decision memo: `CACHE_PROVIDER_DECISION_2026-08.md`).
  Remote Redis caching stays disabled while its re-enable gate and command budget are pending
  measurement; `CACHE_ENABLED` cannot activate Redis without an explicit provider override.
- Pull requests are validated locally and in GitHub Actions. ComicPile does not provision or maintain Vercel Preview environments.

## Self-hosting with Neon

Neon is the database platform used by ComicPile production and is the closest hosted path to the maintained deployment. A self-hosted installation can also use another PostgreSQL server, but the steps below document the Neon path end to end.

### 1. Create or select a Neon project

You can create a project in the Neon Console or use the current Neon CLI:

```bash
npm i -g neon@latest
neon auth
neon projects create --name comic-pile
```

From a checked-out ComicPile repository, the Neon CLI can also link the workspace and pull the Postgres environment values:

```bash
neon link
neon env pull --service postgres
```

Alternatively, copy a Neon Postgres connection string from the Console and set it as `DATABASE_URL` yourself.

### 2. Configure ComicPile

At minimum, a production installation needs the database connection plus the ordinary production security settings:

```dotenv
DATABASE_URL=postgresql://USER:PASSWORD@HOST/DATABASE?sslmode=require
SECRET_KEY=<generate-a-long-random-value>
ENVIRONMENT=production
CORS_ORIGINS=https://your-comic-pile.example
```

ComicPile accepts `postgresql://`, `postgres://`, and `postgresql+asyncpg://` URLs. Application startup normalizes standard Postgres URLs to SQLAlchemy's `asyncpg` driver, while Alembic converts the same database URL to `psycopg` for synchronous migrations.

For the closest match to the maintained production setup, use Neon's pooled connection for application traffic and a direct Neon connection for schema migrations. The production migration tooling can resolve a direct URL through `NEON_PROJECT_ID` and `NEON_API_KEY`, or it can use an explicit `NEON_DIRECT_DATABASE_URL`; see [`.env.example`](../.env.example) for those variables.

### 3. Apply the schema

Run the committed Alembic migrations before serving the application:

```bash
make migrate
```

The migration must target the same Neon database that the deployed application will use. Do not rely on application startup to create or repair the production schema.

### 4. Deploy the application

The maintained hosting target is Vercel. Configure the production environment variables there, including `DATABASE_URL`, `SECRET_KEY`, `ENVIRONMENT=production`, and `CORS_ORIGINS`, then deploy from `main`.

After deployment, `GET /api/v1/health/dependencies` can be used to verify the application's database dependency independently from the lightweight liveness endpoint.

### How ComicPile uses Neon

Neon is not only an incidental development database in this project:

- Production application data is stored in Neon PostgreSQL.
- The production delivery workflow runs database migrations before deploying the application.
- Runtime database access uses SQLAlchemy with `asyncpg`, with pooled connections supported for application traffic.
- Migration tooling supports direct Neon connections and the Neon API integration described in `.env.example`.
- Operational health checks report database dependency health separately from process liveness.
- The repository includes Neon-specific operational and performance documentation, including production-to-local data workflows and connection-pool measurements.

The core application remains portable PostgreSQL software. Neon is the maintained managed-Postgres integration and the production reference implementation.

## Production delivery

Merges to `main` are the production source. The production workflow runs the required database migration against Neon before deploying the application to Vercel.

Do not add Fly.io, Railway, or another maintained hosting target without a new product decision and an explicit migration plan. Historical references in the changelog describe past deployments and are not active operating instructions.

## Local development

Use `make setup` for the local environment, `make dev` for the frontend and API development servers, and `make verify` for the complete local verification suite. Local development and GitHub Actions remain independent from production deployment configuration.
