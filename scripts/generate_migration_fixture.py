"""Prod-shaped synthetic migration fixture generator (issue #3554).

Builds a deterministic, anonymized and synthetic PostgreSQL fixture that
exercises the migration-relevant data shapes named in issue #3554:

* multiple synthetic users;
* threads with canonical dependencies and legacy ``cbl-order:%`` rows;
* reading plans with ``nodes_json`` / ``lanes_json``;
* CBL-adopted plans, source links and adoption receipts;
* snoozed and blocked threads plus collection exclusions;
* NULL-heavy legacy rows and adversarial values.

The fixture contains no real user records, credentials, comic titles or
personal data; every value is synthetic or derived from synthetic identities.
It is applied to a disposable database by :func:`apply_fixture` at the base
revision before the migration rehearsal runs ``alembic upgrade head``. The
applier reflects that historical schema instead of assuming current ORM columns
already exist, so pending column additions cannot make fixture loading fail.

Rows satisfy the base schema's CHECK / NOT NULL constraints. Adversarial history
includes the reviewed dangling rules that broke #3359, duplicate natural keys
across owners/threads, NULL-heavy legacy rows and a non-trivial dependency
volume; pending migrations must repair or explicitly tolerate that history.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import MetaData, Table, insert, inspect
from sqlalchemy.engine import Connection, Engine

SYNTHETIC_EMAIL_DOMAIN = "example.invalid"
VOLUME_THREAD_COUNT = 20
VOLUME_ISSUES_PER_THREAD = 50
REVIEWED_DANGLING_OWNER_USER_ID = 23199
REVIEWED_DANGLING_RULE_IDS = (1715192, 1715241, 1715291, 1715333, 1715578, 1715620)


def _utc_now() -> datetime:
    """Return a single UTC timestamp shared by all synthetic fixture rows."""
    return datetime.now(UTC)


def _user_rows() -> list[dict[str, Any]]:
    """Synthetic users; no real identities or credentials are ever stored."""
    now = _utc_now()
    return [
        {
            "id": 900001,
            "username": "reader-alpha",
            "email": f"reader-alpha@{SYNTHETIC_EMAIL_DOMAIN}",
            "password_hash": "synthetic-password-hash-alpha",
            "is_admin": False,
            "password_changed_at": None,
            "created_at": now,
        },
        {
            "id": 900002,
            "username": "reader-beta",
            "email": f"reader-beta@{SYNTHETIC_EMAIL_DOMAIN}",
            "password_hash": "synthetic-password-hash-beta",
            "is_admin": False,
            "password_changed_at": None,
            "created_at": now,
        },
    ]


def _thread_rows() -> list[dict[str, Any]]:
    """Threads covering active, blocked, snoozed and legacy NULL-heavy shapes."""
    now = _utc_now()
    return [
        {
            "id": 910001,
            "title": "Rehearsal Alpha Series",
            "format": "Comic",
            "issues_remaining": 2,
            "total_issues": 3,
            "next_unread_issue_id": None,
            "reading_progress": "in_progress",
            "queue_position": 1,
            "queue_order_key": None,
            "status": "active",
            "last_rating": None,
            "last_activity_at": now,
            "notes": None,
            "manual_creator_credits": None,
            "is_test": False,
            "is_blocked": True,
            "queue_position_is_manual": True,
            "created_at": now,
            "user_id": 900001,
            "catalog_series_id": None,
        },
        {
            "id": 910002,
            "title": "Rehearsal Beta Series",
            "format": "Comic",
            "issues_remaining": 1,
            "total_issues": 2,
            "next_unread_issue_id": None,
            "reading_progress": "not_started",
            "queue_position": 2,
            "queue_order_key": None,
            "status": "active",
            "last_rating": 4.5,
            "last_activity_at": now,
            "notes": "Synthetic rehearsal note",
            "manual_creator_credits": None,
            "is_test": False,
            "is_blocked": False,
            "queue_position_is_manual": False,
            "created_at": now,
            "user_id": 900001,
            "catalog_series_id": None,
        },
        {
            "id": 910003,
            "title": "Rehearsal Legacy Series",
            "format": "Comic",
            "issues_remaining": 1,
            "total_issues": 1,
            "next_unread_issue_id": None,
            "reading_progress": "completed",
            "queue_position": 3,
            "queue_order_key": None,
            "status": "completed",
            "last_rating": None,
            "last_activity_at": None,
            "notes": None,
            "manual_creator_credits": None,
            "is_test": True,
            "is_blocked": False,
            "queue_position_is_manual": False,
            "created_at": now,
            "user_id": 900002,
            "catalog_series_id": None,
        },
    ]


def _issue_rows() -> list[dict[str, Any]]:
    """Issue rows with unread/NULL-heavy legacy shapes."""
    now = _utc_now()
    return [
        {
            "id": 920001,
            "thread_id": 910001,
            "issue_number": "1",
            "position": 1,
            "status": "read",
            "read_at": now,
            "created_at": now,
            "catalog_issue_id": None,
        },
        {
            "id": 920002,
            "thread_id": 910001,
            "issue_number": "2",
            "position": 2,
            "status": "unread",
            "read_at": None,
            "created_at": now,
            "catalog_issue_id": None,
        },
        {
            "id": 920003,
            "thread_id": 910002,
            "issue_number": "1",
            "position": 1,
            "status": "unread",
            "read_at": None,
            "created_at": now,
            "catalog_issue_id": None,
        },
        {
            "id": 920004,
            "thread_id": 910003,
            "issue_number": "1",
            "position": 1,
            "status": "read",
            "read_at": now,
            "created_at": now,
            "catalog_issue_id": None,
        },
    ]


def _dependency_rows() -> list[dict[str, Any]]:
    """Canonical edges plus a legacy ``cbl-order:%`` inert row."""
    now = _utc_now()
    return [
        {
            "id": 930001,
            "source_issue_id": 920001,
            "target_issue_id": 920002,
            "created_at": now,
            "note": "synthetic-prerequisite",
            "origin": "reader",
            "classification": "A",
            "provenance": "synthetic",
        },
        {
            "id": 930002,
            "source_issue_id": 920003,
            "target_issue_id": 920004,
            "created_at": now,
            "note": "cbl-order:1700000000000",
            "origin": None,
            "classification": None,
            "provenance": None,
        },
    ]


def _continuity_plan_rows() -> list[dict[str, Any]]:
    now = _utc_now()
    return [
        {
            "id": 940001,
            "user_id": 900001,
            "name": "Rehearsal Alpha Plan",
            "ordering_mode": "strict_sequential",
            "nodes_json": [{"issue_id": 920002, "lane_id": "main"}],
            "lanes_json": [{"prerequisite_issue_id": 920001, "lane_id": "main"}],
            "created_at": now,
            "updated_at": now,
        },
    ]


def _reading_plan_issue_rows() -> list[dict[str, Any]]:
    return [
        {
            "plan_id": 940001,
            "occurrence_id": "entry",
            "issue_id": 920002,
            "lane_id": "main",
            "display_position": 1,
            "label": None,
            "reader_role": "reader",
            "reader_optional": False,
            "is_checkpoint": False,
            "source_metadata_json": {"source": "synthetic"},
        }
    ]


def _reading_plan_source_rows() -> list[dict[str, Any]]:
    now = _utc_now()
    return [
        {
            "id": 950001,
            "plan_id": 940001,
            "raw_source_path": "/synthetic/rehearsal-alpha.json",
            "repository": None,
            "source_path": None,
            "revision_sha": "synthetic-revision-0001",
            "content_hash": "synthetic-content-hash-0001",
            "cbl_source_list_id": 890001,
            "custom_cbl_list_id": 970001,
            "adopted_at": now,
            "recorded_at": now,
            "metadata_json": None,
        }
    ]


def _reading_plan_dependency_rows() -> list[dict[str, Any]]:
    return [
        {
            "plan_id": 940001,
            "dependency_id": 930001,
            "explanation": "synthetic-prerequisite",
        }
    ]


def _continuity_rule_rows() -> list[dict[str, Any]]:
    now = _utc_now()
    return [
        {
            "id": 960001,
            "user_id": 900001,
            "legacy_dependency_id": None,
            "source_type": "issue",
            "source_id": 920001,
            "target_type": "issue",
            "target_id": 920002,
            "satisfaction_type": "item_read",
            "checkpoint_issue_id": None,
            "convergence_targets": None,
            "note": "synthetic-rule",
            "created_at": now,
            "updated_at": now,
        },
    ]


def _custom_cbl_list_rows() -> list[dict[str, Any]]:
    now = _utc_now()
    return [
        {
            "id": 970001,
            "user_id": 900001,
            "name": "Rehearsal Alpha CBL",
            "mode": "loose",
            "description": None,
            "created_at": now,
            "updated_at": now,
            "overlap_decisions_updated_at": now,
        },
    ]


def _custom_cbl_entry_rows() -> list[dict[str, Any]]:
    return [
        {
            "id": 980001,
            "list_id": 970001,
            "issue_id": 920002,
            "position": 0,
            "gate": "none",
            "skipped": False,
            "is_checkpoint": False,
            "checkpoint_target_issue_ids": [],
            "created_at": _utc_now(),
        }
    ]


def _custom_cbl_source_link_rows() -> list[dict[str, Any]]:
    now = _utc_now()
    return [
        {
            "id": 990001,
            "user_id": 900001,
            "cbl_source_list_id": 890001,
            "custom_cbl_list_id": 970001,
            "source_revision_sha": "synthetic-revision-0001",
            "source_content_hash": "synthetic-content-hash-0001",
            "created_at": now,
            "updated_at": now,
        },
    ]


def _cbl_source_rows() -> list[dict[str, Any]]:
    now = _utc_now()
    return [
        {
            "id": 890000,
            "repository": "synthetic/org/rehearsal-cbl.git",
            "revision_sha": "synthetic-revision-0001",
            "synced_at": now,
            "created_at": now,
            "updated_at": now,
        },
    ]


def _cbl_source_list_rows() -> list[dict[str, Any]]:
    now = _utc_now()
    return [
        {
            "id": 890001,
            "source_id": 890000,
            "source_path": "/synthetic/cbl/rehearsal-alpha.txt",
            "name": "Rehearsal Alpha CBL",
            "declared_issue_count": 3,
            "content_hash": "synthetic-content-hash-0001",
            "revision_sha": "synthetic-revision-0001",
            "active": True,
            "created_at": now,
            "updated_at": now,
        },
    ]


def _cbl_adoption_receipt_rows() -> list[dict[str, Any]]:
    return [
        {
            "id": 991001,
            "user_id": 900001,
            "cbl_source_list_id": 890001,
            "plan_id": 940001,
            "request_fingerprint": "synthetic-fingerprint-0001",
            "created_at": _utc_now(),
        },
    ]


def _collection_exclusion_rows() -> list[dict[str, Any]]:
    now = _utc_now()
    return [
        {
            # Volume-based exclusion (exactly one target).
            "id": 992001,
            "user_id": 900002,
            "provider": "comicvine",
            "external_volume_id": "synthetic-volume-0001",
            "thread_id": None,
            "issue_id": None,
            "created_at": now,
        },
        {
            # Thread-based exclusion (exactly one target).
            "id": 992002,
            "user_id": 900001,
            "provider": None,
            "external_volume_id": None,
            "thread_id": 910002,
            "issue_id": None,
            "created_at": now,
        },
    ]


def _session_rows() -> list[dict[str, Any]]:
    now = _utc_now()
    return [
        {
            "id": 993001,
            "started_at": now,
            "ended_at": None,
            "start_die": 6,
            "manual_die": None,
            "user_id": 900001,
            "pending_thread_id": 910001,
            "pending_issue_id": 920002,
            "pending_thread_updated_at": now,
            "snoozed_thread_ids": [910003],
            "skipped_thread_ids": None,
            "timezone": "America/Chicago",
            "predicted_bandwidth": "balanced",
            "reading_bandwidth": "balanced",
            "active_bandwidth": None,
            "bandwidth_confidence": 0.9,
            "bandwidth_source": "manual",
            "bandwidth_version": "synthetic-1",
            "bandwidth_updated_at": now,
            "reading_intent": "balanced",
            "reading_mode_source": None,
            "reading_mode_suggested": False,
            "active_intent": "balanced",
            "predicted_intent": "balanced",
            "intent_confidence": None,
            "intent_source": "manual",
            "intent_version": "synthetic-1",
            "session_mode_correction_guidance": None,
        },
    ]


def _reviewed_dangling_user_rows() -> list[dict[str, Any]]:
    """Return the synthetic owner identity required by the #3359 allowlist."""
    return [
        {
            **_user_rows()[0],
            "id": REVIEWED_DANGLING_OWNER_USER_ID,
            "username": "rehearsal-reviewed-owner",
            "email": f"rehearsal-reviewed-owner@{SYNTHETIC_EMAIL_DOMAIN}",
            "password_hash": None,
        }
    ]


