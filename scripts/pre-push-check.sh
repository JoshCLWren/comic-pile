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
echo -e "${YELLOW}[1/4] Running type checker...${NC}"
if ! uv run ty check --error-on-warning; then
    echo -e "${RED}❌ Type checking failed${NC}"
    echo "Fix type errors before pushing"
    exit 1
fi
echo -e "${GREEN}✅ Type checking passed${NC}"
echo ""

# 2. Run linter
echo -e "${YELLOW}[2/4] Running linter...${NC}"
if ! uv run ruff check .; then
    echo -e "${RED}❌ Linting failed${NC}"
    echo "Fix lint errors before pushing"
    exit 1
fi
echo -e "${GREEN}✅ Linting passed${NC}"
echo ""

# 3. Run tests
echo -e "${YELLOW}[3/4] Running tests...${NC}"
if ! uv run pytest tests/ --no-cov -q; then
    echo -e "${RED}❌ Tests failed${NC}"
    echo "Fix test failures before pushing"
    exit 1
fi
echo -e "${GREEN}✅ All tests passed${NC}"
echo ""

# 4. Check for uncommitted changes
echo -e "${YELLOW}[4/4] Checking git status...${NC}"
if ! git diff-index --quiet HEAD --; then
    echo -e "${YELLOW}⚠️  You have uncommitted changes${NC}"
    echo "Commit them before pushing"
    exit 1
fi
echo -e "${GREEN}✅ Working tree clean${NC}"
echo ""

echo -e "${GREEN}=== ✅ ALL CHECKS PASSED - SAFE TO PUSH ===${NC}"
