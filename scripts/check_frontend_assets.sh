#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-${PROD_BASE_URL:-}}"

if [ -z "$BASE_URL" ]; then
  echo "Usage: scripts/check_frontend_assets.sh <BASE_URL>"
  echo "Example: scripts/check_frontend_assets.sh https://app-production-72b9.up.railway.app"
  exit 1
fi

BASE_URL="${BASE_URL%/}"
ROOT_URL="$BASE_URL/"

echo "Checking frontend entrypoint: $ROOT_URL"
html=$(curl -fsSL "$ROOT_URL")

if [ -z "$html" ]; then
  echo "ERROR: Empty HTML response from $ROOT_URL"
  exit 1
fi

mapfile -t assets < <(printf '%s' "$html" | grep -oE '/assets/[^"\047 ]+\.(js|css)' | sort -u)

if [ "${#assets[@]}" -eq 0 ]; then
  echo "ERROR: No /assets/*.js or /assets/*.css references found in HTML"
  exit 1
fi

echo "Found ${#assets[@]} frontend assets in HTML"
for asset in "${assets[@]}"; do
  url="$BASE_URL$asset"
  echo "Checking asset: $url"
  curl -fsSI "$url" >/dev/null
  echo "OK: $asset"
done

echo "Frontend asset validation passed for $BASE_URL"
