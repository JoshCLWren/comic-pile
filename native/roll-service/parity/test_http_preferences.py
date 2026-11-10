"""Native same-path preferences and Taste Bank signals against PostgreSQL.

The Rust handlers replace the Python handlers at the exact same
method/path pairs (#4834):

* ``GET /api/v1/users/me/preferences``
* ``PATCH /api/v1/users/me/preferences``
* ``GET /api/v1/users/me/taste-signals``
* ``PUT /api/v1/users/me/taste-signals/{signal_type}/{external_key}/verdict``

This test seeds the canonical application schema with an owner and a
foreign owner, then checks the native responses directly: the ``classic``
default, theme persistence and atomic upsert behaviour, empty-PATCH
seeding, 422 validation, unauthenticated rejection, canonical signal
ordering, verdict creation/idempotence, inferred-column preservation and
owner isolation. Handler statement counters are asserted as bounded
constants (one read per GET, one atomic upsert per write, insert-plus-read
only for empty-PATCH seeding); no per-row fan-out exists.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models import TasteSignal, User

SECRET = "synthetic-native-preferences-secret"
# CI builds into native/roll-service/target; the managed local wrapper keeps
# its own bounded target directory, so locate the built example without
# changing how this test builds or runs anything.
EXAMPLE = (
    Path(os.environ.get("CARGO_TARGET_DIR", "native/roll-service/target"))
    / "debug/examples/http_preferences"
)

PREFERENCES_URI = "/api/v1/users/me/preferences"
SIGNALS_URI = "/api/v1/users/me/taste-signals"
# The frontend `encodeURIComponent`s the external key, so the colon arrives
# percent-encoded and the handler must decode it back to the stored key.
VERDICT_URI = (
    "/api/v1/users/me/taste-signals/creator/creator%3Awriter%3Adk/verdict"
)


def _token(username: str, *, jti: str) -> str:
    return jwt.encode(
        {
            "sub": username,
            "jti": jti,
            "type": "access",
            "exp": 4_102_444_800,
        },
        SECRET,
        algorithm="HS256",
    )


async def _run_example(env: dict[str, str]) -> dict[str, object]:
    proc = await asyncio.create_subprocess_exec(
        str(EXAMPLE),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await asyncio.wait_for(proc.communicate(), 30)
    assert proc.returncode == 0, err.decode()
    if err:
        print(err.decode(), flush=True)
    return json.loads(out)


def _env(
    url: str,
    *,
    token: str = "",
    method: str = "GET",
    uri: str = PREFERENCES_URI,
    body: dict[str, object] | None = None,
) -> dict[str, str]:
    env = {
        **os.environ,
        "RUST_ROLL_DATABASE_URL": url,
        "RUST_ROLL_JWT_SECRET": SECRET,
        "RUST_ROLL_POOL_SIZE": "2",
        "RUST_ROLL_TEST_TOKEN": token,
        "RUST_ROLL_TEST_METHOD": method,
        "RUST_ROLL_TEST_URI": uri,
    }
    if body is not None:
        env["RUST_ROLL_TEST_BODY"] = json.dumps(body)
    return env


@pytest.mark.asyncio
async def test_native_preferences_preserve_the_python_contract() -> None:
    """Default, persistence, seeding, validation and owner isolation."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        owner_name = f"prefs_{uuid4().hex[:12]}"
        stranger_name = f"stranger_{uuid4().hex[:12]}"
        token = _token(owner_name, jti=f"jti-{uuid4().hex}")
        stranger_token = _token(stranger_name, jti=f"jti-{uuid4().hex}")
        now = datetime.now(UTC)

        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=owner_name, created_at=now)
            stranger = User(username=stranger_name, created_at=now)
            db.add_all([owner, stranger])
            await db.flush()
            owner_id = owner.id
            # The example subprocess uses its own connection, so the seeded
            # users must be committed before any request can find them.
            await db.commit()

            # Unauthenticated requests are rejected before any handler SQL.
            unauthenticated = await _run_example(_env(url))
            assert unauthenticated["status"] == 401, unauthenticated
            assert unauthenticated["preferences_statements"] == 0

            # No preference row yet: the default resolves without a write.
            default = await _run_example(_env(url, token=token))
            assert default["status"] == 200, default
            assert default["body"] == {"theme": "classic", "user_id": owner_id}
            assert default["preferences_statements"] == 1

            # A theme write creates the row through one atomic upsert.
            created = await _run_example(
                _env(url, token=token, method="PATCH", body={"theme": "ink-gold"})
            )
            assert created["status"] == 200, created
            assert created["body"] == {"theme": "ink-gold", "user_id": owner_id}
            assert created["preferences_statements"] == 1

            # The persisted theme is readable and a later write updates it.
            persisted = await _run_example(_env(url, token=token))
            assert persisted["body"]["theme"] == "ink-gold"
            updated = await _run_example(
                _env(
                    url,
                    token=token,
                    method="PATCH",
                    body={"theme": "command-center"},
                )
            )
            assert updated["status"] == 200
            assert updated["body"]["theme"] == "command-center"

            # An explicit null theme is a no-op for an existing row.
            noop = await _run_example(
                _env(url, token=token, method="PATCH", body={"theme": None})
            )
            assert noop["status"] == 200
            assert noop["body"]["theme"] == "command-center"

            # An unknown theme is a 422 and issues no handler statement.
            invalid = await _run_example(
                _env(url, token=token, method="PATCH", body={"theme": "neon-pink"})
            )
            assert invalid["status"] == 422, invalid
            assert invalid["preferences_statements"] == 0

            # An empty PATCH seeds a missing row with the default, then an
            # explicit null leaves that seeded row alone.
            stranger_seeded = await _run_example(
                _env(url, token=stranger_token, method="PATCH", body={})
            )
            assert stranger_seeded["status"] == 200, stranger_seeded
            assert stranger_seeded["body"]["theme"] == "classic"
            assert stranger_seeded["preferences_statements"] == 2
            stranger_noop = await _run_example(
                _env(
                    url,
                    token=stranger_token,
                    method="PATCH",
                    body={"theme": None},
                )
            )
            assert stranger_noop["body"]["theme"] == "classic"
            assert stranger_noop["body"]["user_id"] != owner_id

            # Every supported theme is accepted through the same contract.
            for theme in ("classic", "ink-gold", "command-center"):
                response = await _run_example(
                    _env(url, token=token, method="PATCH", body={"theme": theme})
                )
                assert response["status"] == 200, response
                assert response["body"]["theme"] == theme
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_native_taste_signals_preserve_the_python_contract() -> None:
    """Verdict upserts, idempotence, ordering and inferred preservation."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        owner_name = f"taste_{uuid4().hex[:12]}"
        stranger_name = f"stranger_{uuid4().hex[:12]}"
        token = _token(owner_name, jti=f"jti-{uuid4().hex}")
        stranger_token = _token(stranger_name, jti=f"jti-{uuid4().hex}")
        now = datetime.now(UTC)

        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=owner_name, created_at=now)
            stranger = User(username=stranger_name, created_at=now)
            db.add_all([owner, stranger])
            await db.flush()
            owner_id = owner.id
            # The example subprocess uses its own connection, so the seeded
            # users must be committed before any request can find them.
            await db.commit()

            # Unauthenticated list and verdict requests are rejected.
            unauthenticated_list = await _run_example(_env(url, uri=SIGNALS_URI))
            assert unauthenticated_list["status"] == 401
            unauthenticated_verdict = await _run_example(
                _env(url, method="PUT", uri=VERDICT_URI, body={"verdict": "confirmed"})
            )
            assert unauthenticated_verdict["status"] == 401

            # The list is empty before any discovery or verdict exists.
            empty = await _run_example(_env(url, token=token, uri=SIGNALS_URI))
            assert empty["status"] == 200, empty
            assert empty["body"] == {"signals": []}
            assert empty["taste_statements"] == 1

            # A verdict on an unknown key creates the canonical row through
            # one atomic upsert; the percent-encoded key is decoded.
            created = await _run_example(
                _env(
                    url,
                    token=token,
                    method="PUT",
                    uri=VERDICT_URI,
                    body={"verdict": "confirmed"},
                )
            )
            assert created["status"] == 200, created
            body = created["body"]
            assert created["taste_statements"] == 1
            assert body["user_id"] == owner_id
            assert body["signal_type"] == "creator"
            assert body["external_key"] == "creator:writer:dk"
            assert body["display_name"] == "dk"
            assert body["user_verdict"] == "confirmed"
            assert body["affinity_estimate"] is None
            assert body["confidence"] is None
            assert body["evidence_count"] == 0
            assert body["distinct_thread_count"] == 0
            assert body["verdict_at"] is not None
            assert body["first_observed_at"] is not None
            assert body["last_observed_at"] is not None
            assert body["last_prompted_at"] is None

            # Repeating the same verdict is idempotent: still one row.
            repeated = await _run_example(
                _env(
                    url,
                    token=token,
                    method="PUT",
                    uri=VERDICT_URI,
                    body={"verdict": "confirmed"},
                )
            )
            assert repeated["status"] == 200
            assert repeated["body"]["user_verdict"] == "confirmed"
            listed = await _run_example(_env(url, token=token, uri=SIGNALS_URI))
            assert len(listed["body"]["signals"]) == 1

            # A changed verdict overwrites only the verdict columns, and a
            # seeded inferred row keeps its evidence across the write.
            seeded = TasteSignal(
                user_id=owner_id,
                signal_type="team",
                external_key="team:xmen",
                display_name="X-Men",
                affinity_estimate=-0.6,
                confidence=0.7,
                evidence_count=9,
                distinct_thread_count=4,
                first_observed_at=now,
                last_observed_at=now,
            )
            db.add(seeded)
            await db.flush()
            await db.commit()
            changed = await _run_example(
                _env(
                    url,
                    token=token,
                    method="PUT",
                    uri="/api/v1/users/me/taste-signals/team/team%3Axmen/verdict",
                    body={"verdict": "rejected"},
                )
            )
            assert changed["status"] == 200, changed
            assert changed["body"]["user_verdict"] == "rejected"
            assert changed["body"]["affinity_estimate"] == -0.6
            assert changed["body"]["confidence"] == pytest.approx(0.7)
            assert changed["body"]["evidence_count"] == 9
            assert changed["body"]["distinct_thread_count"] == 4
            assert changed["body"]["display_name"] == "X-Men"

            # The list is ordered by signal type, then external key, and a
            # foreign owner's verdicts never appear in it.
            ordered = await _run_example(_env(url, token=token, uri=SIGNALS_URI))
            keys = [
                (item["signal_type"], item["external_key"])
                for item in ordered["body"]["signals"]
            ]
            assert keys == sorted(keys)
            assert len(keys) == 2
            stranger_list = await _run_example(
                _env(url, token=stranger_token, uri=SIGNALS_URI)
            )
            assert stranger_list["body"] == {"signals": []}

            # Validation mirrors the Python literals and issues no SQL.
            for uri, payload in (
                (
                    "/api/v1/users/me/taste-signals/color/red/verdict",
                    {"verdict": "confirmed"},
                ),
                (VERDICT_URI, {"verdict": "love-it"}),
                (VERDICT_URI, {}),
            ):
                rejected = await _run_example(
                    _env(url, token=token, method="PUT", uri=uri, body=payload)
                )
                assert rejected["status"] == 422, rejected
                assert rejected["taste_statements"] == 0
    finally:
        await engine.dispose()
