#!/usr/bin/env python3
from __future__ import annotations

import base64
import gzip
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = Path(__file__).with_name("spec.ts.gz.b64")
TARGET = ROOT / "frontend/src/test/production-profile-real-user.spec.ts"
EXPECTED_SHA256 = "060ad0a06efc51a69b61499c2b3e28df8b294ce32f9caa7b40ee73615e3084dc"

source = gzip.decompress(base64.b64decode(PAYLOAD.read_text().strip()))
actual_sha256 = hashlib.sha256(source).hexdigest()
if actual_sha256 != EXPECTED_SHA256:
    raise SystemExit(
        f"UI-driven profile checksum mismatch: expected {EXPECTED_SHA256}, got {actual_sha256}"
    )
TARGET.write_bytes(source)
print(f"materialized {TARGET.relative_to(ROOT)} ({len(source)} bytes, sha256={actual_sha256})")
