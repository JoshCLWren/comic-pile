#!/usr/bin/env python3
"""Seed and verify the disposable-user B.P.R.D. live UI acceptance path."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
from sqlalchemy import func, select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PRODUCTION_BRANCH_ID = "br-silent-violet-ayobfez5"
EXPECTED_BRANCH_NAME = "production"


def production_database_url() -> str:
    project_id = os.environ["NEON_PROJECT_ID"]
    api_key = os.environ["NEON_API_KEY"]
    headers = {"Accept": "application/json", "Authorization": f"Bearer {api_key}"}
    response = requests.get(
        f"https://console.neon.tech/api/v2/projects/{project_id}/branches/{PRODUCTION_BRANCH_ID}",
        headers=headers,
        timeout=30,
    )
    response.raise_for_status()
    branch = response.json()["branch"]
    assert branch["id"] == PRODUCTION_BRANCH_ID and branch["name"] == EXPECTED_BRANCH_NAME
    assert branch["default"] is True and branch["primary"] is True

    response = requests.get(
        f"https://console.neon.tech/api/v2/projects/{project_id}/connection_uri",
        headers=headers,
        params={"branch_id": PRODUCTION_BRANCH_ID, "database_name": "neondb", "role_name": "neondb_owner"},
        timeout=30,
    )
    response.raise_for_status()
    parts = urlsplit(response.json()["uri"])
    query: list[tuple[str, str]] = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key == "channel_binding":
            continue
        query.append(("ssl" if key == "sslmode" else key, value))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def configure_database() -> None:
    os.environ["DATABASE_URL"] = production_database_url()
    os.environ["ENVIRONMENT"] = "development"


async def seed(username: str) -> dict[str, int]:
    configure_database()
    from app.database import AsyncSessionLocal
    from app.models.continuity_plan import ContinuityPlan
    from app.models.issue import Issue
    from app.models.thread import Thread
    from app.models.user import User
    from app.schemas.continuity_plan import ContinuityPlanNode
    from app.services.continuity_plan_writer import replace_compiled_rules, validate_node_ownership
    from app.services.issue_tracking import apply_thread_issue_tracking_state
    from comic_pile.dependencies import refresh_user_blocked_status

    async with AsyncSessionLocal() as db:
        user = await db.scalar(select(User).where(User.username == username))
        assert user is not None
        assert await db.scalar(select(func.count()).select_from(Thread).where(Thread.user_id == user.id)) == 0
        assert await db.scalar(select(func.count()).select_from(ContinuityPlan).where(ContinuityPlan.user_id == user.id)) == 0
        thread = Thread(
            user_id=user.id,
            title="B.P.R.D. Acceptance Gate",
            format="comic",
            queue_position=1,
            status="active",
            total_issues=1,
            issues_remaining=1,
            reading_progress="not_started",
            created_at=datetime.now(UTC),
        )
        db.add(thread)
        await db.flush()
        issue = Issue(thread_id=thread.id, issue_number="gate", position=1, status="unread")
        db.add(issue)
        await db.flush()
        apply_thread_issue_tracking_state(thread, [issue])
        node = ContinuityPlanNode(
            id=f"issue-{issue.id}",
            node_type="issue",
            ref_id=issue.id,
            lane_id="main",
            position=0,
            is_checkpoint=False,
            convergence_gate=[],
        )
        await validate_node_ownership(db, user_id=user.id, nodes=[node])
        plan = ContinuityPlan(
            user_id=user.id,
            name="B.P.R.D.",
            ordering_mode="strict_sequential",
            lanes_json=[{"id": "main", "name": "Reading order", "order": 0}],
            nodes_json=[node.model_dump()],
        )
        db.add(plan)
        await db.flush()
        await replace_compiled_rules(db, user_id=user.id, plan=plan, nodes=[node], ordering_mode="strict_sequential")
        await refresh_user_blocked_status(user.id, db)
        await db.commit()
        return {"user_id": user.id, "plan_id": plan.id, "gate_thread_id": thread.id}


async def verify(username: str, plan_id: int, gate_thread_id: int) -> dict[str, object]:
    configure_database()
    from app.database import AsyncSessionLocal
    from app.models.continuity_plan import ContinuityPlan
    from app.models.continuity_rule import ContinuityRule
    from app.models.thread import Thread
    from app.models.user import User
    from comic_pile.queue import get_roll_pool

    async with AsyncSessionLocal() as db:
        user = await db.scalar(select(User).where(User.username == username))
        assert user is not None
        plan = await db.get(ContinuityPlan, plan_id)
        assert plan is not None and plan.user_id == user.id
        assert plan.ordering_mode == "strict_sequential"
        assert len(plan.nodes_json or []) == 16
        assert {str(node.get("lane_id")) for node in plan.nodes_json or []} == {"main"}
        rule_count = await db.scalar(
            select(func.count()).select_from(ContinuityRule).where(
                ContinuityRule.user_id == user.id,
                ContinuityRule.note == f"continuity-plan:{plan.id}",
            )
        )
        assert rule_count == 15
        expected_titles = [
            "CBL: B.P.R.D.: The Universal Machine",
            "CBL: B.P.R.D.: Garden of Souls",
            "CBL: B.P.R.D.: Killing Ground",
        ]
        threads = list(
            (
                await db.execute(
                    select(Thread)
                    .where(Thread.user_id == user.id, Thread.title.in_(expected_titles))
                    .order_by(Thread.queue_position)
                )
            )
            .scalars()
            .all()
        )
        assert len(threads) == 3
        pool_ids = [item.id for item in await get_roll_pool(user.id, db)]
        assert pool_ids == [gate_thread_id], pool_ids
        return {
            "user_id": user.id,
            "plan_id": plan.id,
            "nodes": len(plan.nodes_json or []),
            "compiled_rules": rule_count,
            "materialized_threads": [thread.title for thread in threads],
            "roll_pool_thread_ids": pool_ids,
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="command", required=True)
    seed_parser = subs.add_parser("seed")
    seed_parser.add_argument("username")
    verify_parser = subs.add_parser("verify")
    verify_parser.add_argument("username")
    verify_parser.add_argument("plan_id", type=int)
    verify_parser.add_argument("gate_thread_id", type=int)
    args = parser.parse_args()
    result = asyncio.run(seed(args.username)) if args.command == "seed" else asyncio.run(verify(args.username, args.plan_id, args.gate_thread_id))
    print(json.dumps(result))


if __name__ == "__main__":
    main()
