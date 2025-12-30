#!/bin/bash
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "Running code quality checks..."

# Activate venv if not already active
if [ -z "$VIRTUAL_ENV" ]; then
    if [ -f .venv/bin/activate ]; then
        source .venv/bin/activate
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
if ! pyright .; then
    echo ""
    echo "${RED}ERROR: Type checking failed.${NC}"
    echo "${RED}Please fix the type errors and check CONTRIBUTING.md for guidelines.${NC}"
    exit 1
fi

echo ""
echo "${GREEN}All checks passed!${NC}"
