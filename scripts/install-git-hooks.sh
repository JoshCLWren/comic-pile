#!/usr/bin/env bash
# Install git hooks for this repository

set -e

echo "🔧 Installing git hooks..."

# Backup any existing hooks
cp .git/hooks/pre-commit .git/hooks/pre-commit.sample 2>/dev/null || true
cp .git/hooks/pre-push .git/hooks/pre-push.sample 2>/dev/null || true
cp .git/hooks/prepare-commit-msg .git/hooks/prepare-commit-msg.sample 2>/dev/null || true

# Install from versioned hooks
mkdir -p .git/hooks
cp .githooks/pre-commit .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit

if [ -f .githooks/pre-push ]; then
    cp .githooks/pre-push .git/hooks/pre-push
    chmod +x .git/hooks/pre-push
fi

if [ -f .githooks/prepare-commit-msg ]; then
    cp .githooks/prepare-commit-msg .git/hooks/prepare-commit-msg
    chmod +x .git/hooks/prepare-commit-msg
fi

echo "✅ Git hooks installed"
echo ""
echo "Hooks installed:"
echo "  - pre-commit: Runs linting before each commit"
echo "  - pre-push: Runs tests before each push"
echo "  - prepare-commit-msg: Signs commits with the producing model (\$OPENCODE_MODEL)"
echo ""
echo "To bypass hooks (not recommended), use:"
echo "  git commit --no-verify"
echo "  git push --no-verify"