def _reviewed_dangling_thread_rows() -> list[dict[str, Any]]:
    """Return surviving synthetic threads around the #3359 dangling rules."""
    return [
        {
            **_thread_rows()[1],
            "id": 910004,
            "title": "Rehearsal Reviewed Dangling Series",
            "issues_remaining": 1,
            "total_issues": 2,
            "queue_position": 4,
            "user_id": REVIEWED_DANGLING_OWNER_USER_ID,
        }
    ]


def _reviewed_dangling_issue_rows() -> list[dict[str, Any]]:
    """Return two surviving endpoints; the other #3359 endpoints stay absent."""
    return [
        {
            **_issue_rows()[0],
            "id": 920005,
            "thread_id": 910004,
            "issue_number": "1",
            "position": 1,
        },
        {
            **_issue_rows()[1],
            "id": 920006,
            "thread_id": 910004,
            "issue_number": "2",
            "position": 2,
        },
    ]


def _reviewed_dangling_plan_rows() -> list[dict[str, Any]]:
    """Return the synthetic plan named by the reviewed dangling rules."""
    return [
        {
            **_continuity_plan_rows()[0],
            "id": 940002,
            "user_id": REVIEWED_DANGLING_OWNER_USER_ID,
            "name": "Rehearsal Reviewed Dangling Plan",
            "nodes_json": [{"issue_id": 920006, "lane_id": "reviewed"}],
            "lanes_json": [],
        }
    ]


