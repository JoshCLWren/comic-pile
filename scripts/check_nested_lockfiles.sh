#!/usr/bin/env bash
set -euo pipefail

# Reject lockfiles inside pnpm workspace packages. The repository root
# pnpm-lock.yaml is the only lockfile pnpm installs from in this workspace.
# Reintroducing a nested lockfile causes silent drift and duplicate Dependabot PRs.

cd "$(git rev-parse --show-toplevel)"

if [[ ! -f pnpm-workspace.yaml ]]; then
  echo "pnpm-workspace.yaml not found; cannot determine workspace packages." >&2
  exit 1
fi

mapfile -t packages < <(
  python3 - <<'PY'
import pathlib
import re

text = pathlib.Path("pnpm-workspace.yaml").read_text(encoding="utf-8")
# Parse simple pnpm-workspace package entries: `  - 'frontend'` / `  - "pkg/*"` / `  - frontend`
for raw in text.splitlines():
    m = re.match(r"^\s*-\s*['\"]?([^'\"#]+?)['\"]?\s*(?:#.*)?$", raw)
    if not m:
        continue
    value = m.group(1).strip()
    if value:
        print(value)
PY
)

if [[ ${#packages[@]} -eq 0 ]]; then
  echo "No workspace packages found in pnpm-workspace.yaml." >&2
  exit 1
fi

lock_names=(pnpm-lock.yaml package-lock.json yarn.lock npm-shrinkwrap.json bun.lock bun.lockb)
status=0

for pkg in "${packages[@]}"; do
  # Expand simple workspace globs; ignore non-matching patterns.
  shopt -s nullglob
  matches=($pkg)
  shopt -u nullglob
  if [[ ${#matches[@]} -eq 0 ]]; then
    continue
  fi
  for dir in "${matches[@]}"; do
    [[ -d "$dir" ]] || continue
    for name in "${lock_names[@]}"; do
      if [[ -f "$dir/$name" ]]; then
        echo "ERROR: nested lockfile found in workspace package: $dir/$name" >&2
        echo "Remove it and use the repository root pnpm-lock.yaml." >&2
        status=1
      fi
    done
  done
done

if [[ $status -eq 0 ]]; then
  echo "No nested lockfiles found in workspace packages."
fi

exit "$status"
