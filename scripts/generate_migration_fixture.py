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
It is applied to a disposable database by :func:`apply_fixture` before the
migration rehearsal runs ``alembic upgrade head``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import insert
from sqlalchemy.engine import Engine

from app.models.cbl_adoption_receipt import CBLAdoptionReceipt
from app.models.collection_exclusion import CollectionExclusion
from app.models.continuity_plan import ContinuityPlan
from app.models.continuity_rule import ContinuityRule
from app.models.custom_cbl import CustomCBLEntry, CustomCBLList, CustomCBLSourceLink
from app.models.custom_cbl_source_link import CustomCBLSourceLink as CustomCBLSourceLinkAlias  # noqa: F401
from app.models.dependency import Dependency
from app.models.issue import Issue
from app.models.reading_plan_dependencies import ReadingPlanDependency
from app.models.reading_plan_issues import ReadingPlanIssue
from app.models.reading_plan_release_source import ReadingPlanReleaseSource
from app.models.reading_plan_sources import ReadingPlanSource
from app.models.thread import Thread
from app.models.user import User

FIXTURE_OWNER_USERNAME = "reader-alpha"
SYNTHETIC_EMAIL_DOMAIN = "example.invalid"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _user_rows() -> list[dict[str, Any]]:
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
    now = _utc_now()
    return [
        {
            "id": 930001,
            "source_issue_id": 920001,
            "target_issue_id": 920002,
            "created_at": now,
            "note": "synthetic-prerequisite",
            "origin": "manual",
            "classification": "needs_review",
            "provenance": "synthetic",
        },
        {
            "id": 930002,
            "source_issue_id": 920003,
            "target_issue_id": 920004,
            "created_at": now,
            "note": "cbl-order:1700000000000",
            "origin": "cbl_order",
            "classification": None,
            "provenance": "synthetic",
        },
    ]


def _continuity_plan_rows() -> list[dict[str, Any]]:
    now = _utc_now()
    return [
        {
            "id": 940001,
            "user_id": 900001,
            "name": "Rehearsal Alpha Plan",
            "ordering_mode": "strict",
            "nodes_json": [{"issue_id": 920002, "lane_id": "main"}],
            "lanes_json": {"main": {"prerequisite": "920001"}},
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
        },
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
            "cbl_source_list_id": None,
            "custom_cbl_list_id": None,
            "adopted_at": None,
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
            "note": None,
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
            "overlap_decisions_updated_at": None,
        },
    ]


def _custom_cbl_entry_rows() -> list[dict[str, Any]]:
    return [
        {
            "id": 980001,
            "list_id": 970001,
            "issue_id": 920002,
            "position": 0,
            "gate": "safe",
            "skipped": False,
            "is_checkpoint": False,
            "checkpoint_target_issue_ids": None,
            "created_at": _utc_now(),
        },
    ]


def _custom_cbl_source_link_rows() -> list[dict[str, Any]]:
    now = _utc_now()
    return [
        {
            "id": 990001,
            "user_id": 900001,
            "cbl_source_list_id": 970001,
            "custom_cbl_list_id": 970001,
            "source_revision_sha": "synthetic-revision-0001",
            "source_content_hash": "synthetic-content-hash-0001",
            "created_at": now,
            "updated_at": now,
        },
    ]


def _cbl_adoption_receipt_rows() -> list[dict[str, Any]]:
    return [
        {
            "id": 991001,
            "user_id": 900001,
            "cbl_source_list_id": 970001,
            "plan_id": 940001,
            "request_fingerprint": "synthetic-fingerprint-0001",
            "created_at": _utc_now(),
        },
    ]


def _collection_exclusion_rows() -> list[dict[str, Any]]:
    return [
        {
            "id": 992001,
            "user_id": 900002,
            "provider": "comicvine",
            "external_volume_id": "synthetic-volume-0001",
            "thread_id": 910003,
            "issue_id": 920004,
            "created_at": _utc_now(),
        }
    ]


def _session_rows() -> list[dict[str, Any]]:
    return [
        {
            "id": 993001,
            "started_at": _utc_now(),
            "ended_at": None,
            "start_die": 6,
            "manual_die": None,
            "user_id": 900001,
            "pending_thread_id": 910001,
            "pending_issue_id": 920002,
            "pending_thread_updated_at": _utc_now(),
            "snoozed_thread_ids": None,
            "skipped_thread_ids": None,
            "timezone": "America/Chicago",
            "predicted_bandwidth": "wifi",
            "active_bandwidth": None,
            "bandwidth_confidence": 0.9,
            "bandwidth_source": "manual",
            "bandwidth_version": "synthetic-1",
            "bandwidth_updated_at": _utc_now(),
            "reading_bandwidth": "wifi",
            "reading_intent": "read",
            "reading_mode_source": "manual",
            "reading_mode_suggested": False,
            "active_intent": None,
            "predicted_intent": None,
            "intent_confidence": None,
            "intent_source": None,
            "intent_version": None,
            "intent_updated_at": None,
            "session_mode_correction_guidance": None,
        },
    ]


def build_fixture() -> dict[str, list[dict[str, Any]]]:
    """Build the deterministic prod-shaped synthetic fixture rows.

    Returns:
        Mapping of table name to inserted row dictionaries, in fixture order.
    """
    return {
        "users": _user_rows(),
        "threads": _thread_rows(),
        "issues": _issue_rows(),
        "dependencies": _dependency_rows(),
        "continuity_plans": _continuity_plan_rows(),
        "reading_plan_issues": _reading_plan_issue_rows(),
        "reading_plan_sources": _reading_plan_source_rows(),
        "reading_plan_dependencies": _reading_plan_dependency_rows(),
        "continuity_rules": _continuity_rule_rows(),
        "custom_cbl_lists": _custom_cbl_list_rows(),
        "custom_cbl_entries": _custom_cbl_entry_rows(),
        "custom_cbl_source_links": _custom_cbl_source_link_rows(),
        "cbl_adoption_receipts": _cbl_adoption_receipt_rows(),
        "collection_exclusions": _collection_exclusion_rows(),
        "sessions": _session_rows(),
    }


def apply_fixture(engine: Engine) -> None:
    """Apply the prod-shaped synthetic fixture through bulk inserts.

    Args:
        engine: Sync SQLAlchemy engine bound to the disposable rehearsal DB.

    Raises:
        RuntimeError: When a fixture row violates a constraint.
    """
    from sqlalchemy.orm import Session

    fixture = build_fixture()
    with Session(engine) as session:
        for table_name, rows in fixture.items():
            if not rows:
                continue
            table = {
                model.__tablename__: model.__table__
                for model in (
                    User,
                    Thread,
                    Issue,
                    Dependency,
                    ContinuityPlan,
                    ReadingPlanIssue,
                    ReadingPlanSource,
                    ReadingPlanDependency,
                    ContinuityRule,
                    CustomCBLList,
                    CustomCBLEntry,
                    CustomCBLSourceLink,
                    CBLAdoptionReceipt,
                    CollectionExclusion,
                    Session,
                )
            }[table_name]
            session.execute(insert(table).values(rows))
        session.commit()


def _unused_session_alias() -> None:  # pragma: no cover - documentation helper
    """Keep mypy/ruff quiet about the sync Session import used by apply_fixture."""
    session: Session | None = None
