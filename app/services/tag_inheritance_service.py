"""Additive effective-tag inheritance across threads, issues, and Reading Plans.

Implements issue #3031: effective tags are the union of the tags directly
assigned to an object and the tags inherited through every supported v1 parent
path. Inheritance is strictly additive — there are no negative assignments
and no child override or negation mechanism.

Supported v1 parent paths:

- ``Thread -> Issue``: an issue inherits tags directly assigned to its thread.
- ``Reading Plan -> Issue``: every canonical issue that is a member of a
  Reading Plan inherits the plan's tags. Membership alone establishes
  inheritance; dependency direction and ordering inside the plan do not
  change it.

Threads and Reading Plans have no parents in v1, so their effective tags are
exactly their directly assigned tags. The same tag inherited through multiple
paths appears once but retains every contributing source, so the UI can
navigate to each source and removing one source never misleadingly implies
the tag disappears.

Privacy follows the tag governance rules from #3030: a viewer sees global
tags plus their own private tags. Private tags owned by anyone else are
filtered before inheritance is computed, and only plans owned by the viewer
contribute inheritance, so one user's plan existence never leaks through
another user's effective tags. The service relies on the #3037 invariant
that a canonical issue occurs at most once per Reading Plan and performs no
duplicate-occurrence compatibility handling.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Tag, User
from app.repositories import (
    continuity_repository,
    issue_repository,
    reading_plan_repository,
    tag_repository,
    thread_repository,
)
from app.services.errors import NotFoundError


@dataclass
class InheritanceSource:
    """One object responsible for an effective tag.

    Attributes:
        target_type: Polymorphic target type (``"Issue"``, ``"Thread"``, or
            ``"ContinuityPlan"``).
        target_id: Primary key of the source object.
        display_name: Human-readable label for navigation (thread title, plan
            name, or issue number).
    """

    target_type: str
    target_id: int
    display_name: str


@dataclass
class EffectiveTag:
    """One deduplicated effective tag with every contributing source.

    Attributes:
        tag: The tag itself.
        direct: ``True`` when the tag is directly assigned to the queried
            object (it may additionally be inherited).
        sources: Every object whose direct assignment contributes this tag,
            including the queried object itself for direct assignments.
    """

    tag: Tag
    direct: bool
    sources: list[InheritanceSource] = field(default_factory=list)


@dataclass
class EffectiveTagsResult:
    """Direct and effective tags for one object.

    Attributes:
        target_type: Polymorphic target type of the queried object.
        target_id: Primary key of the queried object.
        direct_tags: Tags directly assigned to the object and visible to the
            viewer.
        effective_tags: Union of direct and inherited visible tags,
            deduplicated by tag with all contributing sources retained.
    """

    target_type: str
    target_id: int
    direct_tags: list[Tag]
    effective_tags: list[EffectiveTag]


def _combine_assignments(
    *,
    self_type: str,
    self_id: int,
    pairs: list[tuple[Tag, str, int, str]],
) -> EffectiveTagsResult:
    """Combine visible assignments into direct and effective tag views.

    Args:
        self_type: Target type of the queried object.
        self_id: Primary key of the queried object.
        pairs: ``(tag, source_type, source_id, display_name)`` rows for every
            visible assignment that contributes to the result, including the
            object's own direct assignments.

    Returns:
        The combined direct and effective tag result.
    """
    by_tag_id: dict[int, EffectiveTag] = {}
    order: list[int] = []
    for tag, source_type, source_id, display_name in pairs:
        entry = by_tag_id.get(tag.id)
        if entry is None:
            entry = EffectiveTag(tag=tag, direct=False, sources=[])
            by_tag_id[tag.id] = entry
            order.append(tag.id)
        if source_type == self_type and source_id == self_id:
            entry.direct = True
        entry.sources.append(
            InheritanceSource(
                target_type=source_type,
                target_id=source_id,
                display_name=display_name,
            )
        )
    effective = [by_tag_id[tag_id] for tag_id in order]
    direct = [entry.tag for entry in effective if entry.direct]
    return EffectiveTagsResult(
        target_type=self_type,
        target_id=self_id,
        direct_tags=direct,
        effective_tags=effective,
    )


class TagInheritanceService:
    """Computes explainable effective tags for taggable objects.

    The service enforces target ownership (a viewer only resolves effective
    tags for objects they own) and the tag visibility boundary (global tags
    plus the viewer's own private tags). HTTP status mapping lives in the
    routers.
    """

    def __init__(self, db: AsyncSession) -> None:
        """Initialize the inheritance service.

        Args:
            db: Database session.
        """
        self._db = db

    async def get_issue_effective_tags(
        self, user: User, issue_id: int
    ) -> EffectiveTagsResult:
        """Return direct and effective tags for one owned issue.

        Effective tags union the issue's direct tags, its thread's tags, and
        the tags of every Reading Plan owned by the viewer that contains the
        issue. Tags inherited through several paths appear once with all of
        their sources retained.

        Args:
            user: The requesting user; must own the issue's thread.
            issue_id: Primary key of the issue.

        Returns:
            The direct and effective tags for the issue.

        Raises:
            NotFoundError: When the issue does not exist or is not owned by
                the user.
        """
        issue = await issue_repository.find_owned(self._db, user.id, issue_id)
        if issue is None:
            raise NotFoundError(f"Issue {issue_id} does not exist")
        thread_id = issue.thread_id
        issue_number = issue.issue_number

        thread = await thread_repository.find_owned(self._db, user.id, thread_id)
        if thread is None:
            raise NotFoundError(f"Issue {issue_id} does not exist")
        thread_title = thread.title

        plans = await reading_plan_repository.plans_containing_issue_for_user(
            self._db, issue_id=issue_id, user_id=user.id
        )
        plan_names = {plan.id: plan.name for plan in plans}

        targets: list[tuple[str, int]] = [("Issue", issue_id), ("Thread", thread_id)]
        targets.extend(("ContinuityPlan", plan_id) for plan_id in plan_names)
        pairs = await tag_repository.list_visible_assignments_for_targets(
            self._db, user.id, targets
        )

        display_names = {("Issue", issue_id): f"#{issue_number}"}
        display_names[("Thread", thread_id)] = thread_title
        for plan_id, plan_name in plan_names.items():
            display_names[("ContinuityPlan", plan_id)] = plan_name
        rows = [
            (tag, assignment.target_type, assignment.target_id, display_names[
                (assignment.target_type, assignment.target_id)
            ])
            for tag, assignment in pairs
        ]
        return _combine_assignments(
            self_type="Issue", self_id=issue_id, pairs=rows
        )

    async def get_thread_effective_tags(
        self, user: User, thread_id: int
    ) -> EffectiveTagsResult:
        """Return direct and effective tags for one owned thread.

        Threads have no parents in v1, so effective tags are exactly the
        directly assigned visible tags.

        Args:
            user: The requesting user; must own the thread.
            thread_id: Primary key of the thread.

        Returns:
            The direct and effective tags for the thread.

        Raises:
            NotFoundError: When the thread does not exist or is not owned by
                the user.
        """
        thread = await thread_repository.find_owned(self._db, user.id, thread_id)
        if thread is None:
            raise NotFoundError(f"Thread {thread_id} does not exist")

        pairs = await tag_repository.list_visible_assignments_for_targets(
            self._db, user.id, [("Thread", thread_id)]
        )
        rows = [
            (tag, "Thread", thread_id, thread.title) for tag, _assignment in pairs
        ]
        return _combine_assignments(
            self_type="Thread", self_id=thread_id, pairs=rows
        )

    async def get_plan_effective_tags(
        self, user: User, plan_id: int
    ) -> EffectiveTagsResult:
        """Return direct and effective tags for one owned Reading Plan.

        Reading Plans have no parents in v1, so effective tags are exactly
        the directly assigned visible tags.

        Args:
            user: The requesting user; must own the plan.
            plan_id: Primary key of the plan.

        Returns:
            The direct and effective tags for the plan.

        Raises:
            NotFoundError: When the plan does not exist or is not owned by
                the user.
        """
        plan = await continuity_repository.get_continuity_plan(
            self._db, user.id, plan_id
        )
        if plan is None:
            raise NotFoundError(f"Reading Plan {plan_id} does not exist")

        pairs = await tag_repository.list_visible_assignments_for_targets(
            self._db, user.id, [("ContinuityPlan", plan_id)]
        )
        rows = [
            (tag, "ContinuityPlan", plan_id, plan.name)
            for tag, _assignment in pairs
        ]
        return _combine_assignments(
            self_type="ContinuityPlan", self_id=plan_id, pairs=rows
        )
