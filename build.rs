//! Capture the actual compiler and source revision in the native executable.
use std::{env, process::Command};

fn main() {
    println!("cargo:rerun-if-env-changed=COMICPILE_BUILD_SHA");
    println!("cargo:rerun-if-env-changed=RUSTC");
    println!("cargo:rerun-if-changed=.git/HEAD");
    println!("cargo:rerun-if-changed=.git/refs/heads");
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
}
