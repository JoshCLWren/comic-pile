#!/usr/bin/env bash
set -euo pipefail

BASE="${BASE:-http://127.0.0.1:8000}"

read -r -p "ComicPile username: " USERNAME
read -r -s -p "ComicPile password: " PASSWORD
echo

LOGIN_JSON="$(
  USERNAME="$USERNAME" PASSWORD="$PASSWORD" python3 - <<'PY'
import json
import os

print(json.dumps({"username": os.environ["USERNAME"], "password": os.environ["PASSWORD"]}))
PY
)"
unset PASSWORD

LOGIN_RESPONSE="$(
  curl --silent --show-error --fail-with-body \
    -H 'Content-Type: application/json' \
    -d "$LOGIN_JSON" \
    "$BASE/api/v1/auth/login"
)"
unset LOGIN_JSON

ACCESS_TOKEN="$(
  printf '%s' "$LOGIN_RESPONSE" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin).get("access_token", ""))'
)"
unset LOGIN_RESPONSE

if [ -z "$ACCESS_TOKEN" ]; then
  echo "Login failed: no access token returned." >&2
  exit 1
fi

echo
echo "Login succeeded."
echo

bench_one() {
  local name="$1"
  local path="$2"

  curl --silent --show-error --output /dev/null \
    -H "Authorization: Bearer $ACCESS_TOKEN" \
    -w "$name status=%{http_code} total=%{time_total}s\n" \
    "$BASE$path"
}

summarize() {
  local file="$1"

  sort -n "$file" | awk '
  {
    a[NR]=$1
    sum+=$1
  }
  END {
    print "requests:", NR
    print "avg:", sum/NR
    print "p50:", a[int(NR*0.50)]
    print "p95:", a[int(NR*0.95)]
    print "max:", a[NR]
  }'
}

echo "=== Single requests ==="
bench_one "auth/me        " "/api/v1/auth/me"
bench_one "roll/bootstrap " "/api/v1/roll/bootstrap"
bench_one "releases       " "/api/v1/releases/"

echo
echo "=== roll/bootstrap sequential, 20 requests ==="
for _ in $(seq 1 20); do
  curl --silent --show-error --output /dev/null \
    -H "Authorization: Bearer $ACCESS_TOKEN" \
    -w '%{time_total}\n' \
    "$BASE/api/v1/roll/bootstrap"
done > /tmp/comicpile-bootstrap-sequential.txt
summarize /tmp/comicpile-bootstrap-sequential.txt

echo
echo "=== roll/bootstrap concurrency 5, 30 requests ==="
export ACCESS_TOKEN BASE
seq 1 30 | xargs -P 5 -I{} bash -c '
  curl --silent --show-error --output /dev/null \
    -H "Authorization: Bearer $ACCESS_TOKEN" \
    -w "%{time_total}\n" \
    "$BASE/api/v1/roll/bootstrap"
' > /tmp/comicpile-bootstrap-c5.txt
summarize /tmp/comicpile-bootstrap-c5.txt

echo
echo "=== roll/bootstrap concurrency 10, 30 requests ==="
seq 1 30 | xargs -P 10 -I{} bash -c '
  curl --silent --show-error --output /dev/null \
    -H "Authorization: Bearer $ACCESS_TOKEN" \
    -w "%{time_total}\n" \
    "$BASE/api/v1/roll/bootstrap"
' > /tmp/comicpile-bootstrap-c10.txt
summarize /tmp/comicpile-bootstrap-c10.txt

echo
echo "=== Memory/load ==="
free -h
uptime

unset ACCESS_TOKEN USERNAME BASE