def _reviewed_dangling_rule_rows() -> list[dict[str, Any]]:
    """Reproduce the six reviewed missing-endpoint shapes that aborted #3359."""
    specs = (
        (1117318, 920006),
        (920005, 1117522),
        (1117685, 920006),
        (920005, 1117685),
        (1117318, 1117522),
        (1117522, 1117685),
    )
    template = _continuity_rule_rows()[0]
    return [
        {
            **template,
            "id": rule_id,
            "user_id": REVIEWED_DANGLING_OWNER_USER_ID,
            "source_id": source_id,
            "target_id": target_id,
            "note": "continuity-plan:940002",
        }
        for rule_id, (source_id, target_id) in zip(
            REVIEWED_DANGLING_RULE_IDS, specs, strict=True
        )
    ]


def _volume_thread_rows() -> list[dict[str, Any]]:
    """Return a bounded multi-user synthetic library for backfill timing."""
    template = _thread_rows()[1]
    return [
        {
            **template,
            "id": 800001 + thread_index,
            "title": f"Rehearsal Volume Series {thread_index + 1:02d}",
            "issues_remaining": VOLUME_ISSUES_PER_THREAD,
            "total_issues": VOLUME_ISSUES_PER_THREAD,
            "queue_position": 100 + thread_index,
            "last_activity_at": None,
            "last_rating": None,
            "notes": None if thread_index % 2 else "  synthetic legacy whitespace  ",
            "is_blocked": thread_index % 7 == 0,
            "user_id": 900001 + thread_index % 2,
        }
        for thread_index in range(VOLUME_THREAD_COUNT)
    ]


