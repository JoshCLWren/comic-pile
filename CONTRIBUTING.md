# Contributing

Thanks for contributing to Comic Pile. This project values clear APIs, mobile-first UX, and approachable code. Please follow the checks below for any code change.

## Pre-commit hook

A pre-commit hook is installed in `.git/hooks/pre-commit` that automatically runs:
- Check for type/linter ignores in staged files
- Run the shared lint script (`scripts/lint.sh`)

The lint script runs:
- Python compilation check
- Ruff linting
- Any type usage check (ruff ANN401 rule)
- Pyright type checking

The hook will block commits containing `# type: ignore`, `# noqa`, `# ruff: ignore`, or `# pylint: ignore`.

To test the hook manually: `make githook` or `bash scripts/lint.sh`

## Development workflow

### Getting Started

1. Install dependencies:
   ```bash
   uv sync --all-extras
   source .venv/bin/activate
   ```

2. Set up the database:
   ```bash
   make migrate
   ```

3. Seed sample data (optional):
   ```bash
   make seed
   ```

4. Run the development server:
   ```bash
   make dev
   ```

5. View the app:
   - App: http://localhost:8000
   - API docs: http://localhost:8000/docs

### API Development

- REST endpoints are defined in `app/api/`
- Request/response schemas in `app/schemas/` using Pydantic
- Database models in `app/models/` using SQLAlchemy
- Test endpoints with httpx.AsyncClient before building UI
- Use FastAPI's automatic OpenAPI docs at `/docs`

### Frontend Development

- Templates live in `app/templates/` with Jinja2 syntax
- Use HTMX for interactivity (AJAX without JavaScript)
- Style with Tailwind CSS (mobile-first, touch targets ≥44px)
- Keep custom JavaScript to a minimum

### Database Migrations

```bash
# Create a new migration
alembic revision --autogenerate -m "description"

# Run migrations
make migrate  # or: alembic upgrade head
```

## Code quality standards

- Run linting after each change:
  - `make lint` or `bash scripts/lint.sh`
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
- Maintain 96% coverage threshold

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
