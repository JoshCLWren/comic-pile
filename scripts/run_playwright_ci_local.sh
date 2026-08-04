#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE_TAG="comic-pile-ci:local"
NETWORK_NAME="comic-pile-playwright-$RANDOM"
POSTGRES_CONTAINER="comic-pile-playwright-postgres-$RANDOM"
MODE="smoke"
BROWSERS=(firefox webkit chromium)
SHARDS=("1/1")
SKIP_BUILD=0
AFFECTED_SPECS=""

usage() {
  cat <<'EOF'
Usage: scripts/run_playwright_ci_local.sh [options]

Options:
  --browser <firefox|webkit|chromium|all>  Browser selection (default: all)
  --mode <smoke|affected|full>             Deterministic E2E mode (default: smoke)
  --shards <count>                         Split each browser into count shards (default: 1)
  --affected-specs <comma-separated>       Explicit specs for affected mode
  --skip-build                             Reuse comic-pile-ci:local
  -h, --help                               Show help

Examples:
  scripts/run_playwright_ci_local.sh --browser all --mode smoke
  scripts/run_playwright_ci_local.sh --browser firefox --mode full --shards 6
  scripts/run_playwright_ci_local.sh --mode affected --affected-specs src/test/history.spec.ts
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --browser)
      case "${2:-}" in
        firefox|webkit|chromium) BROWSERS=("$2") ;;
        all) BROWSERS=(firefox webkit chromium) ;;
        *) echo "Unsupported browser: ${2:-}"; usage; exit 1 ;;
      esac
      shift 2
      ;;
    --mode)
      case "${2:-}" in
        smoke|affected|full) MODE="$2" ;;
        *) echo "Unsupported mode: ${2:-}"; usage; exit 1 ;;
      esac
      shift 2
      ;;
    --shards)
      shard_count="${2:-}"
      if [[ ! "${shard_count}" =~ ^[1-9][0-9]*$ ]]; then
        echo "--shards requires a positive integer"
        exit 1
      fi
      SHARDS=()
      for shard_index in $(seq 1 "${shard_count}"); do
        SHARDS+=("${shard_index}/${shard_count}")
      done
      shift 2
      ;;
    --affected-specs)
      AFFECTED_SPECS="${2:-}"
      if [[ -z "${AFFECTED_SPECS}" ]]; then
        echo "--affected-specs requires a comma-separated value"
        exit 1
      fi
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

cleanup() {
  docker rm -f "${POSTGRES_CONTAINER}" >/dev/null 2>&1 || true
  docker network rm "${NETWORK_NAME}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

create_database() {
  local database_name="$1"
  docker run --rm --network "${NETWORK_NAME}" \
    -e PGPASSWORD=postgres postgres:16 \
    createdb -h postgres -U postgres "${database_name}"
}

wait_for_postgres() {
  for _ in $(seq 1 30); do
    if docker exec "${POSTGRES_CONTAINER}" pg_isready -U postgres >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  echo "PostgreSQL failed to become ready"
  return 1
}

if [[ "${SKIP_BUILD}" -eq 0 ]]; then
  docker build -f "${ROOT_DIR}/Dockerfile.ci" -t "${IMAGE_TAG}" "${ROOT_DIR}"
fi

docker network create "${NETWORK_NAME}" >/dev/null
docker run -d --name "${POSTGRES_CONTAINER}" \
  --network "${NETWORK_NAME}" --network-alias postgres \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=postgres \
  postgres:16 >/dev/null
wait_for_postgres

pids=()
names=()
for browser in "${BROWSERS[@]}"; do
  for shard in "${SHARDS[@]}"; do
    shard_index="${shard%/*}"
    total_shards="${shard#*/}"
    database_name="comic_pile_${browser}_${shard_index}_${RANDOM}"
    create_database "${database_name}"
    database_url="postgresql+asyncpg://postgres:postgres@postgres:5432/${database_name}"
    run_name="${browser} ${MODE} shard ${shard}"
    echo "Starting ${run_name}"

    docker run --rm --network "${NETWORK_NAME}" \
      --shm-size=2gb --memory=8gb --cpus=4 \
      -e CI=true \
      -e HOME=/root \
      -e TEST_ENVIRONMENT=true \
      -e SECRET_KEY=test-secret-key-for-testing-only \
      -e DATABASE_URL="${database_url}" \
      -e TEST_DATABASE_URL="${database_url}" \
      -e REDIS_URL=redis://localhost:6379/0 \
      -e E2E_BROWSER="${browser}" \
      -e E2E_AFFECTED_SPECS="${AFFECTED_SPECS}" \
      -e API_PORT=9000 \
      -e BASE_URL=http://localhost:9000 \
      "${IMAGE_TAG}" bash -lc "
        set -euo pipefail
        export PATH=/workspace/.venv/bin:\$PATH
        rm -f .env .env.test .envrc .env.local .env.production
        redis-server --daemonize yes
        alembic upgrade head
        python -m uvicorn app.main:app --host 0.0.0.0 --port 9000 --workers 4 >/tmp/backend.log 2>&1 &
        backend_pid=\$!
        trap 'kill \${backend_pid} >/dev/null 2>&1 || true; cat /tmp/backend.log' EXIT
        for attempt in \$(seq 1 30); do
          curl -fsS http://localhost:9000/health >/dev/null && break
          if [[ \${attempt} -eq 30 ]]; then exit 1; fi
          sleep 2
        done
        cd /workspace/frontend
        REUSE_EXISTING_SERVER=true node scripts/e2e-mode.mjs '${MODE}' --shard='${shard}' --workers=1
      " &
    pids+=("$!")
    names+=("${run_name}")
  done
done

failed=0
for index in "${!pids[@]}"; do
  if wait "${pids[$index]}"; then
    echo "Passed: ${names[$index]}"
  else
    echo "Failed: ${names[$index]}"
    failed=1
  fi
done

if [[ "${failed}" -ne 0 ]]; then
  echo "One or more browser runs failed"
  exit 1
fi

echo "All requested browser runs passed."
