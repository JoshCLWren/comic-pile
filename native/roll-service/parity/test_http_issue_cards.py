"""Authenticated native Issue card POST against the canonical app schema.

The mounted Rust route runs on a disposable schema created from the canonical
SQLAlchemy models. The projection must return exact owned card state, confirmed
mapping metadata and the exact stored provider CDN URL, with no per-card
provider call and no foreign-user data. Field shape and request ordering are
asserted directly because this is a new Rust product contract, not a
language-only port of an existing Python operation.
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from jose import jwt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.database import Base
from app.models import Event, Issue, Thread, User
from app.models.external_identity import (
    ExternalIdentity,
    IssueExternalIdentityMapping,
)

SECRET = "synthetic-native-issue-card-secret"


def _iso_ms(value: datetime) -> str:
    """Render the native projection's fixed UTC millisecond timestamp."""
    utc = value.astimezone(UTC)
    return utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{utc.microsecond // 1000:03d}Z"


async def _run_example(env: dict[str, str]) -> dict[str, object]:
    proc = await asyncio.create_subprocess_exec(
        "native/roll-service/target/debug/examples/http_issue_cards",
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await asyncio.wait_for(proc.communicate(), 25)
    assert proc.returncode == 0, err.decode()
    return json.loads(out)


@pytest.mark.asyncio
async def test_authenticated_issue_cards_are_owner_scoped_and_bounded() -> None:
    """Return exact owned cards, confirmed URLs, and omit foreign or duplicate IDs."""
    url = os.environ["RUST_ROLL_TEST_DATABASE_URL"]
    name = f"rust_issue_cards_{uuid4().hex}"
    admin = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    async with admin.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{name}"'))
    engine = create_async_engine(
        url.replace("postgresql://", "postgresql+asyncpg://"),
        connect_args={"server_settings": {"search_path": f"{name},public"}},
    )
    try:
        async with engine.begin() as connection:
            # The schema is new, so skip public-schema table collisions while
            # keeping public on the path for the pg_trgm operator class.
            await connection.run_sync(
                lambda sync_connection: Base.metadata.create_all(
                    sync_connection, checkfirst=False
                )
            )

        now = datetime.now(UTC)
        read_at = datetime(2026, 1, 2, 3, 4, 5, 123456, tzinfo=UTC)
        username = f"cards_{uuid4().hex[:16]}"
        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=username)
            stranger = User(username=f"other_{uuid4().hex[:16]}")
            db.add_all([owner, stranger])
            await db.flush()

            hellboy = Thread(
                user_id=owner.id,
                title="Hellboy in Hell",
                format="Comic",
                queue_position=1,
                issues_remaining=2,
                total_issues=3,
            )
            bprd = Thread(
                user_id=owner.id,
                title="B.P.R.D.",
                format="Comic",
                queue_position=2,
                issues_remaining=1,
                total_issues=1,
            )
            foreign_thread = Thread(
                user_id=stranger.id,
                title="Private run",
                format="Comic",
                queue_position=1,
                issues_remaining=1,
                total_issues=1,
            )
            db.add_all([hellboy, bprd, foreign_thread])
            await db.flush()

            issues = {
                "one": Issue(
                    thread_id=hellboy.id,
                    issue_number="1",
                    position=1,
                    status="unread",
                ),
                "two": Issue(
                    thread_id=hellboy.id,
                    issue_number="2",
                    position=2,
                    status="unread",
                ),
                "ten": Issue(
                    thread_id=hellboy.id,
                    issue_number="10",
                    position=10,
                    status="read",
                    read_at=read_at,
                ),
                "bprd": Issue(
                    thread_id=bprd.id,
                    issue_number="1",
                    position=1,
                    status="unread",
                ),
                "foreign": Issue(
                    thread_id=foreign_thread.id,
                    issue_number="1",
                    position=1,
                    status="unread",
                ),
            }
            db.add_all(issues.values())
            await db.flush()
            hellboy.next_unread_issue_id = issues["one"].id
            bprd.next_unread_issue_id = issues["bprd"].id
            foreign_thread.next_unread_issue_id = issues["foreign"].id

            identities = {
                "ten": ExternalIdentity(
                    provider="comicvine",
                    entity_type="issue",
                    external_id="4000-42",
                    metadata_json={
                        "image": {
                            "medium_url": "https://comicvine.example/medium/4000-42.jpg",
                            "original_url": "https://comicvine.example/original/4000-42.jpg",
                        }
                    },
                ),
                "two": ExternalIdentity(
                    provider="comicvine",
                    entity_type="issue",
                    external_id="4000-43",
                    metadata_json={
                        "image": {"medium_url": "https://comicvine.example/medium/4000-43.jpg"}
                    },
                ),
                "one": ExternalIdentity(
                    provider="comicvine",
                    entity_type="issue",
                    external_id="4000-44",
                    metadata_json={
                        "image": {"medium_url": "https://comicvine.example/medium/4000-44.jpg"}
                    },
                ),
                "bprd": ExternalIdentity(
                    provider="comicvine",
                    entity_type="issue",
                    external_id="4000-45",
                    metadata_json={
                        "image": {"original_url": "https://comicvine.example/original/4000-45.jpg"}
                    },
                ),
                "foreign": ExternalIdentity(
                    provider="comicvine",
                    entity_type="issue",
                    external_id="4000-46",
                    metadata_json={
                        "image": {"medium_url": "https://comicvine.example/medium/4000-46.jpg"}
                    },
                ),
            }
            db.add_all(identities.values())
            await db.flush()
            db.add_all(
                [
                    IssueExternalIdentityMapping(
                        issue_id=issues["ten"].id,
                        external_identity_id=identities["ten"].id,
                        status="confirmed",
                        confidence=0.9,
                    ),
                    IssueExternalIdentityMapping(
                        issue_id=issues["two"].id,
                        external_identity_id=identities["two"].id,
                        status="candidate",
                        confidence=0.7,
                    ),
                    IssueExternalIdentityMapping(
                        issue_id=issues["one"].id,
                        external_identity_id=identities["one"].id,
                        status="rejected",
                    ),
                    IssueExternalIdentityMapping(
                        issue_id=issues["bprd"].id,
                        external_identity_id=identities["bprd"].id,
                        status="confirmed",
                        confidence=0.8,
                    ),
                    IssueExternalIdentityMapping(
                        issue_id=issues["foreign"].id,
                        external_identity_id=identities["foreign"].id,
                        status="confirmed",
                        confidence=0.95,
                    ),
                    Event(
                        type="rate",
                        timestamp=now - timedelta(days=1),
                        user_id=owner.id,
                        thread_id=hellboy.id,
                        issue_id=issues["ten"].id,
                        issue_number="10",
                        rating=4.5,
                        issues_read=1,
                    ),
                ]
            )
            await db.commit()
            issue_ids = {key: issue.id for key, issue in issues.items()}

        expected = {
            "items": [
                {
                    "issue_id": issue_ids["ten"],
                    "thread_id": hellboy.id,
                    "thread_title": "Hellboy in Hell",
                    "issue_number": "10",
                    "status": "read",
                    "read_at": _iso_ms(read_at),
                    "rating": 4.5,
                    "has_confirmed_identity": True,
                    "mapping_state": "confirmed",
                    "comicvine_issue_id": "4000-42",
                    "cover_image_url": (
                        "https://comicvine.example/medium/4000-42.jpg"
                    ),
                },
                {
                    "issue_id": issue_ids["two"],
                    "thread_id": hellboy.id,
                    "thread_title": "Hellboy in Hell",
                    "issue_number": "2",
                    "status": "unread",
                    "read_at": None,
                    "rating": None,
                    "has_confirmed_identity": False,
                    "mapping_state": "candidate",
                    "comicvine_issue_id": None,
                    "cover_image_url": None,
                },
                {
                    "issue_id": issue_ids["one"],
                    "thread_id": hellboy.id,
                    "thread_title": "Hellboy in Hell",
                    "issue_number": "1",
                    "status": "unread",
                    "read_at": None,
                    "rating": None,
                    "has_confirmed_identity": False,
                    "mapping_state": "unmapped",
                    "comicvine_issue_id": None,
                    "cover_image_url": None,
                },
                {
                    "issue_id": issue_ids["bprd"],
                    "thread_id": bprd.id,
                    "thread_title": "B.P.R.D.",
                    "issue_number": "1",
                    "status": "unread",
                    "read_at": None,
                    "rating": None,
                    "has_confirmed_identity": True,
                    "mapping_state": "confirmed",
                    "comicvine_issue_id": "4000-45",
                    "cover_image_url": (
                        "https://comicvine.example/original/4000-45.jpg"
                    ),
                },
            ]
        }
        requested = [
            issue_ids["ten"],
            issue_ids["two"],
            issue_ids["one"],
            issue_ids["bprd"],
            issue_ids["foreign"],
            issue_ids["ten"],
        ]
        token = jwt.encode(
            {
                "sub": username,
                "jti": "native-issue-card-fixture",
                "type": "access",
                "exp": int((now + timedelta(hours=1)).timestamp()),
            },
            SECRET,
            "HS256",
        )
        query = f"options=-csearch_path%3D{name}"
        env = {
            **os.environ,
            "RUST_ROLL_DATABASE_URL": url + ("&" if "?" in url else "?") + query,
            "RUST_ROLL_JWT_SECRET": SECRET,
            "RUST_ROLL_TEST_TOKEN": token,
            "RUST_ROLL_POOL_SIZE": "2",
            "RUST_ROLL_TEST_BODY": json.dumps({"issue_ids": requested}),
        }

        result = await _run_example(env)
        assert result["status"] == 200, result
        assert result["body"] == expected

        for rejected in (
            {"issue_ids": []},
            {"issue_ids": list(range(1, 202))},
            {"issue_ids": [0]},
        ):
            env["RUST_ROLL_TEST_BODY"] = json.dumps(rejected)
            invalid = await _run_example(env)
            assert invalid["status"] == 422, invalid
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{name}" CASCADE'))
