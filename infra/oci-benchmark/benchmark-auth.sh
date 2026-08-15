#!/usr/bin/env bash
set -euo pipefail

BASE="http://127.0.0.1:8000"
read -r -p "ComicPile username: " USERNAME
read -r -s -p "ComicPile password: " PASSWORD
echo

LOGIN_RESPONSE="$(USERNAME="$USERNAME" PASSWORD="$PASSWORD" python3 - <<'PY'
import json, os, urllib.request
payload = json.dumps({"username": os.environ["USERNAME"], "password": os.environ["PASSWORD"]}).encode()
req = urllib.request.Request("http://127.0.0.1:8000/api/v1/auth/login", data=payload, headers={"Content-Type":"application/json"}, method="POST")
with urllib.request.urlopen(req) as r:
    print(r.read().decode())
PY
)"
ACCESS_TOKEN="$(printf '%s' "$LOGIN_RESPONSE" | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')"
unset PASSWORD LOGIN_RESPONSE

echo "Login succeeded."

request() {
  local path="$1"
  curl -sS -o /dev/null -H "Authorization: Bearer $ACCESS_TOKEN" -w '%{http_code} %{time_total}\n' "$BASE$path"
}

echo
echo "=== Single requests ==="
for spec in "auth/me:/api/v1/auth/me" "roll/bootstrap:/api/v1/roll/bootstrap" "releases:/api/v1/releases/"; do
  name="${spec%%:*}"; path="${spec#*:}"
  read -r status total <<<"$(request "$path")"
  printf '%-15s status=%s total=%ss\n' "$name" "$status" "$total"
  if [ "$status" != "200" ]; then
    echo "Refusing to benchmark: $path returned $status" >&2
    exit 1
  fi
done

# Verify multi-worker auth before timing batches.
STATUS_COUNTS="$(for _ in $(seq 1 20); do request /api/v1/auth/me | awk '{print $1}'; done | sort | uniq -c)"
if [ "$STATUS_COUNTS" != "     20 200" ] && [ "$STATUS_COUNTS" != "20 200" ]; then
  echo "Refusing to benchmark because auth is not stable across workers:" >&2
  echo "$STATUS_COUNTS" >&2
  exit 1
fi

summarize() {
  sort -n "$1" | awk '{a[NR]=$1; sum+=$1} END {print "requests:",NR; print "avg:",sum/NR; print "p50:",a[int(NR*0.50)]; print "p95:",a[int(NR*0.95)]; print "max:",a[NR]}'
}

run_batch() {
  local concurrency="$1" count="$2" out="$3"
  export ACCESS_TOKEN BASE
  seq 1 "$count" | xargs -P "$concurrency" -I{} bash -c '
    result=$(curl -sS -o /dev/null -H "Authorization: Bearer $ACCESS_TOKEN" -w "%{http_code} %{time_total}" "$BASE/api/v1/roll/bootstrap")
    status=${result%% *}; total=${result#* }
    if [ "$status" != 200 ]; then echo "HTTP_$status" >&2; exit 42; fi
    echo "$total"
  ' > "$out"
}

echo
echo "=== roll/bootstrap sequential, 20 requests ==="
run_batch 1 20 /tmp/oci-bootstrap-c1.txt
summarize /tmp/oci-bootstrap-c1.txt

echo
echo "=== roll/bootstrap concurrency 5, 30 requests ==="
run_batch 5 30 /tmp/oci-bootstrap-c5.txt
summarize /tmp/oci-bootstrap-c5.txt

echo
echo "=== roll/bootstrap concurrency 10, 30 requests ==="
run_batch 10 30 /tmp/oci-bootstrap-c10.txt
summarize /tmp/oci-bootstrap-c10.txt

echo
echo "=== Memory/load ==="
free -h
uptime
