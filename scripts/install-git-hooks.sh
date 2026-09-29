#!/usr/bin/env bash
# Install git hooks for this repository.

set -euo pipefail

echo "🔧 Installing git hooks..."

if git_common_dir="$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)"; then
    hooks_dir="$git_common_dir/hooks"
else
    # Preserve support for the isolated fixture used by the installer regression test.
    hooks_dir="$(pwd)/.git/hooks"
fi

mkdir -p "$hooks_dir" "$hooks_dir/comic-pile-originals"

backup_original_hook() {
    local hook_name="$1"
    local active_hook="$hooks_dir/$hook_name"
    local backup_hook="$hooks_dir/comic-pile-originals/$hook_name"

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
cp .githooks/pre-commit "$hooks_dir/pre-commit"
chmod +x "$hooks_dir/pre-commit"

if [[ -f .githooks/pre-push ]]; then
    cp .githooks/pre-push "$hooks_dir/pre-push"
    chmod +x "$hooks_dir/pre-push"
fi

if [[ -f .githooks/prepare-commit-msg ]]; then
    cp .githooks/prepare-commit-msg "$hooks_dir/prepare-commit-msg"
    chmod +x "$hooks_dir/prepare-commit-msg"
fi

echo "✅ Git hooks installed"
echo ""
echo "Hooks installed:"
echo "  - pre-commit: Full-repo ruff check . and ty check --error-on-warning"
echo "  - pre-push: Runs tests before each push"
echo "  - prepare-commit-msg: Adds the producing model trailer (\$OPENCODE_MODEL)"
echo ""
echo "Original user hooks, when present, are preserved in:"
echo "  $hooks_dir/comic-pile-originals/"
echo ""
echo "Cursor Cloud remaps core.hooksPath to its dispatcher. That dispatcher"
echo "only chains to these files when they exist and are executable under"
echo "  .git/hooks/"
echo "Re-run this installer at the start of every agent session."
