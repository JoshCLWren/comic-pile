#!/usr/bin/env bash
set -euo pipefail

# Capture a small, portable cold/warm timing bundle for ComicPile production.
#
# Prerequisites:
#   - Vercel CLI 48.9.0+ authenticated for the ComicPile project
#   - standalone httpstat executable available on PATH
#   - Run from the repository root
#
# The output is intentionally limited to request timing and request IDs. It does
# not print environment variables, credentials, response bodies, or user data.

if ! command -v vercel >/dev/null 2>&1; then
  printf 'Vercel CLI is required. Install or upgrade it before running this capture.\n' >&2
  exit 1
fi

if ! command -v httpstat >/dev/null 2>&1; then
  printf 'The standalone httpstat executable is required. Install it (for example, brew install httpstat or pip install httpstat) and retry.\n' >&2
  exit 1
fi

VERCEL_VERSION="$(vercel --version 2>/dev/null | grep -Eo '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || true)"
if [[ -z "$VERCEL_VERSION" ]]; then
  printf 'Could not determine Vercel CLI version; version 48.9.0 or newer is required.\n' >&2
  exit 1
fi

if ! printf '%s\n%s\n' '48.9.0' "$VERCEL_VERSION" | sort -V -C; then
  printf 'Vercel CLI 48.9.0 or newer is required; found %s. Please upgrade and retry.\n' "$VERCEL_VERSION" >&2
  exit 1
fi

OUTPUT_DIR="${1:-artifacts/startup-timing}"
mkdir -p "$OUTPUT_DIR"

STAMP="$(date '+%Y-%m-%dT%H:%M:%S%z')"
SAFE_STAMP="$(date '+%Y%m%d-%H%M%S')"
OUT="$OUTPUT_DIR/startup-timing-$SAFE_STAMP.txt"

capture() {
  local label="$1"
  local path="$2"

  {
    printf '\n=== %s ===\n' "$label"
    printf 'captured_at=%s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')"
    printf 'path=%s\n' "$path"
    printf 'classification=verify X-App-Cold-Request in captured response headers (1=cold, 0=warm)\n'
    printf 'correlate=retain X-Request-ID from captured response headers\n'
  } | tee -a "$OUT"

  vercel httpstat "$path" 2>&1 | tee -a "$OUT"
}

{
  printf 'ComicPile production startup timing capture\n'
  printf 'started_at=%s\n' "$STAMP"
  printf 'purpose=cold-vs-warm request timing without response-body or user-data capture\n'
} > "$OUT"

capture "potential cold root" "/"
capture "potential warm root" "/"
capture "potential warm OpenAPI" "/openapi.json"

printf '\nSaved timing bundle: %s\n' "$OUT"
