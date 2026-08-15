#!/usr/bin/env bash
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this helper with sudo: sudo $0" >&2
  exit 1
fi

ENV_DIR="/etc/comicpile"
ENV_FILE="$ENV_DIR/benchmark.env"
APP_USER="comicpile"
APP_DIR="/opt/comic-pile"
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
filtered = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k not in {"sslmode", "channel_binding"}]
print(urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(filtered), parts.fragment)))
PY
} )"
unset RAW_DATABASE_URL

# ComicPile currently randomizes SECRET_KEY in staging even when one is supplied.
# Patch only this benchmark checkout so two Uvicorn workers share the explicit key.
python3 - <<'PY'
from pathlib import Path
path = Path('/opt/comic-pile/app/config.py')
text = path.read_text()
old = 'if environment == "test" and v and v.strip():'
new = 'if environment in {"staging", "test"} and v and v.strip():'
if old in text:
    path.write_text(text.replace(old, new, 1))
elif new not in text:
    raise SystemExit('Expected AuthSettings staging/test condition not found')
PY
chown "$APP_USER:$APP_USER" "$APP_DIR/app/config.py"

SECRET_KEY="$(openssl rand -hex 32)"
install -d -m 0750 -o root -g "$APP_USER" "$ENV_DIR"

DATABASE_URL="$DATABASE_URL" SECRET_KEY="$SECRET_KEY" python3 - "$ENV_FILE" <<'PY'
import os
import sys
path = sys.argv[1]
def esc(value: str) -> str:
    return value.replace('\\', '\\\\').replace('"', '\\"')
with open(path, 'w', encoding='utf-8') as handle:
    handle.write('ENVIRONMENT="staging"\n')
    handle.write('WEB_CONCURRENCY="2"\n')
    handle.write('CACHE_ENABLED="false"\n')
    handle.write(f'DATABASE_URL="{esc(os.environ["DATABASE_URL"])}"\n')
    handle.write(f'SECRET_KEY="{esc(os.environ["SECRET_KEY"])}"\n')
PY
unset DATABASE_URL SECRET_KEY

chown root:"$APP_USER" "$ENV_FILE"
chmod 0640 "$ENV_FILE"

systemctl daemon-reload
systemctl enable --now comicpile-benchmark.service

echo "Waiting up to ${READY_TIMEOUT_SECONDS}s for ComicPile to become healthy..."
for second in $(seq 1 "$READY_TIMEOUT_SECONDS"); do
  if curl --max-time 2 --silent --fail http://127.0.0.1:8000/health >/dev/null; then
    echo "ComicPile benchmark service is healthy after ${second}s"
    exit 0
  fi
  if (( second % 10 == 0 )); then
    echo "Still waiting (${second}s elapsed)..."
  fi
  sleep 1
done

echo "ComicPile did not become healthy within ${READY_TIMEOUT_SECONDS}s." >&2
systemctl status comicpile-benchmark.service --no-pager >&2 || true
journalctl -u comicpile-benchmark.service --since "-${READY_TIMEOUT_SECONDS} seconds" --no-pager >&2 || true
exit 1
