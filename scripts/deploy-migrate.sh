#!/usr/bin/env bash
# Production/rehearsal database migration step, run by deploy-production.yml
# and rehearsed against a throwaway Postgres by .github/workflows/migrate-rehearsal.yml.
#
# Usage: MIGRATE_DATABASE_URL=... scripts/deploy-migrate.sh <path-to-comicpile-migrate>
#
# 1. status : read-only guard. Fails unless the DB is empty, an Alembic DB at
#             the baseline head, or already managed by the Rust runner.
# 2. up     : applies pending migrations (adopts an Alembic-head DB without
#             executing the baseline); idempotent.
# 3. verify : fails unless nothing is pending afterwards.
# The caller orders this before the application deploy, so a failure aborts it.
set -euo pipefail
bin="${1:?usage: deploy-migrate.sh <comicpile-migrate binary>}"
: "${MIGRATE_DATABASE_URL:?MIGRATE_DATABASE_URL is required}"
"$bin" status
"$bin" up
"$bin" verify
