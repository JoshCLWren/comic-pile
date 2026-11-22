#!/usr/bin/env bash
# Production Vercel Rust build guard for the unified Cargo workspace.
#
# Invoked by @vercel/rust without any vercel.json config: packages/rust/src/index.ts
# calls runUserScripts(workPath) -> @vercel/build-utils runShellScript("build.sh")
# before compileCargoBinary, once per native function declared under "builds".
# Verified against @vercel/rust source on 2026-11-17 (no external build-command
# setting is required). build.sh and check-rust-workspace-lock.mjs are committed
# at the repo root and are not excluded by .vercelignore.
#
# The script proves that the root ingress package and the roll-service member
# resolve one locked graph, then compiles both Vercel binaries through the root
# Cargo.lock. COMICPILE_EXPECTED_LOCK_SHA256 makes the build script fail if
# Cargo mutates the lockfile while resolving the production binaries.
set -Eeuo pipefail

readonly workspace_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$workspace_root"

command -v cargo >/dev/null || {
  echo "cargo is required for the Vercel Rust workspace build" >&2
  exit 1
}
command -v node >/dev/null || {
  echo "node is required for the Vercel Rust workspace lock check" >&2
  exit 1
}

printf '%s\n' "Production Rust toolchain:"
cargo --version
rustc --version --verbose

lock_sha256="$(node check-rust-workspace-lock.mjs --lock-sha256)"
readonly lock_sha256
export COMICPILE_EXPECTED_LOCK_SHA256="$lock_sha256"
printf 'Canonical Cargo.lock SHA-256: %s\n' "$lock_sha256"

cargo build --release --locked --package comicpile-vercel-native --bins
