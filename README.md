# Comic Pile

A dice-driven comic reading tracker built with FastAPI, HTMX, and Tailwind CSS.

## Features

- **Dice-driven reading**: Roll for your next comic using a ladder system (d4 → d20)
- **Queue management**: Drag and drop to prioritize comics
- **Session tracking**: Automatically groups reading sessions with narrative summaries
- **Mobile-first**: Touch-friendly interface designed for tablets and phones
- **Local network access**: Use on any device in your home network

## Tech Stack

- **Backend**: FastAPI (Python 3.13)
- **Database**: PostgreSQL with SQLAlchemy ORM
- **Migrations**: Alembic
- **Frontend**: HTMX + Jinja2 templates
- **Styling**: Tailwind CSS
- **Testing**: pytest with httpx.AsyncClient for API tests
- **Code Quality**: ruff linting, pyright type checking, 96% coverage requirement

## Quick Start

```bash
# Clone the repository
git clone https://github.com/JoshCLWren/comic-pile.git
cd comic-pile

# Install dependencies
uv sync --all-extras

# Activate the virtual environment
source .venv/bin/activate

# Set up the database
make migrate

# Seed sample data (optional)
make seed

# Run the development server
make dev
```

Open http://localhost:8000 to view the app, or http://localhost:8000/docs for API documentation.

## Development Workflow

### Daily Development

```bash
# Run the development server
make dev

# Run tests
pytest
make pytest

# Run tests with coverage
pytest --cov=comic_pile --cov-report=term-missing

# Run linting
make lint

# Seed database with sample data
make seed

# Run database migrations
make migrate
```

### Make Commands

- `make dev` - Run FastAPI development server with hot reload
- `make seed` - Populate database with Faker sample data
- `make migrate` - Run Alembic migrations
- `make pytest` - Run test suite with coverage
- `make lint` - Run ruff and pyright
- `make worktrees` - List git worktrees
- `make status` - Show current task status

## Project Structure

```
.
├── app/                    # FastAPI application
│   ├── __init__.py
│   ├── main.py            # FastAPI app factory
│   ├── api/               # API route handlers
│   ├── models/            # SQLAlchemy database models
│   ├── schemas/           # Pydantic request/response schemas
│   └── templates/         # Jinja2 templates
├── comic_pile/            # Core package (dice ladder, queue, session logic)
├── migrations/            # Alembic migration files
├── scripts/               # Utility scripts (seed data, etc.)
├── static/                # Static assets (CSS, JS)
├── tests/                 # pytest test suite
├── pyproject.toml         # Project configuration
└── uv.lock                # Dependency lockfile
```

## Testing

The project uses pytest with coverage reporting:

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run with coverage
pytest --cov=comic_pile --cov-report=term-missing
```

**Coverage requirement**: Minimum 96% (configured in pyproject.toml)

## Code Quality

### Linting

```bash
# Run linter
ruff check .

# Fix auto-fixable issues
ruff check --fix .

# Format code
ruff format .
```

### Type Checking

```bash
# Run type checker
pyright .
```

### Pre-commit Hook

A pre-commit hook is installed automatically that runs:
- Python compilation check
- Ruff linting
- Any type usage check (disallows `Any` type)
- Pyright type checking

The hook will block commits with issues. To test manually:

```bash
make githook
```

## Mobile Access

The app is configured with CORS enabled for local network access. To use the app on other devices:

1. Find your machine's local IP address:
   - Linux/Mac: `ip addr show` or `ifconfig`
   - Windows: `ipconfig`

2. Access from any device on your local network:
   - App: http://YOUR_IP:8000 (e.g., http://192.168.1.5:8000)
   - API docs: http://YOUR_IP:8000/docs

3. If firewall blocks connections, allow port 8000:
   ```bash
   # Linux (ufw)
   sudo ufw allow 8000
   ```

## API Documentation

FastAPI automatically generates interactive API documentation:

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
- Full API Documentation: [docs/API.md](docs/API.md)

## Contributing

1. Fork the repository
2. Create a phase branch: `git checkout main && git checkout -b phase/2-database-models`
3. Make your changes
4. Run tests: `pytest`
5. Run linting: `make lint`
6. Commit with conventional commits
7. Push and create a pull request

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed guidelines.

## License

MIT License - see LICENSE file for details

## Credits

Created by Josh Wren
