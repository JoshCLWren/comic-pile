#!/usr/bin/env bash
set -euo pipefail

# Run local equivalents of the current GitHub Actions CI jobs.
#
# This script no longer drives the retired Python application runtime.
# It targets the live Rust ingress and frontend CI jobs.
#
# Usage examples:
#   scripts/run_ci_local.sh
#   scripts/run_ci_local.sh --job rust-ingress
#   scripts/run_ci_local.sh --job frontend

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

RUN_RUST_INGRESS=1
RUN_FRONTEND=1

usage() {
  cat <<'EOF'
Usage: scripts/run_ci_local.sh [options]

Options:
  --job <all|rust-ingress|frontend>
                              Select which CI lane to run (default: all)
  -h, --help                  Show help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --job)
      if [[ -z "${2:-}" ]]; then
        echo "--job requires a value"
        usage
        exit 1
      fi
      case "${2:-}" in
        all)
          RUN_RUST_INGRESS=1
          RUN_FRONTEND=1
          ;;
        rust-ingress)
          RUN_RUST_INGRESS=1
          RUN_FRONTEND=0
          ;;
        frontend)
          RUN_RUST_INGRESS=0
          RUN_FRONTEND=1
          ;;
        *)
          echo "Unknown job: ${2:-}"
          usage
          exit 1
          ;;
      esac
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1"
      usage
      exit 1
      ;;
  esac
done

if [[ "${RUN_RUST_INGRESS}" -eq 1 ]]; then
  echo "==> Rust ingress checks"
  node scripts/generate_vercel_routes.mjs --check
  node scripts/generate_route_burndown.mjs --check
  node --test \
    scripts/generate_route_burndown.test.mjs \
    scripts/generate_openapi_types.test.mjs \
    scripts/generate_vercel_routes.test.mjs \
    scripts/vercel_slim_routes.test.mjs \
    scripts/generate_ui_audit_ingress.test.mjs
fi

if [[ "${RUN_FRONTEND}" -eq 1 ]]; then
  echo "==> Frontend checks"
  pnpm install --frozen-lockfile
  pnpm run lint:anti-slop
  node --test scripts/anti_slop_scope.test.mjs
  pnpm --filter frontend run lint
  pnpm --filter frontend run check:unused
  pnpm --filter frontend run check:api-types
  pnpm --filter frontend run typecheck
  pnpm run build
  pnpm --filter frontend test:coverage
fi

echo "Local CI run completed."
