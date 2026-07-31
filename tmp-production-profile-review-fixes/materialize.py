#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
import io
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = Path(__file__).with_name("review-fixes.tar.gz.b64")
EXPECTED = {
    "frontend/src/test/production-profile-real-user-support.ts": "d5fdd1663763eafbd70dc72045a3f2877058770974a81f99a272745ad5e385ad",
    "frontend/src/test/production-profile-real-user.spec.ts": "55aaba7c7760f03db42bfc8f9a4efca9706ca0f8c85b213b0894c8106daa8c4a",
    "frontend/playwright.prod-profile.config.ts": "deeb82029e34f26e2307db00727dc1595e3fb6901d8faff847975aaf9474d5e7",
    "scripts/build_production_profile_manifest.py": "f1ad1b735f12655419dabf20d8646825a56d5b9e29fe1024c54a9bfab5d4c5da",
    "tests/test_build_production_profile_manifest.py": "a83a33530d5d2696e6287b489c678eea393b7ad7915abe9889975deaa2ddab78",
    "frontend/src/test/fixtures/production-profile-workload.json": "f0c0f604d0e9f5d761b506a647ab1fb4abdba3c60b46920238f98733c875c497",
    "frontend/src/test/fixtures/production-profile-workload.actions.json": "2042df57898628e823cdccecd261b1c5b800338a584c140d083522e33dbdd937",
    "frontend/src/test/fixtures/production-profile-workload.routes.json": "7959ad06c385195364c4a9e778bdfc98d2a70e35666bc71657e7ddb5be899880",
}

archive_bytes = base64.b64decode(BUNDLE.read_text().strip())
with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as archive:
    members = {member.name: member for member in archive.getmembers()}
    if set(members) != set(EXPECTED):
        raise SystemExit(
            f"Bundle file set mismatch: expected {sorted(EXPECTED)}, found {sorted(members)}"
        )
    for relative_path, expected_sha256 in EXPECTED.items():
        member = members[relative_path]
        if not member.isfile():
            raise SystemExit(f"Bundle member is not a regular file: {relative_path}")
        source = archive.extractfile(member)
        if source is None:
            raise SystemExit(f"Could not read bundle member: {relative_path}")
        data = source.read()
        actual_sha256 = hashlib.sha256(data).hexdigest()
        if actual_sha256 != expected_sha256:
            raise SystemExit(
                f"{relative_path} checksum mismatch: expected {expected_sha256}, got {actual_sha256}"
            )
        target = ROOT / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        print(f"materialized {relative_path} ({len(data)} bytes, sha256={actual_sha256})")
