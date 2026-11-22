//! Capture the actual compiler, source revision and Cargo lock identity in the
//! native executable. Build scripts run at compile time only; toolchain or lock
//! failures abort the build without handling requests, so panicking accessors
//! cannot leak request data.
#![allow(clippy::unwrap_used, clippy::expect_used)]
use sha2::{Digest, Sha256};
use std::{env, fs, path::PathBuf, process::Command};

fn hex_lower(bytes: impl AsRef<[u8]>) -> String {
    bytes
        .as_ref()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

fn canonical_lock_sha256() -> String {
    let workspace_root = PathBuf::from(
        env::var("CARGO_MANIFEST_DIR").expect("Cargo supplies the workspace manifest directory"),
    );
    let lockfile = fs::read(workspace_root.join("Cargo.lock")).expect("read canonical Cargo.lock");
    hex_lower(Sha256::digest(lockfile))
}

fn main() {
    println!("cargo:rerun-if-env-changed=COMICPILE_BUILD_SHA");
    println!("cargo:rerun-if-env-changed=COMICPILE_EXPECTED_LOCK_SHA256");
    println!("cargo:rerun-if-env-changed=RUSTC");
    println!("cargo:rerun-if-changed=.git/HEAD");
    println!("cargo:rerun-if-changed=.git/refs/heads");
    println!("cargo:rerun-if-changed=Cargo.lock");
    let rustc = env::var_os("RUSTC").expect("Cargo supplies the compiler path");
    let compiler = Command::new(rustc)
        .arg("--version")
        .output()
        .expect("read actual compiler version");
    assert!(compiler.status.success(), "compiler identity unavailable");
    let compiler = String::from_utf8(compiler.stdout).expect("compiler version is UTF-8");
    println!("cargo:rustc-env=COMICPILE_COMPILER={}", compiler.trim());
    let revision = env::var("COMICPILE_BUILD_SHA").unwrap_or_else(|_| {
        Command::new("git")
            .args(["rev-parse", "HEAD"])
            .output()
            .ok()
            .filter(|output| output.status.success())
            .and_then(|output| String::from_utf8(output.stdout).ok())
            .unwrap_or_else(|| "unknown".to_owned())
    });
    let revision = revision.trim();
    assert!(
        revision == "unknown"
            || (revision.len() == 40 && revision.bytes().all(|byte| byte.is_ascii_hexdigit())),
        "build revision must be a complete commit SHA"
    );
    println!("cargo:rustc-env=COMICPILE_SOURCE_REVISION={revision}");

    let lock_sha256 = canonical_lock_sha256();
    if let Ok(expected) = env::var("COMICPILE_EXPECTED_LOCK_SHA256") {
        let expected = expected.trim();
        assert!(
            expected.len() == 64 && expected.bytes().all(|byte| byte.is_ascii_hexdigit()),
            "expected Cargo.lock SHA-256 must be one complete hexadecimal digest"
        );
        assert_eq!(
            expected, lock_sha256,
            "Cargo changed the canonical lockfile while resolving the production build"
        );
    }
    println!("cargo:rustc-env=COMICPILE_LOCK_SHA256={lock_sha256}");
}