def _volume_issue_rows() -> list[dict[str, Any]]:
    """Return representative issue cardinality and duplicate cross-thread keys."""
    template = _issue_rows()[1]
    rows: list[dict[str, Any]] = []
    for thread_index in range(VOLUME_THREAD_COUNT):
        for position in range(1, VOLUME_ISSUES_PER_THREAD + 1):
            is_read = position % 17 == 0
            rows.append(
                {
                    **template,
                    "id": 1000000 + thread_index * VOLUME_ISSUES_PER_THREAD + position,
                    "thread_id": 800001 + thread_index,
                    "issue_number": "0001" if position == 1 else str(position),
                    "position": position,
                    "status": "read" if is_read else "unread",
                    "read_at": _utc_now() if is_read else None,
                }
            )
    return rows


def _volume_dependency_rows() -> list[dict[str, Any]]:
    """Return acyclic issue chains for data-dependent backfill/cycle checks."""
    template = _dependency_rows()[0]
    rows: list[dict[str, Any]] = []
    for thread_index in range(VOLUME_THREAD_COUNT):
        for position in range(1, VOLUME_ISSUES_PER_THREAD):
            source_id = 1000000 + thread_index * VOLUME_ISSUES_PER_THREAD + position
            rows.append(
                {
                    **template,
                    "id": 1100000 + thread_index * VOLUME_ISSUES_PER_THREAD + position,
                    "source_issue_id": source_id,
                    "target_issue_id": source_id + 1,
                    "note": "synthetic-volume-prerequisite",
                }
            )
    return rows


