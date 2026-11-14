"""Guard the unified Cargo workspace and single root lockfile for native Rust.

The deployed Vercel ingress and the native roll-service tests must resolve the
same locked dependency graph. These checks fail if a second lockfile, a nested
toolchain override, or a workflow that bypasses the workspace lock returns.
"""

from __future__ import annotations

import tomllib
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _toml(path: Path) -> dict:
    """Return a parsed TOML document.

    Args:
        path: TOML file to read.

    Returns:
        Parsed top-level table.
    """
    return tomllib.loads(path.read_text(encoding="utf-8"))


def test_root_manifest_defines_workspace_with_service_member() -> None:
    """The root package and the service resolve through one workspace."""
    manifest = _toml(REPOSITORY_ROOT / "Cargo.toml")
    workspace = manifest["workspace"]
    assert isinstance(workspace, dict)
    assert "native/roll-service" in workspace["members"]
    assert workspace["resolver"] == "2"

    bins = {entry["name"]: entry["path"] for entry in manifest["bin"]}
    assert bins["native_roll"] == "api/native_roll.rs"
    assert bins["native_issue"] == "api/native_issue.rs"


def test_single_root_lockfile_covers_both_packages() -> None:
    """Only the root lockfile exists and it pins the service package."""
    root_lock = REPOSITORY_ROOT / "Cargo.lock"
    assert root_lock.is_file()
    assert not (REPOSITORY_ROOT / "native/roll-service/Cargo.lock").exists()

    lock = root_lock.read_text(encoding="utf-8")
    assert 'name = "comicpile-vercel-native"' in lock
    assert 'name = "comicpile-roll-service"' in lock


def test_root_toolchain_metadata_replaces_nested_copy() -> None:
    """One floating-stable toolchain file covers both native packages."""
    toolchain_path = REPOSITORY_ROOT / "rust-toolchain.toml"
    assert toolchain_path.is_file()
    assert not (REPOSITORY_ROOT / "native/roll-service/rust-toolchain.toml").exists()

    toolchain = _toml(toolchain_path)["toolchain"]
    assert isinstance(toolchain, dict)
    assert toolchain["channel"] == "stable"
    assert set(toolchain["components"]) >= {"rustfmt", "clippy"}


def test_rust_ci_and_prepush_lock_the_shared_workspace() -> None:
    """CI jobs and the factory gate invoke the workspace through the root lock."""
    rust_roll = (REPOSITORY_ROOT / ".github/workflows/rust-roll.yml").read_text(
        encoding="utf-8"
    )
    native_vercel = (
        REPOSITORY_ROOT / ".github/workflows/native-vercel-rust.yml"
    ).read_text(encoding="utf-8")
    prepush = (REPOSITORY_ROOT / "scripts/check-rust-factory-prepush.sh").read_text(
        encoding="utf-8"
    )
    e2e = (
        REPOSITORY_ROOT / ".github/workflows/e2e-chromium-regression.yml"
    ).read_text(encoding="utf-8")
    audit = (REPOSITORY_ROOT / "native/roll-service/Dockerfile.audit").read_text(
        encoding="utf-8"
    )

    for source in (rust_roll, native_vercel, prepush, e2e, audit):
        assert "native/roll-service/Cargo.lock" not in source
        assert "--locked" in source

    assert "cargo test --workspace --locked --all-targets" in rust_roll
    assert "cargo clippy --workspace --locked --all-targets" in rust_roll
    assert "cargo test --locked -p comicpile-vercel-native --all-targets" in native_vercel
    assert "cargo +stable clippy --workspace --locked --all-targets" in prepush
    assert "cargo build --release --locked -p comicpile-roll-service" in e2e
    assert "cargo build --locked -p comicpile-roll-service" in audit
