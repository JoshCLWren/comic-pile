#!/usr/bin/env bash
# Rust pre-push gate. Mirrors the two native Rust CI entrypoints with no
# database-dependent tests, so a worker cannot push unformatted or
# uncompilable Rust and use GitHub Actions as its first compiler.
set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

command -v cargo >/dev/null || { echo "cargo is required for Rust pre-push checks" >&2; exit 1; }
command -v rustup >/dev/null || { echo "rustup is required for pinned Rust toolchains" >&2; exit 1; }

# Service crate: native/roll-service/rust-toolchain.toml pins 1.85.0.
cargo +1.85.0 fmt --manifest-path native/roll-service/Cargo.toml --all --check
cargo +1.85.0 clippy --locked --manifest-path native/roll-service/Cargo.toml --all-targets -- -D warnings

# Native Vercel function: .github/workflows/native-vercel-rust.yml uses stable.
# Checking the root binary also resolves and type-checks the service dependency
# through the actual production entrypoints, not a substitute example crate.
cargo +stable fmt --manifest-path Cargo.toml -- --check
cargo +stable check --locked --manifest-path Cargo.toml --all-targets
