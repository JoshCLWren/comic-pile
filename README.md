# Python Starter Template

[![CI Status](https://github.com/JoshCLWren/python-starter-template/workflows/CI/badge.svg)](https://github.com/JoshCLWren/python-starter-template/actions)

A modern Python 3.13 project template with best practices, tooling, and CI/CD preconfigured.

## Features

- **Python 3.13** with type hints throughout
- **uv** for fast dependency management
- **pytest** with 96% minimum test coverage
- **ruff** for linting and formatting
- **pyright** for static type checking
- **Pre-commit hooks** to enforce code quality
- **GitHub Actions CI** for automated testing
- **Project initialization** via `make init`

## Quick Start

```bash
# Clone the repository
git clone https://github.com/JoshCLWren/python-starter-template.git
cd python-starter-template

# Initialize with your project name
make init NAME=my-awesome-project

# Install dependencies
uv sync --all-extras

# Activate the virtual environment (do this once per session)
source .venv/bin/activate

# Run tests
pytest

# Run your application
python main.py --name World --value 42
```

## Development Workflow

### First Time Setup

1. **Rename the project**:
   ```bash
   make init NAME=your-project-name
   ```

2. **Install dependencies**:
   ```bash
   uv sync --all-extras
   ```

3. **Activate the virtual environment**:
   ```bash
   source .venv/bin/activate
   ```

### Daily Development

Once the virtual environment is activated:

```bash
# Run the application
python main.py --name World --value 42

# Run tests
pytest

# Run tests with coverage report
pytest --cov-report=term-missing

# Run linting
make lint

# Format code with ruff
ruff format .
```

### Make Commands

- `make init NAME=your-project` - Initialize with new project name
- `make lint` - Run all linting checks (ruff + pyright)
- `make pytest` - Run the test suite
- `make venv` - Create virtual environment
- `make sync` - Install/update dependencies

## Project Structure

```
.
├── example_module/          # Main package (rename via make init)
│   ├── __init__.py
│   └── core.py             # Core business logic
├── tests/                   # Test suite
│   ├── conftest.py         # pytest fixtures
│   └── test_example.py     # Example tests
├── .github/
│   ├── actions/setup/       # CI setup action
│   └── workflows/ci.yml    # CI pipeline
├── scripts/
│   └── lint.sh            # Linting script
├── main.py                # Application entrypoint
├── pyproject.toml        # Project configuration
├── uv.lock               # Dependency lockfile
└── .gitignore           # Git ignore rules
```

## Testing

The template uses pytest with coverage reporting:

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest tests/test_example.py

# Run with coverage
pytest --cov=example_module --cov-report=html
```

**Coverage requirement**: Minimum 96% (configured in pyproject.toml)

## Code Quality

### Linting

The project uses ruff for fast Python linting:

```bash
# Run linter
ruff check .

# Fix auto-fixable issues
ruff check --fix .

# Format code
ruff format .
```

### Type Checking

Pyright provides static type checking:

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

## Configuration

### Python Version

Default is Python 3.13. To change:

1. Update `requires-python` in `pyproject.toml`
2. Update `target-version` in `pyproject.toml`
3. Update `.python-version` file
4. Recreate venv: `rm -rf .venv && uv venv`

### Coverage Threshold

Set in `pyproject.toml`:

```toml
[tool.pytest.ini_options]
addopts = ["--cov-fail-under=96"]
```

### Lint Rules

Configure in `pyproject.toml` under `[tool.ruff]`:

```toml
[tool.ruff]
line-length = 100
target-version = "py313"
```

## CI/CD

GitHub Actions runs on every push to main and on pull requests:

- **Lint job**: Runs ruff and pyright
- **Tests job**: Runs pytest with coverage

View pipeline status in the Actions tab of the repository.

## Dependency Management

The project uses uv for fast dependency management:

```bash
# Add a new dependency
uv add package-name

# Add dev dependency
uv add --dev package-name

# Remove dependency
uv remove package-name

# Update dependencies
uv sync
```

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature-name`
3. Make your changes
4. Run tests: `pytest`
5. Run linting: `make lint`
6. Commit with conventional commits
7. Push and create a pull request

## License

MIT License - see LICENSE file for details

## Credits

Template created by Josh Wren

## Related

- [uv Documentation](https://docs.astral.sh/uv/)
- [pytest Documentation](https://docs.pytest.org/)
- [ruff Documentation](https://docs.astral.sh/ruff/)
- [pyright Documentation](https://microsoft.github.io/pyright/)
