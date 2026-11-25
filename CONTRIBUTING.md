# Contributing

Thanks for contributing to Comic Pile. This project values clear APIs, mobile-first UX, and approachable code. Please follow the checks below for any code change.

Participation in Comic Pile project spaces is also governed by the [Code of Conduct](CODE_OF_CONDUCT.md).

## Good first issues

Looking for a small, well-scoped starter task? Browse open issues labeled
[`good first issue`](https://github.com/JoshCLWren/comic-pile/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22).
These issues are sized for a first contribution and follow the same review, CI, and
merge flow described below.

## Pull requests and the factory

Open a ready-for-review PR from your fork or repository branch. Contributor,
local, and factory PRs all enter the same automated review, repair, CI, and merge
flow. You do not need to request factory enrollment or provide credentials.
Your commits and contributor credit remain intact. Enable **Allow edits from
maintainers** so the factory can push fixes to your PR branch.

Factory labels show the current next action: review, changes requested, CI, or
ready. Every new push requires review and checks for the new commit. Enrollment
alone never approves or authorizes merging your code. Fork CI runs without
repository secrets or permission to publish container images.

Do not create new GitHub issues or sub-issues for defects found during a PR
without explicit owner authorization. Record out-of-scope discoveries in the
existing issue or PR handoff.

## Pre-commit hook

The repository provides pre-commit and pre-push hooks. Install them once per
checkout with `bash scripts/install-git-hooks.sh` (see
[`docs/GIT_HOOKS.md`](docs/GIT_HOOKS.md)). The pre-commit hook automatically runs:
- Check for type/linter ignores in staged files
- Run the shared lint script (`scripts/lint.sh`)

The lint script runs:
- Python compilation and prohibited-ignore/`Any` checks
- JavaScript and frontend ESLint
- HTML lint when legacy HTML templates are present

It does **not** run Ruff or ty. CI runs the required full-repo pair:

```bash
ruff check .
ty check --error-on-warning
```

Path-filtered Ruff or ty is not a valid CI substitute. Run both after your last
Python edit and re-run after later edits. Warnings from ty fail the check,
including `redundant-cast`; do not recast a value after `isinstance` has already
narrowed it.

The hook will block commits containing `# type: ignore`, `# noqa`, `# ruff: ignore`, or `# pylint: ignore`.

To test the shared lint checks manually: `make githook` or `bash scripts/lint.sh`.
Run `ruff check .` and `ty check --error-on-warning` separately for Python changes.

## 🚫 CORE PRINCIPLE: NEVER SKIP TESTS

**⚠️ THIS IS THE MOST IMPORTANT RULE IN THIS PROJECT.**

**TESTS MUST NEVER BE SKIPPED - EVER.**

When a test fails:
1. ✅ Fix the test
2. ✅ Fix the code that breaks the test
3. ✅ Investigate root cause
4. ❌ **NEVER skip the test**

**This applies to:**
- All automated tests (unit, integration, E2E)
- All contributors (human and AI)
- All situations (no exceptions)

**Consequences of skipping tests:**
- Broken code gets merged
- Technical debt accumulates
- Confidence in the test suite is lost
- Other developers waste time debugging

**If you're tempted to use `--no-verify`, skip a test, or disable a check, DON'T.**

Fix the problem instead.

## Development workflow

### Getting Started

1. Copy `.env.example` to `.env` and replace `SECRET_KEY` with a long random value.
2. Export the environment for the migration runner and native service (neither loads `.env`):

   ```bash
   set -a; . ./.env; set +a
   export RUST_ROLL_DATABASE_URL=postgresql://comicpile:comicpile_password@localhost:5435/comicpile
   export RUST_ROLL_JWT_SECRET="$SECRET_KEY"
   ```

3. Run `make setup` to install frontend dependencies, start local PostgreSQL, and apply migrations.
4. For Python tooling tests or git hooks, create the tooling environment with `uv venv && uv sync --all-extras`. This is not required to run the application.
5. Run `make dev` and open the app at `http://localhost:5173`. The native Rust API serves `http://localhost:8010`.
6. There is no seed command: register an account in the running app to create your first queue.

Production deploys run the same Rust migration runner (`native/migrate`) against
Neon before the Vercel deployment. It reads `MIGRATE_DATABASE_URL`, falling back
to `DATABASE_URL`, and accepts SQLAlchemy `+asyncpg`/`+psycopg` URL suffixes. The
Production Runtime Migrations CI job tests that runner; there is no Python
application runtime to install.

### API Development

- HTTP handlers live in `native/roll-service/src/`, registered in
  `native/roll-service/src/lib.rs` and reached through the Vercel entrypoint
  `api/native_roll.rs`.
- Request/response types are Rust `serde`/`utoipa` DTOs. Generated native contracts
  are checked in under `native/contracts/`; the merged client contract is
  `frontend/src/generated/openapi.json`.
- Database access uses `deadpool-postgres`/`tokio-postgres`; shared pool and SQL
  helpers live in `native/roll-service/src/db.rs`.
- Add new client resources under `/api/v2/*`. Route ingress is bot-owned
  (`docs/api/route-fragments/*.json`); never hand-edit `vercel.json`.
- Verify the contract with `pnpm --filter frontend run check:api-types` and
  `node scripts/export_openapi_schema.mjs --check`, then run the Rust tests for
  the route module you changed.

### Route fragments and generated routing files

Contributors edit only `docs/api/route-fragments/*.json` source fragments
(excluding `docs/api/route-fragments/vercel-rewrites.json`). Never hand-edit
`vercel.json`, `docs/api/v2-route-inventory.json`, the `AGENTS.md`
`<!-- route-burndown -->` section, or `docs/api/route-fragments/vercel-rewrites.json` in a PR.
Those files are bot-owned and are regenerated post-merge by
`.github/workflows/regenerate-routes.yml` runs
`node scripts/generate_route_burndown.mjs`, then
`node scripts/generate_vercel_routes.mjs`, then the burndown generator again so
its enrichment is preserved. Both `--check` gates must pass. The
`route-fragment-guard` workflow fails PRs that include generated files. `vercel.json` stays on
`main` for Vercel deploy (do not gitignore it); the previous `main` copy
remains valid until the bot lands.

### Frontend Development

- Install deps:    `pnpm install --frozen-lockfile`
- Dev server:      `make dev` (starts Vite on :5173 and the native Rust API on :8010)
- Build:           `pnpm --filter frontend run build` (outputs to `static/react/`)
- Lint:            `pnpm --filter frontend run lint`
- Unit tests:      `pnpm --filter frontend exec vitest run <file>` (focused, no server needed)
- E2E tests:       from `frontend/`, run `pnpm run build`, then `BASE_URL=http://localhost:5173 pnpm exec playwright test <spec> --project=chromium` while `make dev` is running; after `make docker-test-up`, use `BASE_URL=http://localhost:8000` with the same focused Playwright command

React components live in `frontend/src/` as TypeScript/TSX. Style with Tailwind CSS (mobile-first, touch targets ≥44px).

### Database Migrations

```bash
# Create a new migration: append native/migrate/migrations/V<n>__description.sql
# (append-only; never edit an applied migration)

# Run migrations (refinery runner, comicpile-migrate)
make migrate  # or: cargo run --locked -p comicpile-migrate -- up
```

## Code quality standards

- Run linting after each change:
  - `ruff check .` and `ty check --error-on-warning` for Python tooling
  - `bash scripts/lint.sh` for the other repository static checks
  - `pnpm --filter frontend run lint && pnpm --filter frontend run typecheck` (TypeScript)
- Use specific types instead of `Any` in type annotations (ruff ANN401 rule)
- Run focused tests when you touch logic or input handling:
  - `cargo test -p comicpile-roll-service <filter>` (Rust API)
  - `pnpm --filter frontend exec vitest run <file>` (frontend)
  - `uv run python -m pytest tests/test_<name>.py` (repository tooling)
- Always write a regression test when fixing a bug.
- If you break something while fixing it, fix both in the same PR.
- Do not check in sample data or proprietary content.
- Do not use in-line comments to disable linting or type checks.
- Do not narrate your code with comments; prefer clear code and commit messages.

## Testing guidelines

- Rust API behavior lives in `native/roll-service`; run `cargo test -p comicpile-roll-service <filter>` for one module or case. Full workspace suites run in CI unless explicitly requested.
- Frontend unit tests use Vitest (`pnpm --filter frontend exec vitest run <file>`); browser coverage uses Playwright specs in `frontend/src/test/`.
- Repository tooling tests live in `tests/` and run with focused `uv run python -m pytest tests/test_<name>.py`.
- Test both success and error paths, including ownership and auth failures.
- Frontend coverage thresholds are enforced in CI through `frontend/vitest.config.ts`; Python coverage thresholds are retired.

## Style guidelines

- Keep helpers explicit and descriptive (snake_case), and annotate public
  Python tooling functions with precise types.
- API validation and DTOs are Rust `serde`/`utoipa` types; database access is
  asynchronous Rust through `deadpool-postgres`/`tokio-postgres`.
- Follow PEP 8 spacing (4 spaces, 100-character soft wrap) for Python tooling.

## Branch workflow

- Branch from `main` with a descriptive name (`git checkout -b fix/queue-reorder`).
- Open a ready-for-review PR against `main`; do not open draft PRs unless asked.
- The `make create-phaseX` / `make merge-phaseX` targets are historical leftovers
  from the original nine-phase build and are not part of the current flow.

## Pull request guidelines

- Use imperative, component-scoped commit messages (e.g., "Add thread creation API endpoint")
- Bundle related changes per commit
- PR summary should describe user impact and testing performed
- Attach screenshots when UI is affected
- Ensure all tests pass and coverage is maintained
- Do not add or edit changelog Markdown as part of implementation delivery. User-facing release notes are published after merge by the dedicated release writer to the database-backed release ledger. Release-note publication or reconciliation delays do not block an otherwise-ready implementation PR.

### Merge gate (agent-authored PRs)

Agent-authored PRs follow [the autonomous factory policy](docs/AUTONOMOUS_FACTORY_POLICY.md)
and [the issue execution protocol](docs/ISSUE_EXECUTION_PROTOCOL.md). For the
exact current head, the PR must be open, non-draft, conflict-free and mergeable;
every required CI check must pass; every actionable review finding must be fixed,
demonstrably outdated, or concretely rebutted; and independent exact-head
semantic/acceptance review must confirm that the declared scope is complete and
safe to integrate.

Reviewer independence and provenance are determined by the current factory
controller, not by a hand-maintained model-name comparison in this document.
Do not fabricate approval markers or formal self-approval. `factory:approved` is
visibility only; trusted exact-head review is recorded by the factory controller,
and labels never replace review or CI evidence. Never enable auto-merge or merge
a moved or unverified head.
