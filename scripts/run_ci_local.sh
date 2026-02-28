#!/usr/bin/env bash
set -euo pipefail

# Run GitHub Actions CI jobs locally using Docker.
#
# Default: runs backend, API e2e, dice ladder, and all Playwright shards.
# Usage examples:
#   scripts/run_ci_local.sh
#   scripts/run_ci_local.sh --job backend
#   scripts/run_ci_local.sh --job playwright --shard 2/4
#   scripts/run_ci_local.sh --skip-build

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE_TAG="comic-pile-ci:local"
PG_CONTAINER="comic-pile-ci-postgres"
CI_NETWORK="comic-pile-ci-net-$RANDOM"
API_PORT="8000"
DB_URL="postgresql+asyncpg://postgres:postgres@postgres:5432/comic_pile_test"

RUN_BACKEND=1
RUN_API_E2E=1
RUN_DICE_E2E=1
RUN_PLAYWRIGHT=1
PLAYWRIGHT_SHARDS=("1/4" "2/4" "3/4" "4/4")
SKIP_BUILD=0

usage() {
  cat <<'EOF'
Usage: scripts/run_ci_local.sh [options]

Options:
  --job <all|backend|api-e2e|dice-e2e|playwright>
  --shard <n/4>         Run only one Playwright shard (implies --job playwright if used alone)
  --skip-build          Reuse existing local CI image
  -h, --help            Show help
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
          RUN_BACKEND=1; RUN_API_E2E=1; RUN_DICE_E2E=1; RUN_PLAYWRIGHT=1
          ;;
        backend)
          RUN_BACKEND=1; RUN_API_E2E=0; RUN_DICE_E2E=0; RUN_PLAYWRIGHT=0
          ;;
        api-e2e)
          RUN_BACKEND=0; RUN_API_E2E=1; RUN_DICE_E2E=0; RUN_PLAYWRIGHT=0
          ;;
        dice-e2e)
          RUN_BACKEND=0; RUN_API_E2E=0; RUN_DICE_E2E=1; RUN_PLAYWRIGHT=0
          ;;
        playwright)
          RUN_BACKEND=0; RUN_API_E2E=0; RUN_DICE_E2E=0; RUN_PLAYWRIGHT=1
          ;;
        *)
          echo "Unknown job: ${2:-}"
          usage
          exit 1
          ;;
      esac
      shift 2
      ;;
    --shard)
      if [[ -z "${2:-}" ]]; then
        echo "--shard requires a value like 1/4"
        usage
        exit 1
      fi
      PLAYWRIGHT_SHARDS=("${2:-}")
      RUN_PLAYWRIGHT=1
      shift 2
      ;;
    --skip-build)
      SKIP_BUILD=1
      shift
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

run_in_ci_image() {
  local cmd="$1"
  docker run --rm --network "${CI_NETWORK}" \
    -e CI=true \
    -e SECRET_KEY=test-secret-key-for-testing-only \
    -e DATABASE_URL="${DB_URL}" \
    -e TEST_DATABASE_URL="${DB_URL}" \
    -e PGUSER=postgres \
    -v "${ROOT_DIR}:/repo" \
    -w /repo \
    "${IMAGE_TAG}" \
    bash -lc "export PATH=/workspace/.venv/bin:\$PATH; ${cmd}"
}

start_postgres() {
  docker rm -f "${PG_CONTAINER}" >/dev/null 2>&1 || true
  docker run -d --name "${PG_CONTAINER}" \
    --network "${CI_NETWORK}" \
    --network-alias postgres \
    -e POSTGRES_USER=postgres \
    -e POSTGRES_PASSWORD=postgres \
    -e POSTGRES_DB=comic_pile_test \
    postgres:16 >/dev/null

  local i
  for i in $(seq 1 30); do
    if docker exec "${PG_CONTAINER}" pg_isready -U postgres >/dev/null 2>&1; then
      echo "PostgreSQL is ready"
      return
    fi
    sleep 2
  done
  echo "PostgreSQL failed to start"
  exit 1
}

cleanup() {
  docker rm -f "${PG_CONTAINER}" >/dev/null 2>&1 || true
  docker network rm "${CI_NETWORK}" >/dev/null 2>&1 || true
}

trap cleanup EXIT

docker network create "${CI_NETWORK}" >/dev/null
echo "Using isolated Docker network: ${CI_NETWORK} (postgres:5432, api:${API_PORT})"

if [[ "${SKIP_BUILD}" -eq 0 ]]; then
  echo "Building ${IMAGE_TAG} from Dockerfile.ci..."
  docker build -f "${ROOT_DIR}/Dockerfile.ci" -t "${IMAGE_TAG}" "${ROOT_DIR}"
fi

echo "Starting PostgreSQL service container..."
start_postgres

if [[ "${RUN_BACKEND}" -eq 1 ]]; then
  echo "Running backend tests..."
  run_in_ci_image "rm -f .env .envrc .env.local .env.production 2>/dev/null || true; /workspace/.venv/bin/python -m pytest tests/ --cov=comic_pile --cov-report=xml"
fi

if [[ "${RUN_API_E2E}" -eq 1 ]]; then
  echo "Running API e2e tests..."
  run_in_ci_image "/workspace/.venv/bin/python -m pytest tests_e2e/test_api_workflows.py -v --no-cov"
fi

if [[ "${RUN_DICE_E2E}" -eq 1 ]]; then
  echo "Running dice ladder e2e tests..."
  run_in_ci_image "/workspace/.venv/bin/python -m pytest tests_e2e/test_dice_ladder_e2e.py -v --no-cov"
fi

if [[ "${RUN_PLAYWRIGHT}" -eq 1 ]]; then
  local_shards=("${PLAYWRIGHT_SHARDS[@]}")
  for shard in "${local_shards[@]}"; do
    echo "Running Playwright shard ${shard}..."
    docker run --rm --network "${CI_NETWORK}" --shm-size=2gb --memory=8gb --cpus=4 \
      -e CI=true \
      -e SECRET_KEY=test-secret-key-for-testing-only \
      -e DATABASE_URL="${DB_URL}" \
      -e TEST_DATABASE_URL="${DB_URL}" \
      -e BASE_URL="http://localhost:8000" \
      -e API_PORT="${API_PORT}" \
      -e PGUSER=postgres \
      -v "${ROOT_DIR}:/repo" \
      -w /repo \
      "${IMAGE_TAG}" \
      bash -lc "export PATH=/workspace/.venv/bin:\$PATH; rm -f .env .envrc .env.local .env.production 2>/dev/null || true; \
        cd /repo/frontend && npm ci && npx playwright install --with-deps chromium && npm run build; \
        cd /repo; \
        export AUTO_BACKUP_ENABLED=false; \
        /workspace/.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port ${API_PORT} --workers 4 --log-level warning >/tmp/backend.log 2>&1 & \
        ready=0; \
        for i in \$(seq 1 30); do \
          if curl -fsS http://localhost:${API_PORT}/health >/dev/null; then ready=1; break; fi; \
          sleep 2; \
        done; \
        if [ \"\$ready\" -ne 1 ]; then \
          echo 'Backend failed to start in Playwright container'; \
          cat /tmp/backend.log || true; \
          exit 1; \
        fi; \
        cd /repo/frontend && REUSE_EXISTING_SERVER=true npx playwright test --project=chromium --shard=${shard}"
  done
fi

echo "Local CI run completed."
