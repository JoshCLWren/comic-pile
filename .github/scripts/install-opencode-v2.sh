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
printf 'OpenCode v%s installed from the current release\n' "$version"
