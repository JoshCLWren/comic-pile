#!/usr/bin/env bash
# Install git hooks for this repository.

set -euo pipefail

echo "🔧 Installing git hooks..."

mkdir -p .git/hooks .git/hooks/comic-pile-originals

backup_original_hook() {
    local hook_name="$1"
    local active_hook=".git/hooks/$hook_name"
    local backup_hook=".git/hooks/comic-pile-originals/$hook_name"

    if [[ -f "$active_hook" && ! -e "$backup_hook" ]]; then
        cp "$active_hook" "$backup_hook"
    fi
}

# Preserve each pre-existing user hook exactly once. Re-running this installer
# must never replace the original backup with ComicPile's installed hook.
backup_original_hook pre-commit
backup_original_hook pre-push
backup_original_hook prepare-commit-msg

# Install from versioned hooks.
cp .githooks/pre-commit .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit

if [[ -f .githooks/pre-push ]]; then
    cp .githooks/pre-push .git/hooks/pre-push
    chmod +x .git/hooks/pre-push
fi

if [[ -f .githooks/prepare-commit-msg ]]; then
    cp .githooks/prepare-commit-msg .git/hooks/prepare-commit-msg
    chmod +x .git/hooks/prepare-commit-msg
fi

echo "✅ Git hooks installed"
echo ""
echo "Hooks installed:"
echo "  - pre-commit: Runs linting before each commit"
echo "  - pre-push: Runs tests before each push"
echo "  - prepare-commit-msg: Adds the producing model trailer (\$OPENCODE_MODEL)"
echo ""
echo "Original user hooks, when present, are preserved in:"
echo "  .git/hooks/comic-pile-originals/"
