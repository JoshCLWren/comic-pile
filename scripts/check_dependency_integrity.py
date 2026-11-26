#!/usr/bin/env python3
"""Validate the pnpm workspace manifests and lockfile without network access.

This guard closes the validation gap behind issue #3494. CI installed from the
workspace-root ``pnpm-lock.yaml`` while a malformed nested
``frontend/pnpm-lock.yaml`` was never parsed by pnpm. The guard therefore
validates every manifest/lockfile pair that belongs to the workspace, not only
the file pnpm happens to read:

* conflict-marker-free, structurally valid root and workspace manifests;
* a parseable root ``pnpm-lock.yaml`` with an importer for every workspace;
* declared dependency ranges equal to the lockfile importer specifiers;
* a single pinned pnpm version in ``package.json`` and ``Dockerfile.ci``;
* no nested lockfiles inside workspace packages.

It is deliberately offline and dependency-free so it can run as a required
check on every CI event, including the factory-only fast path. ``--root`` makes
the exact PR head tree checkable in addition to the effective merge candidate.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

LOCKFILE = "pnpm-lock.yaml"
WORKSPACE_FILE = "pnpm-workspace.yaml"
ROOT_MANIFEST = "package.json"
PIN_DOCKERFILE = "Dockerfile.ci"
REQUIRED_WORKSPACE = "frontend"

DEPENDENCY_FIELDS = ("dependencies", "devDependencies", "optionalDependencies")
NESTED_LOCKFILES = (
    "pnpm-lock.yaml",
    "package-lock.json",
    "yarn.lock",
    "npm-shrinkwrap.json",
    "bun.lock",
    "bun.lockb",
)

START_MARKER = "<" * 7
MID_MARKER = "=" * 7
END_MARKER = ">" * 7

# pnpm 8/9 write lockfileVersion 6.0; pnpm 10 writes 9.0. A deliberate pnpm
# upgrade must update package.json, Dockerfile.ci and the lockfile together.
PNPM_LOCKFILE_VERSIONS = {8: "6.0", 9: "6.0", 10: "9.0"}

MAX_LOCKFILE_BYTES = 16 * 1024 * 1024
VERSION_RE = re.compile(r"^\d+\.\d+$")


@dataclass(frozen=True)
class Finding:
    """A dependency-integrity violation with a stable, grep-friendly location."""

    path: str
    message: str

    def render(self) -> str:
        """Render the finding for CI logs."""
        return f"{self.path}: {self.message}"


class DuplicateKeyError(ValueError):
    """Raised when a JSON manifest repeats an object key."""


def unquote(value: str) -> str:
    """Strip YAML single or double quotes from a scalar."""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        inner = value[1:-1]
        return inner.replace("''", "'") if value[0] == "'" else inner
    return value


def yaml_key(line: str, indent: int) -> str | None:
    """Return an unquoted YAML mapping key at an exact indentation."""
    if len(line) - len(line.lstrip(" ")) != indent:
        return None
    stripped = line[indent:]
    if not stripped.endswith(":"):
        return None
    return unquote(stripped[:-1])


def marker_findings(path: str, lines: list[str]) -> list[Finding]:
    """Report unresolved Git conflict markers, which are not valid input data."""
    findings: list[Finding] = []
    for number, line in enumerate(lines, start=1):
        stripped = line.rstrip("\r")
        if (
            stripped.startswith(START_MARKER)
            or stripped == MID_MARKER
            or stripped.startswith(END_MARKER)
        ):
            findings.append(
                Finding(f"{path}:{number}", "unresolved Git conflict marker in dependency file")
            )
    return findings


def read_text(root: Path, relative: str, findings: list[Finding]) -> str | None:
    """Read a required UTF-8 file, recording a finding when it is missing."""
    path = root / relative
    try:
        data = path.read_bytes()
    except OSError:
        findings.append(Finding(relative, "required dependency file is missing"))
        return None
    if len(data) > MAX_LOCKFILE_BYTES:
        findings.append(Finding(relative, "dependency file exceeds the bounded size limit"))
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        findings.append(Finding(relative, "dependency file is not valid UTF-8"))
        return None


def manifest_object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate manifest keys instead of silently keeping the last one."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(key)
        result[key] = value
    return result


def read_manifest(root: Path, relative: str, findings: list[Finding]) -> dict[str, object] | None:
    """Parse a package.json manifest strictly."""
    text = read_text(root, relative, findings)
    if text is None:
        return None
    try:
        manifest = json.loads(text, object_pairs_hook=manifest_object_pairs)
    except (json.JSONDecodeError, DuplicateKeyError) as error:
        findings.append(Finding(relative, f"invalid package.json: {error}"))
        return None
    if not isinstance(manifest, dict):
        findings.append(Finding(relative, "package.json must be a JSON object"))
        return None
    return manifest


def workspace_packages(root: Path, findings: list[Finding]) -> list[str]:
    """Resolve the pnpm workspace package directories from pnpm-workspace.yaml."""
    text = read_text(root, WORKSPACE_FILE, findings)
    if text is None:
        return []
    findings.extend(marker_findings(WORKSPACE_FILE, text.splitlines()))
    patterns: list[str] = []
    for raw in text.splitlines():
        match = re.match(r"^\s*-\s*['\"]?([^'\"#]+?)['\"]?\s*(?:#.*)?$", raw)
        if match:
            patterns.append(match.group(1).strip())
    if not patterns:
        findings.append(Finding(WORKSPACE_FILE, "no workspace package patterns declared"))
    directories: set[str] = set()
    for pattern in patterns:
        if pattern.startswith("/") or ".." in pattern.split("/"):
            findings.append(Finding(WORKSPACE_FILE, f"unsafe workspace pattern: {pattern}"))
            continue
        matches = [
            match
            for match in glob.glob(pattern, root_dir=root)
            if os.path.isdir(root / match)
        ]
        if not matches:
            findings.append(Finding(WORKSPACE_FILE, f"workspace pattern matched no directory: {pattern}"))
        directories.update(matches)
    if REQUIRED_WORKSPACE not in directories:
        findings.append(
            Finding(WORKSPACE_FILE, f"required workspace package is not declared: {REQUIRED_WORKSPACE}")
        )
    return sorted(directories)


def parse_lockfile(root: Path, findings: list[Finding]) -> dict[str, dict[str, dict[str, str]]]:
    """Parse the importer dependency ranges from the root pnpm lockfile."""
    text = read_text(root, LOCKFILE, findings)
    if text is None:
        return {}
    lines = text.splitlines()
    findings.extend(marker_findings(LOCKFILE, lines))

    version_value = None
    for line in lines:
        if line.startswith("lockfileVersion:"):
            version_value = unquote(line.split(":", 1)[1])
            break
    if version_value is None:
        findings.append(Finding(LOCKFILE, "missing lockfileVersion"))
    elif not VERSION_RE.fullmatch(version_value):
        findings.append(Finding(LOCKFILE, f"invalid lockfileVersion: {version_value}"))

    importers: dict[str, dict[str, dict[str, str]]] = {}
    in_importers = False
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            index += 1
            continue
        indent = len(line) - len(line.lstrip(" "))
        if "\t" in line[:indent]:
            findings.append(Finding(f"{LOCKFILE}:{index + 1}", "tab indentation is not valid YAML"))
        if indent == 0:
            key = yaml_key(line, 0)
            if key == "importers":
                in_importers = True
            elif in_importers:
                break
            index += 1
            continue
        if not in_importers:
            index += 1
            continue
        if indent != 2:
            findings.append(
                Finding(f"{LOCKFILE}:{index + 1}", "unexpected indentation in importers section")
            )
            index += 1
            continue

        importer = yaml_key(line, 2)
        if importer is None:
            findings.append(Finding(f"{LOCKFILE}:{index + 1}", "invalid importer key"))
            index += 1
            continue
        if importer in importers:
            findings.append(Finding(f"{LOCKFILE}:{index + 1}", f"duplicate importer: {importer}"))
        dependencies: dict[str, dict[str, str]] = {}
        importers[importer] = dependencies
        field: str | None = None
        package: str | None = None
        index += 1
        while index < len(lines):
            inner = lines[index]
            inner_stripped = inner.strip()
            if not inner_stripped or inner_stripped.startswith("#"):
                index += 1
                continue
            inner_indent = len(inner) - len(inner.lstrip(" "))
            if inner_indent <= 2:
                break
            if inner_indent == 4:
                candidate = yaml_key(inner, 4)
                if candidate in DEPENDENCY_FIELDS:
                    if candidate in dependencies:
                        findings.append(
                            Finding(f"{LOCKFILE}:{index + 1}", f"duplicate dependency field: {candidate}")
                        )
                    dependencies[candidate] = {}
                    field = candidate
                else:
                    field = None
                package = None
            elif inner_indent == 6 and field:
                candidate = yaml_key(inner, 6)
                if candidate is None:
                    findings.append(
                        Finding(f"{LOCKFILE}:{index + 1}", "invalid dependency key in importer")
                    )
                    package = None
                else:
                    if candidate in dependencies[field]:
                        findings.append(
                            Finding(f"{LOCKFILE}:{index + 1}", f"duplicate dependency: {candidate}")
                        )
                    dependencies[field][candidate] = {}
                    package = candidate
            elif inner_indent == 8 and field and package:
                candidate = yaml_key(inner, 8)
                if candidate == "specifier":
                    dependencies[field][package]["specifier"] = unquote(
                        inner.split(":", 1)[1]
                    )
            elif inner_indent not in (4, 6, 8):
                findings.append(
                    Finding(f"{LOCKFILE}:{index + 1}", "unexpected indentation in importer")
                )
            index += 1

    if not in_importers:
        findings.append(Finding(LOCKFILE, "missing importers section"))
    return importers


def check_pnpm_pin(root: Path, manifest: dict[str, object], findings: list[Finding]) -> None:
    """Require the same pinned pnpm version in the manifest and CI Dockerfile."""
    package_manager = manifest.get("packageManager")
    if not isinstance(package_manager, str) or not package_manager.startswith("pnpm@"):
        findings.append(Finding(ROOT_MANIFEST, "packageManager must pin pnpm@<version>"))
        return
    version = package_manager.split("@", 1)[1].split("+", 1)[0]
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        findings.append(Finding(ROOT_MANIFEST, f"invalid pinned pnpm version: {version}"))
        return
    dockerfile = read_text(root, PIN_DOCKERFILE, findings)
    if dockerfile is None:
        return
    if f"pnpm@{version}" not in dockerfile:
        findings.append(
            Finding(
                PIN_DOCKERFILE,
                f"pnpm pin does not match packageManager pin {version}",
            )
        )
    major = int(version.split(".", 1)[0])
    expected_lockfile_version = PNPM_LOCKFILE_VERSIONS.get(major)
    if expected_lockfile_version:
        lockfile = read_text(root, LOCKFILE, findings)
        if lockfile is not None:
            actual = next(
                (
                    unquote(line.split(":", 1)[1])
                    for line in lockfile.splitlines()
                    if line.startswith("lockfileVersion:")
                ),
                None,
            )
            if actual != expected_lockfile_version:
                findings.append(
                    Finding(
                        LOCKFILE,
                        f"lockfileVersion {actual} does not match pinned pnpm {version} "
                        f"(expected {expected_lockfile_version})",
                    )
                )


def check_consistency(
    root: Path,
    directories: list[str],
    importers: dict[str, dict[str, dict[str, str]]],
    findings: list[Finding],
) -> None:
    """Compare every workspace manifest with its lockfile importer ranges."""
    manifest_paths = {".": ROOT_MANIFEST}
    for directory in directories:
        manifest_paths[directory] = f"{directory}/{ROOT_MANIFEST}"
    for importer, manifest_path in manifest_paths.items():
        manifest = read_manifest(root, manifest_path, findings)
        if manifest is None:
            continue
        if importer not in importers:
            findings.append(Finding(LOCKFILE, f"no lockfile importer for workspace: {importer}"))
            continue
        locked_fields = importers[importer]
        for field in DEPENDENCY_FIELDS:
            declared = manifest.get(field, {})
            if not isinstance(declared, dict):
                findings.append(Finding(manifest_path, f"{field} must be a JSON object"))
                continue
            locked = locked_fields.get(field, {})
            for package, range_value in declared.items():
                if not isinstance(range_value, str):
                    findings.append(
                        Finding(manifest_path, f"{field}.{package} must be a version range string")
                    )
                    continue
                if package not in locked:
                    findings.append(
                        Finding(LOCKFILE, f"{importer} {field}.{package} missing from importer")
                    )
                elif locked[package].get("specifier") != range_value:
                    findings.append(
                        Finding(
                            LOCKFILE,
                            f"{importer} {field}.{package} specifier "
                            f"{locked[package].get('specifier')!r} != manifest {range_value!r}",
                        )
                    )
            for package in locked:
                if package not in declared:
                    findings.append(
                        Finding(LOCKFILE, f"{importer} {field}.{package} is not declared in manifest")
                    )


def validate(root: Path) -> list[Finding]:
    """Validate one candidate tree and return all dependency-integrity findings."""
    findings: list[Finding] = []
    root_manifest = read_manifest(root, ROOT_MANIFEST, findings)
    directories = workspace_packages(root, findings)
    for directory in directories:
        for name in NESTED_LOCKFILES:
            nested = f"{directory}/{name}"
            if (root / nested).is_file():
                findings.append(
                    Finding(nested, "nested lockfile in a pnpm workspace package is not installed")
                )
    importers = parse_lockfile(root, findings)
    if root_manifest is not None:
        check_pnpm_pin(root, root_manifest, findings)
    check_consistency(root, directories, importers, findings)
    return findings


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        default=".",
        help="Candidate repository tree to validate (default: current directory).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the dependency-integrity guard."""
    args = parse_args(argv)
    root = Path(args.root).resolve()
    findings = validate(root)
    if findings:
        print("Dependency integrity violations detected:", file=sys.stderr)
        for finding in findings:
            print(finding.render(), file=sys.stderr)
        print(f"{len(findings)} dependency integrity finding(s).", file=sys.stderr)
        return 1
    print(f"Dependency manifests and lockfile valid in {root}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
