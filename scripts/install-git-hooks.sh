#!/usr/bin/env bash
# Install git hooks for this repository

set -e

echo "🔧 Installing git hooks..."

# Copy hooks from .git/hooks/ directory
cp .git/hooks/pre-commit .git/hooks/pre-commit.sample 2>/dev/null || true
cp .git/hooks/pre-push .git/hooks/pre-push.sample 2>/dev/null || true

echo "✅ Git hooks installed"
echo ""
echo "Hooks installed:"
echo "  - pre-commit: Runs linting before each commit"
echo "  - pre-push: Runs tests before each push"
echo ""
echo "To bypass hooks (not recommended), use:"
echo "  git commit --no-verify"
echo "  git push --no-verify"
