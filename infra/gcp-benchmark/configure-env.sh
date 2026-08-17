#!/usr/bin/env bash
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this helper with sudo: sudo $0" >&2
  exit 1
fi

ENV_DIR="/etc/comicpile"
ENV_FILE="$ENV_DIR/benchmark.env"
APP_USER="comicpile"
READY_TIMEOUT_SECONDS=90

read -r -s -p "Neon DATABASE_URL: " RAW_DATABASE_URL
echo

if [ -z "$RAW_DATABASE_URL" ]; then
  echo "DATABASE_URL cannot be empty" >&2
  exit 1
fi

DATABASE_URL="$({ RAW_DATABASE_URL="$RAW_DATABASE_URL" python3 - <<'PY'
import os
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

raw = os.environ["RAW_DATABASE_URL"]
parts = urlsplit(raw)
filtered = [
    (key, value)
    for key, value in parse_qsl(parts.query, keep_blank_values=True)
    if key not in {"sslmode", "channel_binding"}
]
print(urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(filtered), parts.fragment)))
PY
} )"
unset RAW_DATABASE_URL

if [ -z "$DATABASE_URL" ]; then
  echo "Failed to normalize DATABASE_URL" >&2
  exit 1
fi

install -d -m 0750 -o root -g "$APP_USER" "$ENV_DIR"

DATABASE_URL="$DATABASE_URL" python3 - "$ENV_FILE" <<'PY'
import os
import secrets
import sys

path = sys.argv[1]
url = os.environ["DATABASE_URL"]
# Generate one shared signing key in the systemd EnvironmentFile so every
# Uvicorn worker signs and verifies benchmark JWTs with the same secret.
secret_key = secrets.token_urlsafe(48)
# systemd EnvironmentFile accepts backslash escapes inside double quotes.
escaped_url = url.replace("\\", "\\\\").replace('"', '\\"')
escaped_secret = secret_key.replace("\\", "\\\\").replace('"', '\\"')
with open(path, "w", encoding="utf-8") as handle:
    handle.write('ENVIRONMENT="staging"\n')
    handle.write('WEB_CONCURRENCY="2"\n')
    handle.write('CACHE_ENABLED="false"\n')
    handle.write(f'SECRET_KEY="{escaped_secret}"\n')
    handle.write(f'DATABASE_URL="{escaped_url}"\n')
PY
unset DATABASE_URL

chown root:"$APP_USER" "$ENV_FILE"
chmod 0640 "$ENV_FILE"

systemctl daemon-reload
systemctl enable --now comicpile-benchmark.service

echo "Waiting up to ${READY_TIMEOUT_SECONDS}s for ComicPile to become healthy..."
for second in $(seq 1 "$READY_TIMEOUT_SECONDS"); do
  if curl --max-time 2 --silent --fail http://127.0.0.1:8000/health >/dev/null; then
    echo "ComicPile benchmark service is healthy on http://127.0.0.1:8000 after ${second}s"
    exit 0
  fi
  if (( second % 10 == 0 )); then
    echo "Still waiting for ComicPile startup (${second}s elapsed)..."
  fi
  sleep 1
done

echo "ComicPile did not become healthy within ${READY_TIMEOUT_SECONDS} seconds." >&2
systemctl status comicpile-benchmark.service --no-pager >&2 || true
journalctl -u comicpile-benchmark.service --since "-${READY_TIMEOUT_SECONDS} seconds" --no-pager >&2 || true
exit 1
