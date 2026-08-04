"""Regression tests for the deterministic OpenAPI TypeScript generator wrapper."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts import generate_openapi_types


def test_generator_command_pins_maintained_package() -> None:
    """Build an exact command without relying on ambient package versions."""
    command = generate_openapi_types.generator_command(
        Path("schema.json"),
        Path("types.ts"),
    )

    assert command == [
        "pnpm",
        "dlx",
        "openapi-typescript@7.10.1",
        "schema.json",
        "--output",
        "types.ts",
    ]


def test_generate_types_creates_parent_and_checks_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Create the generated directory and require a successful generator exit."""
    calls: list[tuple[list[str], bool]] = []

    def fake_run(command: list[str], *, check: bool) -> None:
        calls.append((command, check))

    monkeypatch.setattr(subprocess, "run", fake_run)
    output = tmp_path / "generated" / "openapi.ts"

    generate_openapi_types.generate_types(Path("openapi.json"), output)

    assert output.parent.is_dir()
    assert calls == [
        (
            [
                "pnpm",
                "dlx",
                "openapi-typescript@7.10.1",
                "openapi.json",
                "--output",
                str(output),
            ],
            True,
        )
    ]


def test_outputs_match_requires_identical_checked_in_bytes(tmp_path: Path) -> None:
    """Reject missing or stale generated TypeScript artifacts."""
    expected = tmp_path / "openapi.ts"
    generated = tmp_path / "fresh.ts"
    generated.write_text("export interface paths {}\n", encoding="utf-8")

    assert not generate_openapi_types.outputs_match(expected, generated)

    expected.write_text("export interface paths {}\n", encoding="utf-8")
    assert generate_openapi_types.outputs_match(expected, generated)

    expected.write_text("export interface paths { stale: true }\n", encoding="utf-8")
    assert not generate_openapi_types.outputs_match(expected, generated)


def test_main_generates_default_schema_and_types(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Refresh the schema before generating the checked-in TypeScript artifact."""
    recorded: list[tuple[list[str], bool]] = []

    def fake_run(command: list[str], *, check: bool) -> None:
        recorded.append((command, check))

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(
        generate_openapi_types,
        "_parse_args",
        lambda: type(
            "Args",
            (),
            {
                "schema": generate_openapi_types.SCHEMA_OUTPUT,
                "output": generate_openapi_types.TYPES_OUTPUT,
                "check": False,
            },
        )(),
    )

    assert generate_openapi_types.main() == 0
    assert recorded == [
        (
            [
                generate_openapi_types.sys.executable,
                "scripts/export_openapi_schema.py",
            ],
            True,
        ),
        (
            generate_openapi_types.generator_command(
                generate_openapi_types.SCHEMA_OUTPUT,
                generate_openapi_types.TYPES_OUTPUT,
            ),
            True,
        ),
    ]
    assert "openapi-typescript@7.10.1" in capsys.readouterr().out


def test_main_check_rejects_stale_types_without_rewriting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Generate into a temporary file and fail when checked-in types differ."""
    schema = tmp_path / "openapi.json"
    output = tmp_path / "openapi.ts"
    schema.write_text("{}\n", encoding="utf-8")
    output.write_text("stale\n", encoding="utf-8")

    def fake_generate_types(_schema: Path, generated: Path) -> None:
        generated.write_text("fresh\n", encoding="utf-8")

    monkeypatch.setattr(generate_openapi_types, "generate_types", fake_generate_types)
    monkeypatch.setattr(
        generate_openapi_types,
        "_parse_args",
        lambda: type(
            "Args",
            (),
            {"schema": schema, "output": output, "check": True},
        )(),
    )

    assert generate_openapi_types.main() == 1
    assert output.read_text(encoding="utf-8") == "stale\n"
    assert "are stale" in capsys.readouterr().out


def test_main_check_accepts_current_types(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Accept byte-identical output generated with the pinned tool."""
    schema = tmp_path / "openapi.json"
    output = tmp_path / "openapi.ts"
    schema.write_text("{}\n", encoding="utf-8")
    output.write_text("current\n", encoding="utf-8")

    def fake_generate_types(_schema: Path, generated: Path) -> None:
        generated.write_text("current\n", encoding="utf-8")

    monkeypatch.setattr(generate_openapi_types, "generate_types", fake_generate_types)
    monkeypatch.setattr(
        generate_openapi_types,
        "_parse_args",
        lambda: type(
            "Args",
            (),
            {"schema": schema, "output": output, "check": True},
        )(),
    )

    assert generate_openapi_types.main() == 0
