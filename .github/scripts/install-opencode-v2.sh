#!/usr/bin/env bash
# Resolve the latest OpenCode 2 from the official npm channel at execution time.
set -Eeuo pipefail
root="${RUNNER_TEMP:-/tmp}/comic-pile-opencode-v2"
npm install --global --prefix "$root" @opencode/cli@latest
binary="$root/bin/opencode"
test -x "$binary"
version="$("$binary" --version)"
if [[ ! "$version" =~ (^|[[:space:]])v?2\. ]]; then
  echo "OpenCode 2 required; received version '$version'" >&2
  exit 1
fi
echo "$root/bin" >> "${GITHUB_PATH:?GITHUB_PATH is required}"
# CI is noninteractive: authorize routine coding tools while keeping
# commits/pushes under the trusted factory wrapper, not the model.
mkdir -p "$HOME/.config/opencode"
cat > "$HOME/.config/opencode/opencode.json" <<'JSON'
{
  "$schema": "https://opencode.ai/config.json",
  "permissions": [
    {"action": "read", "resource": "*", "effect": "allow"},
    {"action": "edit", "resource": "*", "effect": "allow"},
    {"action": "shell", "resource": "*", "effect": "allow"},
    {"action": "glob", "resource": "*", "effect": "allow"},
    {"action": "grep", "resource": "*", "effect": "allow"},
    {"action": "skill", "resource": "*", "effect": "allow"},
    {"action": "subagent", "resource": "*", "effect": "allow"}
  ],
  "policies": [
    {"action": "tool.use", "resource": "shell:git push *", "effect": "deny"},
    {"action": "tool.use", "resource": "shell:git commit *", "effect": "deny"},
    {"action": "tool.use", "resource": "shell:git reset --hard *", "effect": "deny"}
  ]
}
JSON
chmod 600 "$HOME/.config/opencode/opencode.json"
printf 'OpenCode %s installed from the current release\n' "$version"
