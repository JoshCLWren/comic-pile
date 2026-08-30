#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/docker-compose.test.yml"
AUDIT_API_PORT="${AUDIT_API_PORT:-8002}"
AUDIT_PROJECT_NAME="${AUDIT_PROJECT_NAME:-comic-pile-ui-audit-$$}"
AUDIT_BASE_URL="http://127.0.0.1:${AUDIT_API_PORT}"
AUDIT_READY_TIMEOUT_SECONDS="${AUDIT_READY_TIMEOUT_SECONDS:-120}"

export E2E_API_PORT="$AUDIT_API_PORT"
# The browser needs only the API on the host. Publishing just the container
# port asks Docker to choose ephemeral host ports for these dependencies.
export E2E_POSTGRES_PUBLISH="${E2E_POSTGRES_PUBLISH:-5432}"
export E2E_REDIS_PUBLISH="${E2E_REDIS_PUBLISH:-6379}"

compose() {
  docker compose --project-name "$AUDIT_PROJECT_NAME" -f "$COMPOSE_FILE" "$@"
}

cleanup() {
  local exit_code=$?
  trap - EXIT INT TERM
  echo "Stopping UI audit test stack ($AUDIT_PROJECT_NAME)..."
  compose down --volumes --remove-orphans >/dev/null 2>&1 || true
  exit "$exit_code"
}
trap cleanup EXIT INT TERM

command -v docker >/dev/null 2>&1 || {
  echo "UI audit requires Docker with Compose support." >&2
  exit 1
}
command -v pnpm >/dev/null 2>&1 || {
  echo "UI audit requires pnpm." >&2
  exit 1
}
command -v curl >/dev/null 2>&1 || {
  echo "UI audit requires curl for backend readiness checks." >&2
  exit 1
}

cd "$ROOT_DIR"

echo "Starting isolated UI audit backend at $AUDIT_BASE_URL..."
compose up -d --build

echo "Waiting for UI audit backend readiness..."
deadline=$((SECONDS + AUDIT_READY_TIMEOUT_SECONDS))
until curl --fail --silent --show-error "$AUDIT_BASE_URL/health" >/dev/null 2>&1; do
  if (( SECONDS >= deadline )); then
    echo "UI audit backend did not become ready within ${AUDIT_READY_TIMEOUT_SECONDS}s." >&2
    compose ps >&2 || true
    compose logs api-test >&2 || true
    exit 1
  fi
  sleep 2
done

echo "Building frontend..."
pnpm --filter frontend run build

echo "Running rendered Chromium UI audit..."
BASE_URL="$AUDIT_BASE_URL" \
  pnpm --filter frontend exec playwright test \
    --config=playwright.audit.config.ts \
    --workers=1

echo "Rendered UI audit completed. Evidence: frontend/test-results/ui-audit/"
