"""Regression tests for the generic Latticery domain model."""

from __future__ import annotations

from datetime import datetime, UTC


from latticery.types import Candidate, Lease, WorkNode
from latticery.lease import lease_is_expired
from latticery.stage import STAGE_PRECEDENCE, stage_order, stage_precedence
from latticery.ranking import order_candidates, sort_key


class TestCandidateOrdering:
    """Candidate ordering tests."""
    def test_sort_key_deterministic(self) -> None:
        """Test."""
        c1 = Candidate(kind="issue", number=1, lane=1, priority=3)
        assert sort_key(c1) == (1, -3, c1.created_at.timestamp(), 1)
        # Higher priority should come first (more negative second element)
        c_high = Candidate(kind="issue", number=3, lane=1, priority=5)
        ordered = order_candidates([c1, c_high])
        assert ordered[0].number == 3
        assert ordered[1].number == 1

    def test_order_candidates_stable(self) -> None:
        """Test."""
        base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        candidates = [
            Candidate(kind="issue", number=10, lane=3, priority=1, created_at=base),
            Candidate(kind="issue", number=11, lane=3, priority=2, created_at=base),
            Candidate(kind="issue", number=12, lane=1, priority=0, created_at=base),
        ]
        ordered = order_candidates(candidates)
        assert [c.number for c in ordered] == [12, 11, 10]


class TestLeaseExpiry:
    """Lease expiry tests."""
    def test_expired_after_ttl(self) -> None:
        """Test."""
        now = 1000
        assert lease_is_expired(
            "w1",
            latest_activity_epoch=500,
            now_epoch=now,
            ttl_seconds=300,
        ) is True

    def test_not_expired_before_ttl(self) -> None:
        """Test."""
        assert lease_is_expired(
            "w1",
            latest_activity_epoch=900,
            now_epoch=1000,
            ttl_seconds=300,
        ) is False

    def test_no_activity_not_expired_by_default(self) -> None:
        """Test."""
        assert lease_is_expired(
            "w1",
            latest_activity_epoch=None,
            now_epoch=10000,
            ttl_seconds=500,
        ) is False

    def test_unresolved_active_run_prevents_expiry(self) -> None:
        """Test."""
        assert lease_is_expired(
            "w1",
            latest_activity_epoch=100,
            now_epoch=99999,
            ttl_seconds=1,
            active_run_epoch=500,
        ) is False

    def test_lease_model_is_expired(self) -> None:
        """Test."""
        now = datetime(2026, 9, 23, 10, 0, 0, tzinfo=UTC)
        lease = Lease(worker="w", acquired_at=now, ttl_seconds=60, latest_activity_epoch=int(now.timestamp()) - 120)
        assert lease.is_expired(now) is True


class TestStagePrecedence:
    """Stage precedence tests."""
    def test_precedence_order(self) -> None:
        """Test."""
        assert stage_precedence("blocked") < stage_precedence("ready")
        assert stage_precedence("ready") < stage_precedence("review")
        assert stage_precedence("review") < stage_precedence("changes-requested")
        assert stage_precedence("changes-requested") < stage_precedence("ci")
        assert stage_precedence("ci") < stage_precedence("building")

    def test_stage_order_sorted(self) -> None:
        """Test."""
        shuffled = ["building", "blocked", "ready", "ci"]
        assert stage_order(shuffled) == ["blocked", "ready", "ci", "building"]

    def test_precedence_tuple_explicit(self) -> None:
        """Test."""
        assert STAGE_PRECEDENCE == ("blocked", "ready", "review", "changes-requested", "ci", "building")


class TestWorkNodeGeneric:
    """Generic work node tests."""
    def test_work_node_no_comic_pile_ids(self) -> None:
        """Test."""
        node = WorkNode(number=2871, kind="issue", labels=frozenset({"high"}))
        assert node.number == 2871
        assert "factory:" not in str(node.labels)
        assert "ralph-" not in str(node.labels)
