# Contributing

Thanks for contributing to Comic Pile. This project values clear APIs, mobile-first UX, and approachable code. Please follow the checks below for any code change.

Participation in Comic Pile project spaces is also governed by the [Code of Conduct](CODE_OF_CONDUCT.md).

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

## Pre-commit hook

A pre-commit hook is installed in `.git/hooks/pre-commit` that automatically runs:
- Check for type/linter ignores in staged files
- Run the shared lint script (`scripts/lint.sh`)

The lint script runs:
- Python compilation check
- Full-repo ruff linting (`ruff check .`)
- Any type usage check (ruff ANN401 rule)
- Full-repo ty type checking (`ty check --error-on-warning`). Warnings fail this check, including `redundant-cast`. Do not recast a value after `isinstance` has already narrowed it.

Path-filtered ruff or ty is not a valid CI substitute. Use
`bash scripts/check-python-ci-lint.sh` or `make python-ci-lint` before every
Python push. Re-run after every later Python edit.

The hook will block commits containing `# type: ignore`, `# noqa`, `# ruff: ignore`, or `# pylint: ignore`.

To test the hook manually: `make githook` or `bash scripts/lint.sh`

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

1. Copy `.env.example` to `.env`.
2. Run `make setup` to install dependencies, start local PostgreSQL, run migrations, and seed demo data.
3. Run `make dev` and open the app at `http://localhost:5173`.
4. API docs are available at `http://localhost:8000/docs`.

Production migrations install dependencies with `uv sync --locked --no-dev`.
This keeps the `migrate` and `server` default groups but excludes development
tools. Keep `sqlalchemy[asyncio]` in the project dependencies: both the async
application and Alembic's model imports require greenlet. The Production
Runtime Migrations CI job tests this install separately from the dev image,
where Playwright can otherwise mask a missing greenlet dependency.

### API Development

- REST endpoints are defined in `app/api/`
- Request/response schemas in `app/schemas/` using Pydantic
- Database models in `app/models/` using SQLAlchemy
- Test endpoints with httpx.AsyncClient before building UI
- Use FastAPI's automatic OpenAPI docs at `/docs`

### Frontend Development

- Install deps:    `pnpm install`
- Dev server:      `make dev` (starts Vite and FastAPI together)
- Build:           `pnpm --filter frontend run build` (outputs to `static/react/`)
- Lint:            `pnpm --filter frontend run lint`
- Unit tests:      `pnpm --filter frontend test` (vitest, no server needed)
- E2E tests:       `pnpm --filter frontend run test:e2e` (requires backend server)

React components live in `frontend/src/` with JSX syntax. Style with Tailwind CSS (mobile-first, touch targets ≥44px).

### Database Migrations

```bash
# Create a new migration
alembic revision --autogenerate -m "description"

# Run migrations
make migrate  # or: alembic upgrade head
```

## Code quality standards

- Run linting after each change:
  - `make lint` or `bash scripts/lint.sh` (Python)
  - `pnpm --filter frontend run lint` (JavaScript/JSX)
- Use specific types instead of `Any` in type annotations (ruff ANN401 rule)
- Run tests when you touch logic or input handling:
  - `pytest` or `make pytest`
- Always write a regression test when fixing a bug.
- If you break something while fixing it, fix both in the same PR.
- Do not check in sample data or proprietary content.
- Do not use in-line comments to disable linting or type checks.
- Do not narrate your code with comments; prefer clear code and commit messages.

## Testing guidelines

- Automated tests live in `tests/` and run with `pytest` (or `make pytest`).
- Use httpx.AsyncClient for API integration tests
- Test both success and error paths for all API endpoints
- Test business logic (dice ladder, queue management, session detection) independently
- Maintain 94% coverage threshold

## Style guidelines

- Keep helpers explicit and descriptive (snake_case), and annotate public
  functions with precise types.
- Use Pydantic schemas for API validation
- Use SQLAlchemy models for database operations
- Follow PEP 8 spacing (4 spaces, 100-character soft wrap)

## Branch workflow

- Always create a phase branch from `main` before making changes:
  - `git checkout main && git checkout -b phase/2-database-models`
- Use descriptive branch names like `phase/2-database-models`
- When phase is complete, merge to main via the merge-phaseX make target

## Pull request guidelines

- Use imperative, component-scoped commit messages (e.g., "Add thread creation API endpoint")
- Bundle related changes per commit
- PR summary should describe user impact and testing performed
- Attach screenshots when UI is affected
- Ensure all tests pass and coverage is maintained
- Do not add or edit changelog Markdown as part of implementation delivery. User-facing release notes are published after merge by the dedicated release writer to the database-backed release ledger. Release-note publication or reconciliation delays do not block an otherwise-ready implementation PR.

### Merge gate (agent-authored PRs)

This is the only pre-merge process rule (#3561). Every agent-authored pull
request — Cursor cloud agents and factory workers — may merge only when both
are true for the **exact current head**:

1. One thorough code review by a Cursor cloud agent running a **different
   model** than the PR author. Same-model reviews do not count. A review
   recorded against a previous SHA does not count after the head moves.
2. CI is green on that head.

There are no extra pre-merge QA, preview, smoke, or migration-rehearsal
steps. Do not add a `factory:approved` label; controller provenance is the
authority.

The review controller writes those models as `github-actions[bot]` comments.
It records the author model from the factory roster when the producing worker
records the head, and the reviewer model when it launches and interprets an
independent factory review. Cursor cloud-agent ids (`bc-…`) in a PR footer
are a distinct identity token, not a substitute for the controller marker.

Only `github-actions[bot]` model markers count. OWNER/MEMBER/COLLABORATOR
comments — including Cursor agents posting as the repository owner — cannot
satisfy the gate. A missing author marker, or two author markers that disagree,
fails closed.

Markers (entire comment body, written only by the controller):

- Author:
  `<!-- comic-pile-agent-model-author-v1:pr-<n>:head-<sha>:model-<model>:agent-<author-id> -->`
- Reviewer:
  `<!-- comic-pile-agent-model-review-v1:pr-<n>:head-<sha>:author-<author-model>:reviewer-<reviewer-model>:author-agent-<author-id>:reviewer-agent-<reviewer-id>:verdict-approve -->`

The reviewer agent id must differ from the author agent id. Model comparison
uses the model family: a leading `cursor-` prefix and effort/speed suffixes
(`none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`, `thinking`,
`fast`) are stripped, so `cursor-grok-4.6-high-fast` and `cursor-grok-4.6-low`
are the same model.

The factory merge drain refuses the PR when those markers are missing, the
author record is missing or conflicting, the models match, the reviewer is
the authoring agent, the review SHA is stale, or required CI is red.
