#!/usr/bin/env bash
# Regenerate the bot-owned API contracts from the Rust code (owner directive
# 2026-11-19: feature PRs never commit shared generated files).
#
#   native/contracts/v2-runtime.openapi.json   <- cargo example v2_openapi
#   native/contracts/same-path-runtime.openapi.json <- cargo example same_path_openapi
#   frontend/src/generated/{openapi.json,openapi.ts,nativeV2Client.ts}
#                                              <- scripts/generate_openapi_types.mjs
#
# CI runs this on every pull request and push and hands the outputs to the
# frontend jobs, so a feature PR is type-checked against the contract its own
# Rust code produces. regenerate-routes.yml runs it on main and commits the
# result through the route-regeneration bot PR. `--check` additionally fails
# when the committed copies differ from the regenerated ones; CI uses it only
# on that bot PR, which is where the checked-in contract is proven current.
set -Eeuo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly root
cd "$root"

check=false
case "${1:-}" in
  '') ;;
  --check) check=true ;;
  *)
    echo "usage: $0 [--check]" >&2
    exit 2
    ;;
esac

readonly generated=(
  native/contracts/v2-runtime.openapi.json
  native/contracts/same-path-runtime.openapi.json
  frontend/src/generated/openapi.json
  frontend/src/generated/openapi.ts
  frontend/src/generated/nativeV2Client.ts
)

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
cargo run --locked --quiet -p comicpile-roll-service --example v2_openapi >"$tmp/v2.json"
cargo run --locked --quiet -p comicpile-roll-service --example same_path_openapi >"$tmp/same.json"
mv "$tmp/v2.json" native/contracts/v2-runtime.openapi.json
mv "$tmp/same.json" native/contracts/same-path-runtime.openapi.json
node scripts/generate_openapi_types.mjs

if [[ "$check" == true ]]; then
  if ! git diff --exit-code --stat -- "${generated[@]}"; then
    echo "::error::Committed generated contracts differ from what the code produces." >&2
    exit 1
  fi
  echo "Committed generated contracts match the code."
fi
