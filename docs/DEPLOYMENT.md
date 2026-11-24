# Deployment

ComicPile's maintained production deployment runs on Vercel from the `main` branch, with PostgreSQL hosted by Neon. The application remains self-hostable from source because its persistence layer is standard PostgreSQL.

## Production architecture

- Vercel serves the built React/Vite frontend as static output.
- A single native Rust function (`api/native_roll.rs`) serves every deployed
  `/api/*` route; unknown API paths get a Rust JSON 404.
- The OpenAPI contract is generated and checked in
  (`native/contracts/v2-runtime.openapi.json`, merged into
  `frontend/src/generated/openapi.json`). There is no runtime `/docs`,
  `/redoc` or `/openapi.json` endpoint.
- Neon provides PostgreSQL.

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
RUST_ROLL_ENV=production
ENVIRONMENT=production
```

The Vercel entrypoint accepts `DATABASE_URL` and `SECRET_KEY`, defaults to the
production environment, and normalizes supported SQLAlchemy URL prefixes for
`tokio-postgres`. `RUST_ROLL_ENV` controls native runtime validation;
`ENVIRONMENT=production` is also used by the password-reset mailer to select the
default production link origin. A standalone native process instead requires
`RUST_ROLL_DATABASE_URL` and `RUST_ROLL_JWT_SECRET`; it does not normalize driver
prefixes. The Rust migration runner accepts `MIGRATE_DATABASE_URL` or
`DATABASE_URL` and strips `+asyncpg`/`+psycopg` suffixes. Production database
connections require `sslmode=require`.

`CORS_ORIGINS` and `SESSION_GAP_HOURS` remain in `.env.example` for historical
compatibility but are not read by the current native configuration. Export the
selected values in the shell before running the migration runner or a standalone
native process; Vercel reads them from the project environment.

For the closest match to the maintained production setup, use Neon's pooled connection for application traffic and a direct Neon connection for schema migrations. The production migration tooling can resolve a direct URL through `NEON_PROJECT_ID` and `NEON_API_KEY`, or it can use an explicit `NEON_DIRECT_DATABASE_URL`; see [`.env.example`](../.env.example) for those variables.

### 3. Apply the schema

Run the committed migrations (refinery runner, `native/migrate`) before serving the application:

```bash
make migrate
```

The migration must target the same Neon database that the deployed application will use. Do not rely on application startup to create or repair the production schema.

### 4. Deploy the application

The maintained hosting target is Vercel. Configure the production environment variables there, including `DATABASE_URL`, `SECRET_KEY`, `RUST_ROLL_ENV=production`, and `ENVIRONMENT=production` for password-reset links, then deploy from `main`.

After deployment, `GET /api/v2/health` verifies process liveness without opening a database connection and returns the `X-ComicPile-API-Runtime: rust` header. Confirm database readiness with a real data request or with the migration planner:

```bash
MIGRATE_DATABASE_URL="postgresql://..." cargo run --locked -p comicpile-migrate -- plan
```

### Password-reset outbound email (Gmail SMTP)

Password-reset links are delivered through Gmail SMTP behind the existing
provider-neutral mailer boundary. The maintained production deployment needs
two email-specific values:

```dotenv
GMAIL_SMTP_USERNAME=owner@gmail.com
GMAIL_SMTP_APP_PASSWORD=<google-app-password>
```

`GMAIL_SMTP_APP_PASSWORD` must be a Google App Password, not the Google
account's ordinary password. The Google account must have 2-Step Verification
enabled before an App Password can be created. Store the App Password only in
the deployment secret store and never copy it into GitHub, logs, source, or
issue comments.

When `ENVIRONMENT=production`, ComicPile defaults to:

```text
sender: Comic Pile <GMAIL_SMTP_USERNAME>
origin: https://comic-pile.vercel.app
path: /reset-password
```

`PASSWORD_RESET_SENDER` remains an optional override for a sender or alias the
authenticated Gmail account is already permitted to send as.
`PASSWORD_RESET_ORIGIN` and `PASSWORD_RESET_PATH` remain optional overrides
for self-hosting and tests.

Notes:

- Gmail delivery uses `smtp.gmail.com` over implicit TLS on port 465.
- Delivery remains a request background task after the enumeration-safe
  acknowledgement is returned, so SMTP latency or an outage cannot reveal
  whether an email address belongs to an account.
- Authentication and SMTP failures are translated to a provider-neutral
  `PasswordResetDeliveryError`; passwords, recipients, and raw reset tokens
  are never written to application logs.
- The reset token is appended as an encoded `?token=` query parameter only at
  the delivery boundary.
- If either Gmail credential is missing or a placeholder, ComicPile uses the
  deterministic fake mailer and logs `password_reset_email_unconfigured`
  rather than attempting a partially configured send.

### How ComicPile uses Neon

Neon is not only an incidental development database in this project:

- Production application data is stored in Neon PostgreSQL.
- The production delivery workflow runs database migrations before deploying the application.
- Runtime database access uses the Rust `deadpool-postgres` pool over `tokio-postgres`.
- Migration tooling supports direct Neon connections and the Neon API integration described in `.env.example`.
- Process liveness is checked independently at `/api/v2/health`; database readiness is verified with a real data request or the migration planner.
- The repository includes Neon-specific operational and performance documentation, including production-to-local data workflows and connection-pool measurements.

The core application remains portable PostgreSQL software. Neon is the maintained managed-Postgres integration and the production reference implementation.

## Production delivery

Merges to `main` are the production source. The production workflow runs the required database migration against Neon before deploying the application to Vercel.

Factory merges made with the built-in `GITHUB_TOKEN` fire no push event, so the existing factory ready-merge drains dispatch Deploy Production after the last merge. Factory workers may merge only after every exact-head gate in the autonomous policy is satisfied. A queued manual redeploy can be superseded by a later pending run (GitHub keeps only the newest pending run), so see the note in [Overlapping runs](VERCEL_DEPLOYMENT.md#overlapping-runs). See [Bot merges dispatch the deploy](VERCEL_DEPLOYMENT.md#bot-merges-dispatch-the-deploy).

Do not add Fly.io, Railway, or another maintained hosting target without a new product decision and an explicit migration plan. Historical references in the changelog describe past deployments and are not active operating instructions.

## Local development

Use `make setup` for the local environment and `make dev` for the Vite frontend (`:5173`) and native Rust API (`:8010`). Run `make lint`, the full-repo Ruff/ty pair for Python tooling, and focused Rust/frontend tests. For browser changes, build and run one focused Chromium spec: `cd frontend && pnpm run build && BASE_URL=http://localhost:5173 pnpm exec playwright test <spec> --project=chromium`. Full suites run in CI unless explicitly requested. Local development and GitHub Actions remain independent from production deployment configuration.


### Automatic deployment repair

`Production Deploy Recovery` runs after Deploy Production and every 15 minutes.
A real attempted release failure opens or refreshes one GitHub repair issue,
including the failed run and step. Updates preserve active factory leases.
The issue enters the ordinary factory queue as a critical `deploy-fix`; fixes
retain normal exact-head CI and independent review requirements. There is no
red-deploy freeze or override path.
Preflight publishes a run-attempt-specific `deployment-attempt-N` artifact with the
selected checkout SHA before dependency setup. Recovery incidents use that evidence;
historical or expired metadata is explicitly unavailable, never guessed from the
workflow trigger SHA. Missing exact-attempt evidence cannot reconcile a failed CLI
deploy against the live alias.
Only a successful actual deployment with both production probes passing closes
the managed repair issue; live worker leases are left for that worker to finish.

The health probe reports the executable name read from the OS, OS/architecture,
and the package, compiler version and source revision captured during the build.
Deploy Production supplies the exact SHA to the build and checks that revision
in the live response. The compatibility `rust` label alone is not deployment
proof. These fields provide operational evidence, not cryptographic attestation.