def build_fixture() -> dict[str, list[dict[str, Any]]]:
    """Build the deterministic prod-shaped synthetic fixture rows.

    Returns:
        Mapping of table name to inserted row dictionaries, in fixture order.
    """
    return {
        "users": [*_user_rows(), *_reviewed_dangling_user_rows()],
        "threads": [*_thread_rows(), *_reviewed_dangling_thread_rows(), *_volume_thread_rows()],
        "issues": [*_issue_rows(), *_reviewed_dangling_issue_rows(), *_volume_issue_rows()],
        "dependencies": [*_dependency_rows(), *_volume_dependency_rows()],
        "continuity_plans": [*_continuity_plan_rows(), *_reviewed_dangling_plan_rows()],
        "reading_plan_issues": _reading_plan_issue_rows(),
        "reading_plan_dependencies": _reading_plan_dependency_rows(),
        "custom_cbl_lists": _custom_cbl_list_rows(),
        "custom_cbl_entries": _custom_cbl_entry_rows(),
        "cbl_sources": _cbl_source_rows(),
        "cbl_source_lists": _cbl_source_list_rows(),
        "custom_cbl_source_links": _custom_cbl_source_link_rows(),
        "reading_plan_sources": _reading_plan_source_rows(),
        "continuity_rules": [
            *_continuity_rule_rows(),
            *_reviewed_dangling_rule_rows(),
        ],
        "cbl_adoption_receipts": _cbl_adoption_receipt_rows(),
        "collection_exclusions": _collection_exclusion_rows(),
        "sessions": _session_rows(),
    }


def _compatible_rows(
    connection: Connection,
    table: Table,
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Project rows onto the actual base schema and reject unmappable history.

    Args:
        connection: Disposable database connection used for reflection.
        table: Freshly reflected base-revision table.
        rows: Synthetic row values in their newest known shape.

    Returns:
        Rows containing only columns present at the base revision.

    Raises:
        RuntimeError: If a required historical column has no fixture value.
    """
    supplied = set().union(*(row.keys() for row in rows))
    missing_required = [
        column.name
        for column in table.columns
        if column.name not in supplied
        and not column.nullable
        and column.default is None
        and column.server_default is None
        and not column.autoincrement
    ]
    if missing_required:
        raise RuntimeError(
            f"fixture table {table.name!r} needs values for historical required columns: "
            + ", ".join(sorted(missing_required))
        )
    return [
        {key: value for key, value in row.items() if key in table.columns}
        for row in rows
    ]


def apply_fixture(engine: Engine) -> None:
    """Apply synthetic history through bulk inserts at the actual base schema.

    Args:
        engine: Sync SQLAlchemy engine bound to the disposable rehearsal DB.

    Raises:
        RuntimeError: When a historical table needs an explicit new fixture
            mapping, or when a row violates a base-schema constraint.
    """
    fixture = build_fixture()
    metadata = MetaData()
    with engine.begin() as connection:
        existing_tables = set(inspect(connection).get_table_names())
        inserted_total = 0
        for table_name, rows in fixture.items():
            if not rows or table_name not in existing_tables:
                continue
            table = Table(table_name, metadata, autoload_with=connection)
            compatible_rows = _compatible_rows(connection, table, rows)
            connection.execute(insert(table).values(compatible_rows))
            inserted_total += len(compatible_rows)
            print(f"migration-fixture table {table_name}: {len(compatible_rows)} rows")
        print(f"migration-fixture total: {inserted_total} synthetic rows")
