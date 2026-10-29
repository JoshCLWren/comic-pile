"""Complete Option E input parity on isolated synthetic PostgreSQL schemas."""

import asyncio
import json
import os
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

import pytest
from jose import jwt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.database import Base
from app.models import Dependency, Issue, Thread, User
from app.models.catalog import CatalogIssue, CatalogSeries
from app.models.collection_exclusion import CollectionExclusion
from app.models.custom_cbl import CustomCBLEntry, CustomCBLList, CustomCBLOverlapDecision
from app.models.external_identity import ExternalIdentity, ThreadExternalSeriesMapping
from app.repositories.reading_shadow_repository import load_shadow_inputs

ROOT = Path(__file__).resolve().parents[3]
SECRET = "synthetic-option-parity"


@pytest.mark.asyncio
async def test_option_input_parity() -> None:
    """Compare all constraints, then corrupt owned endpoints to test closed failure."""
    url = os.environ["RUST_ROLL_TEST_DATABASE_URL"]
    schema = f"native_options_{uuid4().hex}"
    admin = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    async with admin.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(
        url.replace("postgresql://", "postgresql+asyncpg://"),
        connect_args={"server_settings": {"search_path": schema}},
    )
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with AsyncSession(engine, expire_on_commit=False) as db:
            reader, foreign = User(username="option-reader"), User(username="private-reader")
            db.add_all([reader, foreign])
            await db.flush()
            threads = [Thread(user_id=reader.id, title=f"Owned {n}", format="Comic",
                              status="completed" if n == 0 else "active", queue_position=n)
                       for n in range(8)]
            private = Thread(user_id=foreign.id, title="FOREIGN SECRET", format="Comic",
                             status="active", queue_position=1)
            db.add_all([*threads, private])
            await db.flush()
            issues = [Issue(thread_id=t.id, issue_number=str(n), position=1,
                            status="read" if n == 0 else "unread")
                      for n, t in enumerate([*threads, private])]
            db.add_all(issues)
            await db.flush()
            identities = [ExternalIdentity(provider=p, entity_type="series", external_id=v)
                          for p, v in [(" ComicVine ", "4050-00012"), ("comicvine", "12"),
                                       ("comicvine", "13"), ("other", "12"),
                                       ("comicvine", "4050-00014")]]
            db.add_all(identities)
            await db.flush()
            series = [CatalogSeries(canonical_external_identity_id=i.id) for i in identities]
            db.add_all(series)
            await db.flush()
            # Same volume via two encodings; conflicting volumes; candidate ignored.
            threads[0].catalog_series_id = series[0].id
            threads[1].catalog_series_id = series[1].id
            threads[2].catalog_series_id = series[1].id
            db.add_all([
                ThreadExternalSeriesMapping(thread_id=threads[0].id,
                    external_identity_id=identities[1].id, status="confirmed"),
                ThreadExternalSeriesMapping(thread_id=threads[2].id,
                    external_identity_id=identities[2].id, status="confirmed"),
                ThreadExternalSeriesMapping(thread_id=threads[3].id,
                    external_identity_id=identities[1].id, status="candidate"),
                ThreadExternalSeriesMapping(thread_id=threads[4].id,
                    external_identity_id=identities[3].id, status="confirmed"),
            ])
            issue_identity = ExternalIdentity(provider="comicvine", entity_type="issue",
                                              external_id="900")
            db.add(issue_identity)
            await db.flush()
            catalog_issue = CatalogIssue(canonical_external_identity_id=issue_identity.id,
                                         catalog_series_id=series[4].id)
            db.add(catalog_issue)
            await db.flush()
            issues[5].catalog_issue_id = catalog_issue.id
            db.add_all([
                CollectionExclusion(user_id=reader.id, provider="COMICVINE",
                                    external_volume_id="4050-0012"),
                CollectionExclusion(user_id=reader.id, provider="comicvine",
                                    external_volume_id="14"),
                CollectionExclusion(user_id=reader.id, thread_id=threads[3].id),
                CollectionExclusion(user_id=reader.id, issue_id=issues[4].id),
                CollectionExclusion(user_id=reader.id, issue_id=issues[-1].id),
                CollectionExclusion(user_id=foreign.id, issue_id=issues[6].id),
            ])
            strict = CustomCBLList(user_id=reader.id, name="Strict", mode="strict")
            loose = CustomCBLList(user_id=reader.id, name="Loose", mode="loose")
            hidden = CustomCBLList(user_id=foreign.id, name="FOREIGN LIST", mode="strict")
            db.add_all([strict, loose, hidden])
            await db.flush()
            # Insertion order deliberately differs from curated order. Shared issue
            # placements across lists represent the multi-story/duplicate case.
            db.add_all([
                CustomCBLEntry(list_id=strict.id, issue_id=issues[2].id, position=30,
                               gate="after_previous"),
                CustomCBLEntry(list_id=strict.id, issue_id=issues[0].id, position=10,
                               gate="hold"),
                CustomCBLEntry(list_id=strict.id, issue_id=issues[1].id, position=20,
                               skipped=True),
                CustomCBLEntry(list_id=loose.id, issue_id=issues[2].id, position=1),
                CustomCBLEntry(list_id=hidden.id, issue_id=issues[-1].id, position=1),
                CustomCBLOverlapDecision(user_id=reader.id, list_id=strict.id,
                    continuing_external_identity_id=identities[0].id,
                    waiting_external_identity_id=identities[2].id),
                CustomCBLOverlapDecision(user_id=reader.id, list_id=loose.id,
                    continuing_external_identity_id=identities[3].id,
                    waiting_external_identity_id=identities[2].id),
                Dependency(source_issue_id=issues[0].id, target_issue_id=issues[6].id,
                           origin="reader", classification="A", provenance="reader approved"),
                Dependency(source_issue_id=issues[1].id, target_issue_id=issues[7].id,
                           origin="reader"),
                Dependency(source_issue_id=issues[2].id, target_issue_id=issues[6].id,
                           origin="converted", classification="B", provenance="historical"),
                Dependency(source_issue_id=issues[3].id, target_issue_id=issues[6].id,
                           note="cbl-order:historical"),
            ])
            await db.commit()
            reader_id = reader.id

        async def compare(expected_status: int) -> dict[str, object]:
            """Compare every native constraint with the current canonical Python loader.

            Args:
                expected_status: Zero for resolved inputs, two for unresolved constraints.

            Returns:
                Parsed native snapshot for scenario-specific assertions.
            """
            async with engine.connect() as connection:
                connection = await connection.execution_options(isolation_level="REPEATABLE READ")
                async with connection.begin():
                    await connection.execute(text("SET TRANSACTION READ ONLY"))
                    async with AsyncSession(bind=connection) as db:
                        oracle = await load_shadow_inputs(db, reader_id,
                                                          include_legacy_diagnostics=False)
            environment = {**os.environ,
                "RUST_ROLL_DATABASE_URL": f"{url}{'&' if '?' in url else '?'}options=-csearch_path%3D{schema}",
                "RUST_ROLL_JWT_SECRET": SECRET,
                "RUST_ROLL_TEST_TOKEN": jwt.encode({"sub": "option-reader", "type": "access", "jti": "synthetic-option-jti"},
                                                   SECRET, "HS256")}
            process = await asyncio.create_subprocess_exec(
                str(ROOT / "native/roll-service/target/debug/examples/option_snapshot"),
                env=environment, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=15)
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
            assert process.returncode == expected_status, stderr.decode()
            result = json.loads(stdout)
            assert result["thread_volumes"] == {
                str(t.thread_id): t.comicvine_volume_id for t in oracle.threads
                if t.comicvine_volume_id is not None}
            expected_lists = [asdict(row) for row in oracle.lists]
            for row in expected_lists:
                row.pop("name")
            assert result["lists"] == json.loads(json.dumps(expected_lists))
            assert result["prerequisites"] == json.loads(json.dumps(
                [asdict(row) for row in oracle.prerequisites]))
            assert result["excluded_issue_ids"] == sorted(oracle.excluded_issue_ids)
            assert result["unresolved"] == [asdict(row) for row in oracle.unresolved]
            assert "FOREIGN SECRET" not in stdout.decode()
            assert "FOREIGN LIST" not in stdout.decode()
            return result

        result = await compare(0)
        assert len(result["prerequisites"]) == 2
        assert len(result["excluded_issue_ids"]) == 6
        assert str(threads[2].id) not in result["thread_volumes"]
        assert str(threads[3].id) not in result["thread_volumes"]
        async with AsyncSession(engine) as db:
            # Both directions touch owned data; completely foreign constraints are absent.
            db.add_all([
                Dependency(source_issue_id=issues[-1].id, target_issue_id=issues[7].id,
                           origin="reader"),
                Dependency(source_issue_id=issues[6].id, target_issue_id=issues[-1].id,
                           origin="reader"),
                CustomCBLEntry(list_id=loose.id, issue_id=issues[-1].id, position=2),
            ])
            await db.commit()
        result = await compare(2)
        assert len(result["unresolved"]) == 3
        # A dangling entry is also diagnosed, rather than silently removed by a join.
        # Only this disposable schema loses its normally protective FK.
        async with engine.begin() as connection:
            await connection.execute(text(
                "ALTER TABLE custom_cbl_entries DROP CONSTRAINT custom_cbl_entries_issue_id_fkey"
            ))
            await connection.execute(text(
                "UPDATE custom_cbl_entries SET issue_id=:missing "
                "WHERE list_id=:list AND issue_id=:issue"
            ), {"missing": max(i.id for i in issues) + 100, "list": loose.id,
                "issue": issues[-1].id})
        await compare(2)
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()
