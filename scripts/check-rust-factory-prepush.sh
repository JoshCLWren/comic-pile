#!/usr/bin/env bash
# Rust pre-push gate. Mirrors the two native Rust CI entrypoints with no
# database-dependent tests, so a worker cannot push unformatted or
# uncompilable Rust and use GitHub Actions as its first compiler.
set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

command -v cargo >/dev/null || { echo "cargo is required for Rust pre-push checks" >&2; exit 1; }
command -v rustup >/dev/null || { echo "rustup is required for pinned Rust toolchains" >&2; exit 1; }

# Service crate: native/roll-service/rust-toolchain.toml tracks floating stable, matching rust-roll CI.
cargo +stable fmt --manifest-path native/roll-service/Cargo.toml -- --check
cargo +stable clippy --locked --manifest-path native/roll-service/Cargo.toml --all-targets -- -D warnings

# Native Vercel function: .github/workflows/native-vercel-rust.yml uses stable.
# Checking the root binary also resolves and type-checks the service dependency
# through the actual production entrypoints, not a substitute example crate.
cargo +stable fmt -- --check
cargo +stable check --locked --all-targets
