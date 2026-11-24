# Contributing

Thanks for contributing to Comic Pile. This project values clear APIs,
mobile-first UX and approachable code. Follow the checks below for any change.

Participation is also governed by the [Code of Conduct](CODE_OF_CONDUCT.md).

## Pull requests and the factory

Open a ready-for-review PR from your fork or repository branch. Contributor,
local and factory PRs enter the same review, repair, CI and merge flow. Factory
enrollment never approves or authorizes merging by itself. Fork CI runs without
repository secrets or permission to publish container images.

See [`AGENTS.md`](AGENTS.md), [`docs/ISSUE_EXECUTION_PROTOCOL.md`](docs/ISSUE_EXECUTION_PROTOCOL.md)
and [`docs/AUTONOMOUS_FACTORY_POLICY.md`](docs/AUTONOMOUS_FACTORY_POLICY.md) for
ownership, review and delivery rules. The Rust-cutover backlog freeze prohibits
new issues, sub-issues and work splits without explicit interactive owner
authorization.

## Development prerequisites

- Docker for local PostgreSQL.
- Rust/Cargo for the native service and migration runner.
- Node.js and pnpm for the frontend.
- Python 3.14 and uv for repository tooling/checks. The application itself has no
  Python runtime.

Install the Python tooling environment before using the shared lint script:

```bash
make sync                 # uv sync --all-extras
# or: uv venv && uv sync --all-extras
```

`make setup` installs frontend dependencies, starts PostgreSQL and applies
migrations; it does not install the Python tooling environment.

## Pre-commit and lint gates

Install hooks with `bash scripts/install-git-hooks.sh`. The pre-commit hook runs
`bash scripts/lint.sh`, which currently checks Python syntax, prohibited
ignore/`Any` patterns and frontend ESLint. It does **not** run Ruff or ty.

Before every Python push, run the exact whole-repository CI pair directly:

```bash
ruff check .
ty check --error-on-warning
```

Path-filtered Ruff or ty is not a valid substitute. Re-run after every Python
edit. Never use `--no-verify`, add ignore comments, skip tests or weaken a check
to force green.

For frontend changes, run the focused lint/typecheck/build and targeted tests
described in `AGENTS.md`. Full suites and aggregate coverage run in CI.

## Getting started

1. Copy `.env.example` to `.env` and replace `SECRET_KEY` with a long random
   value.
2. Export the environment for the migration runner and standalone native
   service; neither loads `.env` automatically:

   ```bash
   set -a; . ./.env; set +a
   export RUST_ROLL_DATABASE_URL=postgresql://comicpile:comicpile_password@localhost:5435/comicpile
   export RUST_ROLL_JWT_SECRET="$SECRET_KEY"
   ```

3. Run `make setup` to install frontend dependencies, start PostgreSQL and apply
   migrations.
4. Run `make dev`; open Vite at `http://localhost:5173`. The native API is on
   `http://127.0.0.1:8010`.
5. Register an account in the app. There is no seed command.

See [`LOCAL_TESTING.md`](LOCAL_TESTING.md) for the exact test topology and
[`README.md`](README.md) for self-hosting.

## API development

- Handlers live under `native/roll-service/src/` and are registered in
  `native/roll-service/src/lib.rs`; Vercel enters through
  `api/native_roll.rs`.
- Request/response types are Rust `serde`/`utoipa` DTOs. Generated contracts live
  under `native/contracts/`; do not edit generated JSON or TypeScript directly.
- Database access uses `deadpool-postgres` / `tokio-postgres`; shared helpers are
  in `native/roll-service/src/db.rs`.
- Add new client resources under `/api/v2/*`. API version is not implementation
  language. Preserve retained same-path v1/unversioned contracts unless a
  separate API change is explicitly approved.
- Route ingress is bot-owned. Edit only source fragments under
  `docs/api/route-fragments/`; never hand-edit `vercel.json`, the generated
  inventory or the `AGENTS.md` route-burndown block.
- Run the focused Rust route tests and
  `pnpm --filter frontend run check:api-types` after contract changes.

## Frontend development

- Install dependencies with `pnpm install --frozen-lockfile`.
- `make dev` runs Vite on `:5173` and the native API on `:8010`.
- Build with `pnpm --filter frontend run build` (output `static/react/`).
- Run lint/typecheck and targeted Vitest files; use Playwright for browser
  behavior.
- Follow `frontend/AGENTS.md` and
  [`docs/FRONTEND_VISUAL_GRAMMAR.md`](docs/FRONTEND_VISUAL_GRAMMAR.md) for visual
  work.

## Database migrations

Append-only SQL lives under `native/migrate/migrations/`. Never edit an applied
migration.

```bash
make migrate
# or: cargo run --locked -p comicpile-migrate -- up
```

The runner reads `MIGRATE_DATABASE_URL`, falling back to `DATABASE_URL`, and
accepts historical SQLAlchemy driver suffixes. There is no downgrade path; use a
new forward migration or a verified pre-migration backup. See
[`docs/DATABASE_SAVE_LOAD.md`](docs/DATABASE_SAVE_LOAD.md).

## Code quality and tests

- Run `cargo check --workspace` and targeted Rust tests for backend changes.
- Run targeted frontend Vitest/Playwright tests for changed behavior. Full Rust,
  frontend and coverage suites run in CI.
- Repository tooling tests live under `tests/`; run the affected files with
  pytest after installing the Python environment.
- Test success, validation, auth, ownership and failure paths. Add a regression
  test for every fixed defect.
- Never skip, disable or weaken a meaningful test.

## Python tooling style

- Standard-library, third-party, then local imports.
- Precise public-function annotations; never `Any`.
- Use `|` unions and avoid redundant `cast()` calls.
- Use `snake_case`, `PascalCase`, `SCREAMING_SNAKE_CASE` and `_private` names.
- Google-style docstrings, 4-space indentation, 100-character soft wrap and
  trailing commas in multi-line structures.
- Do not add `# type: ignore`, `# noqa`, `# ruff: ignore` or `# pylint: ignore`.

Do not recreate Pydantic/SQLAlchemy application modules. Python is tooling only;
the QA mirror script's isolated SQLAlchemy use is not a deployed runtime.

## Branch and PR workflow

- Branch from `main` with a descriptive name, e.g. `fix/queue-reorder`.
- Open ready-for-review PRs; use draft only when explicitly requested.
- The old `make create-phaseX` / `make merge-phaseX` targets are historical and
  not part of the current flow.
- Do not add or repair changelog Markdown. Release notes are published after
  merge by the dedicated release writer.

## Merge gate for agent-authored PRs

The exact current head must be green on required CI, mergeable, free of
unresolved actionable review findings and complete for its declared scope.

Current Rotisserie owner policy (2026-11-22) requires **one independent recorded
review**:

- A reviewer model known from trusted factory records to have authored any part
  of the PR cannot approve it.
- A reviewer's executed model must be recorded so self-review can be excluded.
- When no factory author model is recorded (human, external or unattributed PR),
  any recorded reviewer may approve. Missing provenance does not create a
  two-review requirement.
- A worker that switched to a model that authored none of the PR may review;
  provider/route aliases are normalized by the controller.

The trusted controller writes exact-head contributor/review markers and applies
this policy. Do not fabricate approvals or use a label as merge authority. See
[`docs/AUTONOMOUS_FACTORY_POLICY.md`](docs/AUTONOMOUS_FACTORY_POLICY.md) and
[`docs/FACTORY_GITHUB_VISIBILITY.md`](docs/FACTORY_GITHUB_VISIBILITY.md) for the
canonical lifecycle and marker contract.
