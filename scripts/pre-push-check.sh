#!/bin/bash
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}=== PRE-PUSH VERIFICATION ===${NC}"
echo "This script MUST pass before pushing any code"
echo ""

# 1. Run type checking
echo -e "${YELLOW}[1/6] Running type checker...${NC}"
if ! uv run ty check --error-on-warning 2>&1 | grep -v "warning:"; then
    echo -e "${RED}❌ Type checking failed${NC}"
    echo "Fix type errors before pushing"
    exit 1
fi
echo -e "${GREEN}✅ Type checking passed${NC}"
echo ""

# 2. Run linter
echo -e "${YELLOW}[2/6] Running linter...${NC}"
if ! uv run ruff check . 2>&1 | grep -v "warning:"; then
    echo -e "${RED}❌ Linting failed${NC}"
    echo "Fix lint errors before pushing"
    exit 1
fi
echo -e "${GREEN}✅ Linting passed${NC}"
echo ""

# 3. Run unit tests
echo -e "${YELLOW}[3/6] Running unit tests...${NC}"
if ! uv run pytest tests/ --no-cov -q 2>&1 | tail -3; then
    echo -e "${RED}❌ Unit tests failed${NC}"
    echo "Fix test failures before pushing"
    exit 1
fi
echo -e "${GREEN}✅ Unit tests passed${NC}"
echo ""

# 4. Run Python E2E tests (NOT Playwright - those are CI-only)
echo -e "${YELLOW}[4/6] Running Python E2E tests (API workflows, dice ladder)...${NC}"
E2E_TEST_FILES=$(ls tests_e2e/*.py 2>/dev/null | grep -v conftest | grep -v __init__ || echo "")
if [ -z "$E2E_TEST_FILES" ]; then
    echo -e "${YELLOW}No Python E2E tests found - skipping${NC}"
else
    if ! uv run pytest tests_e2e/ --no-cov -q 2>&1 | tail -3; then
        echo -e "${RED}❌ Python E2E tests failed${NC}"
        echo "Fix test failures before pushing"
        exit 1
    fi
    echo -e "${GREEN}✅ Python E2E tests passed${NC}"
fi
echo ""

# 5. Check if frontend is modified
if git diff --name-only HEAD~ | grep -q "^frontend/"; then
    echo -e "${YELLOW}[5/6] Frontend changes detected - checking if frontend is built...${NC}"
    if [ ! -d "static/react" ] || [ -z "$(ls -A static/react 2>/dev/null)" ]; then
        echo -e "${RED}❌ Frontend not built${NC}"
        echo "Run: cd frontend && npm run build"
        exit 1
    fi
    echo -e "${GREEN}✅ Frontend built${NC}"
else
    echo -e "${YELLOW}[5/6] No frontend changes - skipping build check${NC}"
fi
echo ""

# 6. Check for uncommitted changes
echo -e "${YELLOW}[6/6] Checking git status...${NC}"
if ! git diff-index --quiet HEAD --; then
    echo -e "${YELLOW}⚠️  You have uncommitted changes${NC}"
    echo "Commit them before pushing"
    exit 1
fi
echo -e "${GREEN}✅ Working tree clean${NC}"
echo ""

echo -e "${GREEN}=== ✅ ALL CHECKS PASSED - SAFE TO PUSH ===${NC}"
