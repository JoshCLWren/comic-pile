#!/usr/bin/env python3
from __future__ import annotations

import base64
import gzip
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    (
        "support.ts.gz.b64",
        "frontend/src/test/production-profile-real-user-support.ts",
        "cfcb2e9fdc0406c89d35ae3b2411ab2294d673b3e6445fa6854b2d4c5920b1d0",
    ),
    (
        "spec.ts.gz.b64",
        "frontend/src/test/production-profile-real-user.spec.ts",
        "2635e219ea3e6aec471bede2add0a2c0772e51fbf5719e89f143849ab7aaac5c",
    ),
    (
        "builder.py.gz.b64",
        "scripts/build_production_profile_manifest.py",
        "4a68f7cd2bb8458eef4f9faa8c98be678052bb7002de39165034e0864899c2cb",
    ),
    (
        "builder-test.py.gz.b64",
        "tests/test_build_production_profile_manifest.py",
        "8f6d7bc14df2d6474aa0f0c298b11f2a4fb492e9b9ec0ff5cdbb378fb5272b5a",
    ),
]

for payload_name, target_name, expected_sha256 in FILES:
    payload_path = Path(__file__).with_name(payload_name)
    target_path = ROOT / target_name
    decoded = gzip.decompress(base64.b64decode(payload_path.read_text().strip()))
    actual_sha256 = hashlib.sha256(decoded).hexdigest()
    if actual_sha256 != expected_sha256:
        raise SystemExit(
            f"{payload_name} checksum mismatch: expected {expected_sha256}, got {actual_sha256}"
        )
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(decoded)
    print(f"materialized {target_name} ({len(decoded)} bytes, sha256={actual_sha256})")
