#!/usr/bin/env bash
set -euo pipefail

# Capture a small, portable cold/warm timing bundle for ComicPile production.
#
# Prerequisites:
#   - Vercel CLI authenticated for the ComicPile project
#   - Run from the repository root
#
# The output is intentionally limited to request timing and request IDs. It does
# not print environment variables, credentials, response bodies, or user data.

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
  } | tee -a "$OUT"

  # `vercel httpstat` is the project-supported timing probe. Keep stderr so CLI
  # failures are preserved in the evidence bundle instead of disappearing.
  vercel httpstat "$path" 2>&1 | tee -a "$OUT"
}

{
  printf 'ComicPile production startup timing capture\n'
  printf 'started_at=%s\n' "$STAMP"
  printf 'purpose=cold-vs-warm request timing without response-body or user-data capture\n'
} > "$OUT"

capture "potential cold root" "/"
capture "immediate warm root" "/"
capture "immediate warm OpenAPI" "/openapi.json"

printf '\nSaved timing bundle: %s\n' "$OUT"
