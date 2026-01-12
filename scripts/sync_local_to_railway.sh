#!/usr/bin/env bash
set -euo pipefail

RAILWAY_DB_SERVICE="${RAILWAY_DB_SERVICE:-Postgres}"
RAILWAY_ENVIRONMENT="${RAILWAY_ENVIRONMENT:-production}"

if ! command -v railway >/dev/null 2>&1; then
  echo "railway CLI not found in PATH." >&2
  exit 1
fi

if ! command -v pg_dump >/dev/null 2>&1 || ! command -v psql >/dev/null 2>&1; then
  echo "pg_dump/psql not found in PATH. Install PostgreSQL client tools." >&2
  exit 1
fi

if [ ! -f .env ]; then
  echo ".env not found in repo root." >&2
  exit 1
fi

LOCAL_DB_URL=$(python - <<'PY'
from pathlib import Path

url = None
for line in Path(".env").read_text().splitlines():
    if line.startswith("DATABASE_URL="):
        url = line.split("=", 1)[1].strip()
        break
if not url:
    raise SystemExit("DATABASE_URL not found in .env")
if url.startswith("postgresql+psycopg://"):
    url = url.replace("postgresql+psycopg://", "postgresql://", 1)
print(url)
PY
)

VARS_FILE=$(mktemp /tmp/railway_vars.XXXXXX.json)
trap 'rm -f "$VARS_FILE"' EXIT

railway variables --service "$RAILWAY_DB_SERVICE" --environment "$RAILWAY_ENVIRONMENT" --json \
  > "$VARS_FILE"

REMOTE_DB_URL=$(python - <<PY
import json
with open("$VARS_FILE", "r") as f:
    j = json.load(f)
print(j["DATABASE_PUBLIC_URL"])
PY
)

echo "This will DROP and RECREATE schema public on Railway ($RAILWAY_DB_SERVICE/$RAILWAY_ENVIRONMENT)."
read -r -p "Type 'yes' to continue: " confirm
if [ "$confirm" != "yes" ]; then
  echo "Aborted."
  exit 1
fi

TMPFILE=$(mktemp /tmp/comicpile_dump.XXXXXX.sql)
trap 'rm -f "$TMPFILE" "$VARS_FILE"' EXIT

pg_dump "$LOCAL_DB_URL" --no-owner --no-privileges > "$TMPFILE"
psql "$REMOTE_DB_URL" -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
psql "$REMOTE_DB_URL" < "$TMPFILE"

echo "Done."
