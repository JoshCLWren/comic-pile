"""Native v2 reader threads collection against the canonical Python oracle.

The synthetic schema comes from the canonical SQLAlchemy models, so the Rust
handler runs against the same tables production migrations create. Every query
variant compares the mounted Rust route with ``thread_service.list_queue_threads``
on identical data: ordering, cursor paging, search, tags, mapping health, series
metadata, manual credits, next-unread identity, counts and ownership.

The default (legacy) authority must issue exactly one PostgreSQL statement for
the whole request, including the token's revocation and password-epoch check.
The owner-activated Option E preview additionally loads its evaluated input
snapshot before the page statement.
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4

import pytest
from jose import jwt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config import get_reading_execution_settings
from app.database import Base
from app.models import Dependency, Issue, Thread, User
from app.models.custom_cbl import CustomCBLList
from app.models.custom_cbl import CustomCBLEntry
from app.models.external_identity import (
    ExternalIdentity,
    IssueExternalIdentityMapping,
    ThreadExternalSeriesMapping,
)
from app.models.tag import Tag, TagAssignment
from app.services import thread_service

SECRET = "synthetic-native-threads-secret"
# CI builds into native/roll-service/target; the managed local wrapper keeps
# its own bounded target directory, so locate the built example without changing
# how this test builds or runs anything.
EXAMPLE = (
    Path(os.environ.get("CARGO_TARGET_DIR", "native/roll-service/target"))
    / "debug/examples/http_threads_list"
)


def _token(username: str, *, jti: str, password_epoch: int | None = None) -> str:
    payload: dict[str, object] = {
        "sub": username,
        "jti": jti,
        "type": "access",
        "exp": 4_102_444_800,
    }
    if password_epoch is not None:
        payload["pc"] = password_epoch
    return jwt.encode(payload, SECRET, algorithm="HS256")


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


async def _db_transactions(admin) -> tuple[int, int]:
    async with admin.connect() as connection:
        row = await connection.execute(
            text(
                "SELECT xact_commit, xact_rollback FROM pg_stat_database "
                "WHERE datname = current_database()"
            )
        )
        commits, rollbacks = row.one()
        return int(commits), int(rollbacks)


async def _expected(
    db: AsyncSession,
    user_id: int,
    *,
    search: str | None = None,
    sort: str = "position",
    page_size: int = 50,
    page_token: str | None = None,
) -> dict[str, object]:
    response = await thread_service.list_queue_threads(
        db,
        user_id,
        search=search,
        sort=sort,
        page_size=page_size,
        page_token=page_token,
    )
    return response.model_dump(mode="json")


@pytest.mark.asyncio
async def test_native_threads_collection_matches_python_oracle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preserve every real Queue/threads consumer field and one-statement budget."""
    url = os.environ["RUST_ROLL_TEST_DATABASE_URL"]
    schema = f"rust_threads_{uuid4().hex}"
    admin = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    async with admin.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(
        url.replace("postgresql://", "postgresql+asyncpg://"),
        connect_args={"server_settings": {"search_path": f"{schema},public"}},
    )
    try:
        async with engine.begin() as connection:
            # The schema is new; keep public on the path for the pg_trgm
            # operator class without reusing tables created by other tests.
            await connection.run_sync(
                lambda sync_connection: Base.metadata.create_all(
                    sync_connection, checkfirst=False
                )
            )

        owner_name = f"threads_{uuid4().hex[:12]}"
        stranger_name = f"stranger_{uuid4().hex[:12]}"
        token = _token(owner_name, jti=f"jti-{uuid4().hex}")
        created = datetime(2024, 3, 4, 5, 6, 7, 123456, tzinfo=UTC)
        activity = datetime(2024, 4, 5, 6, 7, 8, 1000, tzinfo=UTC)

        async with AsyncSession(engine, expire_on_commit=False) as db:
            owner = User(username=owner_name)
            stranger = User(username=stranger_name)
            db.add_all([owner, stranger])
            await db.flush()

            alpha = Thread(
                user_id=owner.id,
                title="Alpha Saga",
                format="comics",
                queue_position=1,
                issues_remaining=4,
                notes="Continue after Annual 2",
                manual_creator_credits=[{"name": "Ann Author", "roles": ["writer"]}],
                created_at=created,
                last_activity_at=activity,
            )
            beta = Thread(
                user_id=owner.id,
                title="Beta Blocked",
                format="Comic",
                queue_position=2,
                issues_remaining=1,
                total_issues=2,
                is_blocked=True,
                created_at=created.replace(day=5),
            )
            gamma = Thread(
                user_id=owner.id,
                title="Gamma Mapped",
                format="Comic",
                queue_position=3,
                issues_remaining=2,
                total_issues=3,
                created_at=created.replace(day=6),
            )
            delta = Thread(
                user_id=owner.id,
                title="Delta Review",
                format="Comic",
                queue_position=4,
                issues_remaining=1,
                total_issues=1,
                created_at=created.replace(day=7),
            )
            epsilon = Thread(
                user_id=owner.id,
                title="Epsilon Empty",
                format="Comic",
                queue_position=5,
                issues_remaining=0,
                total_issues=1,
                created_at=created.replace(day=8),
            )
            zeta = Thread(
                user_id=owner.id,
                title="Zeta Digital",
                format="digital",
                queue_position=6,
                issues_remaining=1,
                total_issues=1,
                created_at=created.replace(day=9),
            )
            omega = Thread(
                user_id=owner.id,
                title="Omega Pending",
                format="Manga",
                queue_position=0,
                issues_remaining=2,
                created_at=created.replace(day=10),
            )
            foreign = Thread(
                user_id=stranger.id,
                title="Foreign Secret",
                format="Comic",
                queue_position=1,
                issues_remaining=1,
                total_issues=1,
            )
            db.add_all([alpha, beta, gamma, delta, epsilon, zeta, omega, foreign])
            await db.flush()

            beta_one = Issue(
                thread_id=beta.id,
                issue_number="1",
                position=1,
                status="read",
                read_at=created,
            )
            beta_two = Issue(
                thread_id=beta.id, issue_number="2", position=2, status="unread"
            )
            gamma_issues = [
                Issue(
                    thread_id=gamma.id,
                    issue_number=number,
                    position=position,
                    status="read" if number == "1" else "unread",
                )
                for position, number in enumerate(["1", "2", "3"], start=1)
            ]
            delta_issue = Issue(
                thread_id=delta.id, issue_number="1", position=1, status="unread"
            )
            zeta_issue = Issue(
                thread_id=zeta.id, issue_number="1", position=1, status="unread"
            )
            foreign_issue = Issue(
                thread_id=foreign.id, issue_number="1", position=1, status="unread"
            )
            db.add_all(
                [
                    beta_one,
                    beta_two,
                    *gamma_issues,
                    delta_issue,
                    zeta_issue,
                    foreign_issue,
                ]
            )
            await db.flush()
            beta.next_unread_issue_id = beta_two.id
            gamma.next_unread_issue_id = gamma_issues[1].id
            delta.next_unread_issue_id = delta_issue.id
            zeta.next_unread_issue_id = zeta_issue.id
            foreign.next_unread_issue_id = foreign_issue.id

            series_identities = {
                "alpha": ExternalIdentity(
                    provider="comicvine",
                    entity_type="series",
                    external_id="4050-1001",
                    metadata_json={"cover_date": "1987-05-01", "name": "Alpha Saga"},
                ),
                "gamma_primary": ExternalIdentity(
                    provider="comicvine",
                    entity_type="series",
                    external_id="4050-1002",
                    metadata_json={
                        "start_year": "1990",
                        "volume": {"name": "Gamma Vol 2"},
                        "publisher": {"name": "Image"},
                    },
                ),
                "gamma_secondary": ExternalIdentity(
                    provider="comicvine",
                    entity_type="series",
                    external_id="4050-1003",
                    metadata_json={"name": "Gamma Alternate"},
                ),
                "zeta": ExternalIdentity(
                    provider="comicvine",
                    entity_type="series",
                    external_id="4050-1004",
                    metadata_json={"name": "Zeta Digital"},
                ),
            }
            db.add_all(series_identities.values())
            await db.flush()
            db.add_all(
                [
                    ThreadExternalSeriesMapping(
                        thread_id=alpha.id,
                        external_identity_id=series_identities["alpha"].id,
                        status="confirmed",
                        confidence=0.4,
                    ),
                    ThreadExternalSeriesMapping(
                        thread_id=gamma.id,
                        external_identity_id=series_identities["gamma_primary"].id,
                        status="confirmed",
                        confidence=0.9,
                    ),
                    ThreadExternalSeriesMapping(
                        thread_id=gamma.id,
                        external_identity_id=series_identities["gamma_secondary"].id,
                        status="confirmed",
                        confidence=0.5,
                    ),
                    ThreadExternalSeriesMapping(
                        thread_id=zeta.id,
                        external_identity_id=series_identities["zeta"].id,
                        status="confirmed",
                        confidence=0.7,
                    ),
                ]
            )

            mapped_issue = ExternalIdentity(
                provider="comicvine",
                entity_type="issue",
                external_id="4000-2001",
                metadata_json={
                    "issue_number": "1",
                    "volume": {"name": "Gamma Vol 2"},
                },
            )
            metadata_missing_issue = ExternalIdentity(
                provider="comicvine",
                entity_type="issue",
                external_id="4000-2002",
                metadata_json={"volume_name": "Gamma Vol 2"},
            )
            review_one = ExternalIdentity(
                provider="comicvine",
                entity_type="issue",
                external_id="4000-2003",
                metadata_json={"issue_number": "1", "volume_name": "Delta"},
            )
            review_two = ExternalIdentity(
                provider="comicvine",
                entity_type="issue",
                external_id="4000-2004",
                metadata_json={"issue_number": "1", "volume_name": "Delta"},
            )
            db.add_all(
                [mapped_issue, metadata_missing_issue, review_one, review_two]
            )
            await db.flush()
            db.add_all(
                [
                    IssueExternalIdentityMapping(
                        issue_id=gamma_issues[0].id,
                        external_identity_id=mapped_issue.id,
                        status="confirmed",
                    ),
                    IssueExternalIdentityMapping(
                        issue_id=gamma_issues[1].id,
                        external_identity_id=metadata_missing_issue.id,
                        status="confirmed",
                    ),
                    IssueExternalIdentityMapping(
                        issue_id=delta_issue.id,
                        external_identity_id=review_one.id,
                        status="confirmed",
                    ),
                    IssueExternalIdentityMapping(
                        issue_id=delta_issue.id,
                        external_identity_id=review_two.id,
                        status="confirmed",
                    ),
                ]
            )

            global_tag = Tag(
                name="Classic",
                normalized_name="classic",
                scope="global",
                owner_user_id=None,
                color="#112233",
            )
            private_tag = Tag(
                name="Mine",
                normalized_name="mine",
                scope="private",
                owner_user_id=owner.id,
                color="#445566",
            )
            foreign_tag = Tag(
                name="Hidden",
                normalized_name="hidden",
                scope="private",
                owner_user_id=stranger.id,
                color="#778899",
            )
            db.add_all([global_tag, private_tag, foreign_tag])
            await db.flush()
            db.add_all(
                [
                    TagAssignment(
                        tag_id=global_tag.id, target_type="Thread", target_id=alpha.id
                    ),
                    TagAssignment(
                        tag_id=private_tag.id, target_type="Thread", target_id=alpha.id
                    ),
                    TagAssignment(
                        tag_id=private_tag.id, target_type="Thread", target_id=beta.id
                    ),
                    TagAssignment(
                        tag_id=foreign_tag.id, target_type="Thread", target_id=alpha.id
                    ),
                    TagAssignment(
                        tag_id=global_tag.id, target_type="Thread", target_id=foreign.id
                    ),
                ]
            )

            # Option E: a reader prerequisite blocks Beta's frontier; a strict
            # list name must appear in Zeta's projected reason.
            db.add(
                Dependency(
                    source_issue_id=gamma_issues[1].id,
                    target_issue_id=beta_two.id,
                    origin="reader",
                )
            )
            strict = CustomCBLList(user_id=owner.id, name="Cross Strict", mode="strict")
            db.add(strict)
            await db.flush()
            db.add_all(
                [
                    CustomCBLEntry(
                        list_id=strict.id, issue_id=beta_two.id, position=1, gate="none"
                    ),
                    CustomCBLEntry(
                        list_id=strict.id, issue_id=zeta_issue.id, position=2, gate="none"
                    ),
                ]
            )
            await db.commit()

            env = {
                **os.environ,
                "RUST_ROLL_DATABASE_URL": url
                + ("&" if "?" in url else "?")
                + f"options=-csearch_path%3D{schema}",
                "RUST_ROLL_JWT_SECRET": SECRET,
                "RUST_ROLL_TEST_TOKEN": token,
                "RUST_ROLL_POOL_SIZE": "2",
            }

            async def compare(
                *,
                search: str | None = None,
                sort: str = "position",
                page_size: int = 50,
                page_token: str | None = None,
            ) -> dict[str, object]:
                params: dict[str, object] = {"sort": sort, "page_size": page_size}
                if search is not None:
                    params["search"] = search
                if page_token is not None:
                    params["page_token"] = page_token
                expected = await _expected(
                    db,
                    owner.id,
                    search=search,
                    sort=sort,
                    page_size=page_size,
                    page_token=page_token,
                )
                request_env = dict(env)
                request_env["RUST_ROLL_TEST_URI"] = (
                    "/api/v2/threads?" + urlencode(params)
                )
                before = await _db_transactions(admin)
                result = await _run_example(request_env)
                after = await _db_transactions(admin)
                assert result["status"] == 200, result
                # The default path issues its one page statement, with the
                # token revocation and credential-epoch check folded into that
                # statement's CTEs. The database counters are reported as
                # measurement, not as an exact assertion: PostgreSQL updates
                # them asynchronously and the Python oracle shares the database.
                assert result["page_statements"] == 1, result
                print(
                    "native threads parity: "
                    f"page_statements={result['page_statements']} "
                    f"db_commits={after[0] - before[0]} "
                    f"db_rollbacks={after[1] - before[1]}",
                    flush=True,
                )
                assert result["body"] == expected
                return expected

            # The full first page, every consumer field and one statement.
            first = await compare()
            rows = {row["title"]: row for row in first["threads"]}  # type: ignore[index]
            assert first["active_count"] == 6  # Omega (position 0) stays out
            assert [row["title"] for row in first["threads"]] == [  # type: ignore[index]
                "Omega Pending",
                "Alpha Saga",
                "Gamma Mapped",
                "Delta Review",
                "Epsilon Empty",
                "Zeta Digital",
                "Beta Blocked",
            ]
            assert rows["Alpha Saga"]["format"] == "Comic"
            assert rows["Zeta Digital"]["format"] == "Digital"
            assert rows["Alpha Saga"]["manual_creator_credits"] == [
                {"name": "Ann Author", "roles": ["writer"]}
            ]
            assert rows["Gamma Mapped"]["comicvine_mapping"] == {
                "status": "partial",
                "tracked_issue_count": 3,
                "confirmed_issue_count": 2,
                "needs_mapping_count": 1,
                "needs_review_count": 0,
                "metadata_missing_count": 1,
            }
            assert rows["Delta Review"]["comicvine_mapping"]["status"] == "needs_review"
            assert rows["Epsilon Empty"]["comicvine_mapping"] == {
                "status": "not_applicable",
                "tracked_issue_count": 0,
                "confirmed_issue_count": 0,
                "needs_mapping_count": 0,
                "needs_review_count": 0,
                "metadata_missing_count": 0,
            }
            assert rows["Alpha Saga"]["comicvine_mapping"] is None
            assert rows["Gamma Mapped"]["series_metadata"] == {
                "year": 1990,
                "volume": "Gamma Vol 2",
                "publisher": "Image",
            }
            assert rows["Alpha Saga"]["series_metadata"] == {
                "year": 1987,
                "volume": None,
                "publisher": None,
            }
            assert rows["Zeta Digital"]["series_metadata"] == {
                "year": None,
                "volume": None,
                "publisher": None,
            }
            assert rows["Alpha Saga"]["tags"] == [
                {
                    "id": private_tag.id,
                    "name": "Mine",
                    "normalized_name": "mine",
                    "scope": "private",
                    "owner_user_id": owner.id,
                    "color": "#445566",
                    "created_at": rows["Alpha Saga"]["tags"][0]["created_at"],
                    "updated_at": rows["Alpha Saga"]["tags"][0]["updated_at"],
                },
                {
                    "id": global_tag.id,
                    "name": "Classic",
                    "normalized_name": "classic",
                    "scope": "global",
                    "owner_user_id": None,
                    "color": "#112233",
                    "created_at": rows["Alpha Saga"]["tags"][1]["created_at"],
                    "updated_at": rows["Alpha Saga"]["tags"][1]["updated_at"],
                },
            ]
            assert all(tag["name"] != "Hidden" for tag in rows["Alpha Saga"]["tags"])
            assert "Foreign Secret" not in json.dumps(first)

            # Cursor pagination, search and both deterministic secondary sorts.
            paged = await compare(page_size=2)
            await compare(page_size=2, sort="title")
            await compare(page_size=3, sort="created")
            await compare(search="mapped")
            page_two = paged.get("next_page_token")
            assert page_two
            await compare(page_size=2, page_token=str(page_two))

            # Bad inputs keep their v1 status semantics.
            request_env = dict(env)
            request_env["RUST_ROLL_TEST_URI"] = "/api/v2/threads?sort=bogus"
            invalid = await _run_example(request_env)
            assert invalid["status"] == 400
            assert invalid["body"] == {
                "detail": "sort must be one of: position, title, created"
            }
            assert invalid["page_statements"] == 0
            request_env["RUST_ROLL_TEST_URI"] = "/api/v2/threads?page_token=nope"
            malformed = await _run_example(request_env)
            assert malformed["status"] == 400
            assert malformed["body"] == {"detail": "Invalid Queue page token"}
            assert malformed["page_statements"] == 0
            request_env["RUST_ROLL_TEST_URI"] = "/api/v2/threads?collection_id=4"
            retired = await _run_example(request_env)
            assert retired["status"] == 422
            assert retired["body"] == {"detail": "collection_id is retired"}
            assert retired["page_statements"] == 0

            # An empty library is a bounded, valid one-statement read.
            empty_name = f"empty_{uuid4().hex[:12]}"
            empty = User(username=empty_name)
            db.add(empty)
            await db.commit()
            empty_env = dict(env)
            empty_env["RUST_ROLL_TEST_TOKEN"] = _token(
                empty_name, jti=f"empty-{uuid4().hex}"
            )
            empty_env["RUST_ROLL_TEST_URI"] = "/api/v2/threads"
            empty_result = await _run_example(empty_env)
            assert empty_result["status"] == 200, empty_result
            assert empty_result["page_statements"] == 1
            assert empty_result["body"] == await _expected(db, empty.id)
            assert empty_result["body"] == {
                "threads": [],
                "next_page_token": None,
                "active_count": 0,
            }

            # Authentication keeps the token revocation and credential epoch
            # checks folded into the same statement.
            revoked_token = _token(owner_name, jti="revoked-jti")
            request_env = dict(env)
            request_env["RUST_ROLL_TEST_TOKEN"] = revoked_token
            await db.execute(
                text(
                    "INSERT INTO revoked_tokens (jti, user_id, revoked_at, expires_at) "
                    "VALUES (:jti, :user_id, now(), now() + interval '1 day')"
                ),
                {"jti": "revoked-jti", "user_id": owner.id},
            )
            await db.commit()
            denied = await _run_example(request_env)
            assert denied["status"] == 401
            assert denied["body"] == {"detail": "Token has been revoked"}
            assert denied["page_statements"] == 1

            # Option E preview: evaluated grouping, availability, frontier and
            # blockers, plus the bounded input snapshot before the page.
            monkeypatch.setenv("OPTION_E_ENABLED", "true")
            monkeypatch.setenv(
                "OPTION_E_APPROVED_PREVIEW", "native-parity-threads-fixture"
            )
            get_reading_execution_settings.cache_clear()
            option_env = dict(env)
            option_env["OPTION_E_ENABLED"] = "true"
            option_expected = await _expected(db, owner.id)
            option_env["RUST_ROLL_TEST_URI"] = "/api/v2/threads?sort=position"
            before = await _db_transactions(admin)
            option_result = await _run_example(option_env)
            after = await _db_transactions(admin)
            assert option_result["status"] == 200, option_result
            # Preview mode adds the auth lookup and the read-only eligibility
            # snapshot around the same single page statement.
            assert option_result["page_statements"] == 1
            print(
                "native threads Option E parity: "
                f"page_statements={option_result['page_statements']} "
                f"db_commits={after[0] - before[0]} "
                f"db_rollbacks={after[1] - before[1]}",
                flush=True,
            )
            if option_result["body"] != option_expected:
                rust_rows = {
                    row["id"]: row for row in option_result["body"]["threads"]
                }
                oracle_rows = {row["id"]: row for row in option_expected["threads"]}
                print(
                    "OPTION E ORDER",
                    [row["title"] for row in option_result["body"]["threads"]],
                    [row["title"] for row in option_expected["threads"]],
                    flush=True,
                )
                for thread_id in sorted(set(rust_rows) | set(oracle_rows)):
                    if rust_rows.get(thread_id) != oracle_rows.get(thread_id):
                        print(
                            "ROW DIFF",
                            thread_id,
                            json.dumps(rust_rows.get(thread_id), sort_keys=True),
                            json.dumps(oracle_rows.get(thread_id), sort_keys=True),
                            flush=True,
                        )
            assert option_result["body"] == option_expected
            option_rows = {
                row["title"]: row for row in option_result["body"]["threads"]
            }
            assert option_rows["Beta Blocked"]["is_blocked"] is True
            assert option_rows["Beta Blocked"]["blocking_reasons"] == [
                "Reader prerequisite: waiting on Gamma Mapped #2"
            ]
            assert option_rows["Zeta Digital"]["blocking_reasons"] == [
                "Strict order in Cross Strict: waiting on Beta Blocked #2"
            ]
            get_reading_execution_settings.cache_clear()

            await db.execute(
                text("UPDATE users SET password_changed_at = now() WHERE id = :id"),
                {"id": owner.id},
            )
            await db.commit()
            stale_epoch = dict(env)
            stale_epoch["RUST_ROLL_TEST_TOKEN"] = _token(
                owner_name, jti=f"epoch-{uuid4().hex}", password_epoch=0
            )
            stale = await _run_example(stale_epoch)
            assert stale["status"] == 401
            assert stale["body"] == {
                "detail": "Password changed; please sign in again."
            }
            assert stale["page_statements"] == 1
    finally:
        get_reading_execution_settings.cache_clear()
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()
