#!/usr/bin/env bash
set -Eeuo pipefail

setup_file="$(npm root -g)/omniroute/bin/cli/commands/setup.mjs"
[[ -f "$setup_file" ]] || { echo "OmniRoute setup module not found" >&2; exit 1; }

grep -Fq 'let apiKey = opts.apiKey;' "$setup_file" || {
  echo "Unexpected OmniRoute setup implementation; refusing to patch" >&2
  exit 1
}

sed -i 's/let apiKey = opts\.apiKey;/let apiKey = opts.apiKey || process.env.OMNIROUTE_API_KEY;/' "$setup_file"
grep -Fq 'let apiKey = opts.apiKey || process.env.OMNIROUTE_API_KEY;' "$setup_file"
