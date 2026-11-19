#!/usr/bin/env bash
# Rehearse scripts/deploy-migrate.sh against LOCAL throwaway databases only.
# Needs ADMIN_URL (server-level URL to a local Postgres) and uv-synced Alembic.
# Usage: ADMIN_URL=postgresql://postgres:pw@127.0.0.1:5432/postgres scripts/rehearse-deploy-migrate.sh <bin>
set -euo pipefail
bin="$(realpath "${1:?usage: rehearse-deploy-migrate.sh <comicpile-migrate binary>}")"
: "${ADMIN_URL:?ADMIN_URL is required}"
case "$ADMIN_URL" in
  postgresql://*@127.0.0.1:*|postgresql://*@localhost:*) ;;
  *) echo "REFUSING: ADMIN_URL must be a local Postgres" >&2; exit 1 ;;
esac
unset DATABASE_URL NEON_DATABASE_URL
base="${ADMIN_URL%/*}"
suffix="$$"
cleanup() {
  for d in rehearse_alembic_$suffix rehearse_empty_$suffix; do
    psql "$ADMIN_URL" -qc "DROP DATABASE IF EXISTS $d WITH (FORCE)" || true
  done
}
trap cleanup EXIT

expect_output() {
  local out
  out="$(run_step "$1")"
  printf '%s\n' "$out"
  grep -qF -- "$2" <<< "$out" || { echo "expected output: $2" >&2; exit 1; }
}
run_step() { MIGRATE_DATABASE_URL="$1" "$(dirname "$0")/deploy-migrate.sh" "$bin"; }

echo "== (a) Alembic-head database, not yet adopted =="
a=rehearse_alembic_$suffix
psql "$ADMIN_URL" -qc "CREATE DATABASE $a"
DATABASE_URL="$base/$a" uv run alembic upgrade head
expect_output "$base/$a" 'adopted as already applied: [1]'
expect_output "$base/$a" 'migrations applied: []; adopted as already applied: []'
adopted="$(psql "$base/$a" -Atc 'SELECT adopted FROM public.schema_migrations WHERE version = 1')"
[[ "$adopted" == "t" ]]

echo "== (b) empty database =="
e=rehearse_empty_$suffix
psql "$ADMIN_URL" -qc "CREATE DATABASE $e"
expect_output "$base/$e" 'migrations applied: [1]'
expect_output "$base/$e" 'migrations applied: []; adopted as already applied: []'

echo "== (c) database at a non-baseline Alembic revision must fail =="
psql "$base/$a" -qc "UPDATE public.alembic_version SET version_num = 'bogus'"
psql "$base/$a" -qc "DROP TABLE public.schema_migrations"
if run_step "$base/$a"; then echo "expected failure" >&2; exit 1; fi
echo "rehearsal OK"
