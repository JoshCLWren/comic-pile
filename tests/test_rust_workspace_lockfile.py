"""Guard the unified Cargo workspace and single root lockfile for native Rust.

The deployed Vercel ingress and the native roll-service tests must resolve the
same locked dependency graph. These checks fail if a second lockfile, a nested
toolchain override, or a workflow that bypasses the workspace lock returns.
"""

from __future__ import annotations

import importlib
import tomllib

import pytest
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


def test_parity_tests_do_not_hardcode_nested_target_path() -> None:
    """Parity Python tests resolve example binaries through cargo_example_path."""
    parity_dir = REPOSITORY_ROOT / "native/roll-service/parity"
    stale_path = "native/roll-service/target"
    offenders = [
        path.relative_to(REPOSITORY_ROOT).as_posix()
        for path in parity_dir.glob("*.py")
        if stale_path in path.read_text(encoding="utf-8")
    ]
    assert not offenders, f"hardcoded stale target paths: {offenders}"


@pytest.mark.parametrize("target", ["target", "custom-target", "/tmp/absolute-target"])
def test_cargo_example_target_resolution(
    monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    """Relative overrides resolve from the workspace root; absolutes are preserved."""
    parity_dir = REPOSITORY_ROOT / "native" / "roll-service" / "parity"
    monkeypatch.syspath_prepend(str(parity_dir))
    route_harness = importlib.import_module("route_harness")

    monkeypatch.setenv("CARGO_TARGET_DIR", target)
    target_path = Path(target)
    if target_path.is_absolute():
        expected = target_path / "debug/examples/http_auth_login"
    else:
        expected = REPOSITORY_ROOT / target_path / "debug/examples/http_auth_login"
    assert route_harness.cargo_example_path("http_auth_login") == expected


def test_cargo_example_target_resolution_unset_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unset CARGO_TARGET_DIR defaults to the workspace-root target directory."""
    parity_dir = REPOSITORY_ROOT / "native" / "roll-service" / "parity"
    monkeypatch.syspath_prepend(str(parity_dir))
    route_harness = importlib.import_module("route_harness")

    monkeypatch.delenv("CARGO_TARGET_DIR", raising=False)
    assert route_harness.cargo_example_path("http_auth_login") == (
        REPOSITORY_ROOT / "target" / "debug/examples/http_auth_login"
    )


@pytest.mark.parametrize(
    ("module_name", "example"),
    [
        ("test_constraint_validation", "constraint_validation"),
        ("test_http_issue_read_rate", "http_issue_read_rate"),
    ],
)
@pytest.mark.parametrize("target", [None, "custom-target", "/tmp/absolute-target"])
def test_parity_runner_uses_workspace_target(
    monkeypatch: pytest.MonkeyPatch,
    module_name: str,
    example: str,
    target: str | None,
) -> None:
    """Actual parity entrypoints follow workspace defaults and target overrides."""
    import sys
    import uuid
    from importlib.util import module_from_spec, spec_from_file_location

    parity_dir = REPOSITORY_ROOT / "native/roll-service/parity"
    monkeypatch.syspath_prepend(str(parity_dir))
    monkeypatch.delenv("RUST_ROLL_ISSUE_READ_RATE_EXAMPLE", raising=False)
    if target is None:
        monkeypatch.delenv("CARGO_TARGET_DIR", raising=False)
    else:
        monkeypatch.setenv("CARGO_TARGET_DIR", target)

    module_path = parity_dir / f"{module_name}.py"
    isolated_name = f"{module_name}_isolated_{uuid.uuid4().hex}"
    spec = spec_from_file_location(isolated_name, module_path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    sys.modules[isolated_name] = module
    try:
        spec.loader.exec_module(module)
        target_path = Path(target or "target")
        if not target_path.is_absolute():
            target_path = REPOSITORY_ROOT / target_path
        assert module.RUNNER == target_path / "debug/examples" / example
    finally:
        sys.modules.pop(isolated_name, None)
