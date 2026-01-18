#!/bin/bash
set -e

RED=$'\033[0;31m'
GREEN=$'\033[0;32m'
YELLOW=$'\033[1;33m'
NC=$'\033[0m' # No Color

MODE="--all"
if [ $# -ge 1 ]; then
    case "$1" in
        --all|--staged)
            MODE="$1"
            ;;
        *)
            echo "Usage: bash scripts/lint.sh [--all|--staged]"
            exit 2
            ;;
    esac
fi

echo "Running code quality checks..."

# Ensure we're running at repo root
if [ ! -f "pyproject.toml" ]; then
    echo "${RED}ERROR: Run from repository root.${NC}"
    exit 1
fi


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

STAGED_FILES=""
STAGED_PYTHON_FILES=""
STAGED_HTML_FILES=""
STAGED_STATIC_JS_FILES=""
STAGED_FRONTEND_FILES=""

if [ "$MODE" = "--staged" ]; then
    STAGED_FILES=$(git diff --name-only --cached --diff-filter=ACMRT || true)
    if [ -z "$STAGED_FILES" ]; then
        echo ""
        echo "No staged files found; skipping lint."
        exit 0
    fi

    STAGED_PYTHON_FILES=$(printf '%s\n' "$STAGED_FILES" | rg '\\.py$' || true)
    STAGED_HTML_FILES=$(printf '%s\n' "$STAGED_FILES" | rg '^app/templates/.*\\.html$' || true)
    STAGED_STATIC_JS_FILES=$(printf '%s\n' "$STAGED_FILES" | rg '^static/js/.*\\.js$' || true)
    STAGED_FRONTEND_FILES=$(printf '%s\n' "$STAGED_FILES" | rg '^frontend/' || true)
fi

should_run_python() {
    if [ "$MODE" = "--all" ]; then
        return 0
    fi

    [ -n "$STAGED_PYTHON_FILES" ] || printf '%s\n' "$STAGED_FILES" | rg -q '^pyproject\\.toml$|^uv\\.lock$'
}

should_run_static_js() {
    if [ "$MODE" = "--all" ]; then
        return 0
    fi

    [ -n "$STAGED_STATIC_JS_FILES" ]
}

should_run_frontend() {
    if [ "$MODE" = "--all" ]; then
        [ -d "frontend" ]
        return
    fi

    [ -n "$STAGED_FRONTEND_FILES" ]
}

should_run_html() {
    if [ "$MODE" = "--all" ]; then
        return 0
    fi

    [ -n "$STAGED_HTML_FILES" ]
}

ANY_CHECKED=0

if should_run_python; then
    ANY_CHECKED=1

    echo ""
    echo "Checking Python syntax by compiling..."
    if [ "$MODE" = "--staged" ] && [ -n "$STAGED_PYTHON_FILES" ]; then
        while IFS= read -r file; do
            python -m py_compile "$file"
        done <<<"$STAGED_PYTHON_FILES"
    else
        python -m compileall . -q
    fi

    echo ""
    echo "Running ruff linting..."
    if [ "$MODE" = "--staged" ] && [ -n "$STAGED_PYTHON_FILES" ]; then
        if ! xargs ruff check <<<"$STAGED_PYTHON_FILES"; then
            echo ""
            echo "${RED}ERROR: Linting failed.${NC}"
            echo "${RED}Please fix the linting errors and check CONTRIBUTING.md for guidelines.${NC}"
            exit 1
        fi
    else
        if ! ruff check .; then
            echo ""
            echo "${RED}ERROR: Linting failed.${NC}"
            echo "${RED}Please fix the linting errors and check CONTRIBUTING.md for guidelines.${NC}"
            exit 1
        fi
    fi

    echo ""
    echo "Checking for Any type usage..."
    if [ "$MODE" = "--staged" ] && [ -n "$STAGED_PYTHON_FILES" ]; then
        ANY_MATCH=""
        while IFS= read -r file; do
            if [ -n "$(rg ': Any\\b' "$file" 2>/dev/null | rg -v 'type: ignore' | head -1)" ]; then
                ANY_MATCH="$file"
                break
            fi
        done <<<"$STAGED_PYTHON_FILES"

        if [ -n "$ANY_MATCH" ]; then
            echo ""
            echo "${RED}ERROR: Any type found in codebase.${NC}"
            echo "${RED}Please replace Any with specific types and check CONTRIBUTING.md for guidelines.${NC}"
            exit 1
        fi
    else
        if [ -n "$(rg ': Any\\b' . --type py 2>/dev/null | rg -v 'type: ignore' | head -1)" ]; then
            echo ""
            echo "${RED}ERROR: Any type found in codebase.${NC}"
            echo "${RED}Please replace Any with specific types and check CONTRIBUTING.md for guidelines.${NC}"
            exit 1
        fi
    fi

    echo ""
    echo "Running ty type checking..."

    if ! command -v ty >/dev/null 2>&1; then
        echo "${RED}ERROR: ty is not installed in the active environment.${NC}"
        echo "${RED}Run: uv sync --all-extras${NC}"
        exit 1
    fi

    if [ "$MODE" = "--staged" ]; then
        if [ -n "$STAGED_PYTHON_FILES" ]; then
            while IFS= read -r file; do
                if ! ty check --error-on-warning "$file"; then
                    echo ""
                    echo "${RED}ERROR: Type checking failed.${NC}"
                    exit 1
                fi
            done <<<"$STAGED_PYTHON_FILES"
        else
            echo "No staged Python files to type-check."
        fi
    else
        if ! ty check --error-on-warning; then
            echo ""
            echo "${RED}ERROR: Type checking failed.${NC}"
            exit 1
        fi
    fi
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

if should_run_static_js; then
    ANY_CHECKED=1
    echo ""
    echo "Running ESLint for JavaScript..."

    if ! npm run lint:js; then
        echo ""
        echo "${RED}ERROR: JavaScript linting failed.${NC}"
        echo "${RED}Run 'npm run lint:fix' to auto-fix or fix manually.${NC}"
        exit 1
    fi
fi

if should_run_frontend; then
    ANY_CHECKED=1
    echo ""
    echo "Running frontend ESLint..."
    if ! (cd frontend && npm run lint); then
        echo ""
        echo "${RED}ERROR: Frontend JavaScript linting failed.${NC}"
        exit 1
    fi
fi

if should_run_html; then
    ANY_CHECKED=1
    echo ""
    echo "Running htmlhint for HTML templates..."
    if ! npm run lint:html; then
        echo ""
        echo "${RED}ERROR: HTML linting failed.${NC}"
        echo "${RED}Fix HTML template issues manually.${NC}"
        exit 1
    fi
fi

if [ "$ANY_CHECKED" -eq 0 ]; then
    echo ""
    echo "No relevant staged files; skipping lint."
    exit 0
fi

echo ""
echo "${GREEN}All checks passed!${NC}"
