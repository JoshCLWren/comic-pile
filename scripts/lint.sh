#!/bin/bash
set -e

RED=$'\033[0;31m'
GREEN=$'\033[0;32m'
YELLOW=$'\033[1;33m'
NC=$'\033[0m' # No Color

echo "Running code quality checks..."

# Activate venv if not already active
if [ -z "$VIRTUAL_ENV" ]; then
    VENV_PATH=".venv/bin/activate"
    # Handle git worktrees: check if venv exists in main repo
    if [ ! -f "$VENV_PATH" ] && [ -f .git ]; then
        GIT_COMMON_DIR=$(git rev-parse --git-common-dir 2>/dev/null)
        if [ -n "$GIT_COMMON_DIR" ]; then
            MAIN_REPO_DIR=$(dirname "$GIT_COMMON_DIR")
            if [ -f "$MAIN_REPO_DIR/.venv/bin/activate" ]; then
                VENV_PATH="$MAIN_REPO_DIR/.venv/bin/activate"
                echo "Activating venv from main repo: $MAIN_REPO_DIR"
            fi
        fi
    fi

    if [ -f "$VENV_PATH" ]; then
        source "$VENV_PATH"
    else
        echo "No virtual environment found. Please run 'uv venv && uv sync --all-extras' first."
        exit 1
    fi
fi

# Compile check for all Python files
echo ""
echo "Checking Python syntax by compiling..."
python -m compileall . -q

# Run linting
echo ""
echo "Running ruff linting..."
if ! ruff check .; then
    echo ""
    echo "${RED}ERROR: Linting failed.${NC}"
    echo "${RED}Please fix the linting errors and check CONTRIBUTING.md for guidelines.${NC}"
    exit 1
fi

# Check for Any type usage
echo ""
echo "Checking for Any type usage..."
if [ -n "$(rg ': Any\b' . --type py 2>/dev/null | grep -v 'type: ignore' | head -1)" ]; then
    echo ""
    echo "${RED}ERROR: Any type found in codebase.${NC}"
    echo "${RED}Please replace Any with specific types and check CONTRIBUTING.md for guidelines.${NC}"
    exit 1
fi

# Run type checking
echo ""
echo "Running pyright type checking..."

# Handle git worktrees: if .venv doesn't exist locally, find the main repo
# This allows pyright to find the shared venv when working in worktrees
PYRIGHT_ARGS="."
if [ ! -d .venv ]; then
    # Check if we're in a git worktree (where .git is a file, not a directory)
    if [ -f .git ]; then
        # Find the main repository directory using git rev-parse
        GIT_COMMON_DIR=$(git rev-parse --git-common-dir 2>/dev/null)
        if [ -n "$GIT_COMMON_DIR" ]; then
            MAIN_REPO_DIR=$(dirname "$GIT_COMMON_DIR")
            if [ -d "$MAIN_REPO_DIR/.venv" ]; then
                echo "Detected git worktree, using main repo venv at $MAIN_REPO_DIR"
                PYRIGHT_ARGS="-v $MAIN_REPO_DIR ."
            fi
        fi
    fi
fi

if ! pyright $PYRIGHT_ARGS; then
    echo ""
    echo "${RED}ERROR: Type checking failed.${NC}"
    echo "${RED}Please fix the type errors and check CONTRIBUTING.md for guidelines.${NC}"
    exit 1
fi

# Handle node_modules in git worktrees
if [ ! -d "node_modules" ]; then
    if [ -f .git ]; then
        GIT_COMMON_DIR=$(git rev-parse --git-common-dir 2>/dev/null)
        if [ -n "$GIT_COMMON_DIR" ]; then
            MAIN_REPO_DIR=$(dirname "$GIT_COMMON_DIR")
            if [ -d "$MAIN_REPO_DIR/node_modules" ]; then
                echo "Detected git worktree, creating symlink to main repo node_modules"
                ln -sf "$MAIN_REPO_DIR/node_modules" node_modules
            fi
        fi
    fi
fi

# JavaScript linting
echo ""
echo "Running ESLint for JavaScript..."
if ! npm run lint:js; then
    echo ""
    echo "${RED}ERROR: JavaScript linting failed.${NC}"
    echo "${RED}Run 'npm run lint:fix' to auto-fix or fix manually.${NC}"
    exit 1
fi

# HTML linting
echo ""
echo "Running htmlhint for HTML templates..."
if ! npm run lint:html; then
    echo ""
    echo "${RED}ERROR: HTML linting failed.${NC}"
    echo "${RED}Fix HTML template issues manually.${NC}"
    exit 1
fi

echo ""
echo "${GREEN}All checks passed!${NC}"
