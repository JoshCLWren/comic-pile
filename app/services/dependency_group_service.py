"""Dependency-group orchestration for the reading-order-groups API.

Services own business rules, transaction boundaries (commit/rollback),
blocked-state refresh, and cache invalidation. Query construction and
persistence live in ``app/repositories/dependency_group_repository.py``;
HTTP status mapping lives in routers.
"""

from collections.abc import Sequence

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache_invalidation import invalidate_user_view
from app.models import DependencyGroup, DependencyGroupMembership
from app.repositories import dependency_group_repository as groups_repo
from app.schemas.dependency_group import (
    DependencyGroupCreate,
    DependencyGroupDetailMemberResponse,
    DependencyGroupDetailResponse,
    DependencyGroupIssueRangeCreate,
    DependencyGroupIssueRangeResponse,
    DependencyGroupMemberCreate,
    DependencyGroupMemberResponse,
    DependencyGroupOrderUpdate,
    DependencyGroupResponse,
    DependencyGroupSummary,
    DependencyGroupUpdate,
)
from app.schemas.issue import IssueResponse
from app.schemas.thread import ThreadResponse
from app.services.errors import ConflictError, InvalidRequestError, NotFoundError
from comic_pile.dependencies import refresh_user_blocked_status

MAX_RANGE_SIZE = 250


def _normalize_name(name: str) -> str:
    """Normalize a group name to a stripped, non-blank value.

    Args:
        name: The raw group name from a create or rename request.

    Returns:
        The stripped group name.

    Raises:
        InvalidRequestError: When the name is blank after stripping.
    """
    normalized = name.strip()
    if not normalized:
        raise InvalidRequestError("Group name must not be blank")
    return normalized


class DependencyGroupService:
    """Reading-order group orchestration for the dependency-group API."""

    def __init__(self, db: AsyncSession) -> None:
        """Initialize the service with a database session.

        Args:
            db: Async database session.
        """
        self._db = db

    async def _require_owned_group(self, group_id: int, user_id: int) -> DependencyGroup:
        """Return one owned group or raise a 404-mapped error.

        Args:
            group_id: The dependency group identifier.
            user_id: The authenticated group owner.

        Returns:
            The owned group with memberships loaded.

        Raises:
            NotFoundError: When the group does not exist or is not owned.
        """
        group = await groups_repo.find_owned_group(self._db, group_id, user_id)
        if group is None:
            raise NotFoundError(f"Group {group_id} not found")
        return group

    async def _member_responses(
        self,
        memberships: Sequence[DependencyGroupMembership],
    ) -> list[DependencyGroupMemberResponse]:
        """Resolve display metadata for memberships in two batched queries.

        Thread titles come from one query over the referenced threads; issue
        numbers and their series titles come from one joined query over the
        referenced issues. This avoids per-member lazy loads regardless of
        membership count.

        Args:
            memberships: The persisted memberships to describe.

        Returns:
            Member payloads in input order with series titles and issue
            numbers. Targets that no longer resolve keep ``None`` metadata so
            clients can render a readable fallback instead of raw database
            IDs.
        """
        thread_ids = {member.thread_id for member in memberships if member.thread_id is not None}
        issue_ids = {member.issue_id for member in memberships if member.issue_id is not None}

        thread_titles: dict[int, str] = {}
        if thread_ids:
            thread_titles = await groups_repo.thread_titles_by_id(self._db, thread_ids)

        issue_metadata: dict[int, tuple[str | None, str | None]] = {}
        if issue_ids:
            issue_metadata = await groups_repo.issue_series_metadata_by_id(self._db, issue_ids)

        responses: list[DependencyGroupMemberResponse] = []
        for member in memberships:
            if member.thread_id is not None:
                series_title = thread_titles.get(member.thread_id)
                issue_number = None
            else:
                issue_number, series_title = issue_metadata.get(member.issue_id) or (
                    None,
                    None,
                )
            responses.append(
                DependencyGroupMemberResponse(
                    id=member.id,
                    thread_id=member.thread_id,
                    issue_id=member.issue_id,
                    series_title=series_title,
                    issue_number=issue_number,
                    sequence_order=member.sequence_order,
                )
            )
        return responses

    async def _group_response(
        self,
        group: DependencyGroup,
    ) -> DependencyGroupResponse:
        """Serialize one group with enriched member display metadata.

        Args:
            group: The owned group whose memberships should be described.

        Returns:
            The group payload whose members carry resolved comic metadata.
        """
        memberships = await groups_repo.list_memberships(self._db, group.id)
        return DependencyGroupResponse(
            id=group.id,
            name=group.name,
            created_at=group.created_at,
            memberships=await self._member_responses(memberships),
        )

    async def _group_detail_response(
        self,
        group: DependencyGroup,
        user_id: int,
    ) -> DependencyGroupDetailResponse:
        """Serialize one group with enriched member, plan, and other-crossover data.

        Performs batched queries for thread, issue, and other-crossover data
        to avoid N+1 request waterfalls.

        Args:
            group: The owned group whose memberships should be described.
            user_id: The authenticated user identifier.

        Returns:
            The group payload with enriched members and linked plans.
        """
        memberships = await groups_repo.list_memberships(self._db, group.id)

        thread_ids: set[int] = set()
        issue_ids: set[int] = set()
        for member in memberships:
            if member.thread_id is not None:
                thread_ids.add(member.thread_id)
            elif member.issue_id is not None:
                issue_ids.add(member.issue_id)

        issue_to_thread: dict[int, int] = {}
        if issue_ids:
            issue_to_thread = await groups_repo.issue_parent_thread_ids(self._db, issue_ids)
            thread_ids.update(issue_to_thread.values())

        threads = await groups_repo.threads_by_id(self._db, thread_ids)
        issues = await groups_repo.issues_by_id(self._db, issue_ids)

        other_crossovers = await groups_repo.other_crossover_group_names_by_thread(
            self._db, group.id, user_id, thread_ids
        )

        enriched_members: list[DependencyGroupDetailMemberResponse] = []
        for member in memberships:
            thread = None
            issue = None
            other: list[str] = []
            if member.thread_id is not None:
                thread = threads.get(member.thread_id)
                other = other_crossovers.get(member.thread_id, [])
            elif member.issue_id is not None:
                issue = issues.get(member.issue_id)
                if issue is not None:
                    thread = threads.get(issue.thread_id)
                    other = other_crossovers.get(issue.thread_id, [])
            membership_resp = DependencyGroupMemberResponse(
                id=member.id,
                thread_id=member.thread_id,
                issue_id=member.issue_id,
                series_title=thread.title if thread else None,
                issue_number=issue.issue_number if issue else None,
                sequence_order=member.sequence_order,
            )
            thread_resp = ThreadResponse.model_validate(thread) if thread else None
            issue_resp = IssueResponse.model_validate(issue) if issue else None
            enriched_members.append(
                DependencyGroupDetailMemberResponse(
                    membership=membership_resp,
                    thread=thread_resp,
                    issue=issue_resp,
                    other_crossovers=other,
                )
            )

        linked_plans = [
            DependencyGroupSummary(id=plan_id, name=plan_name)
            for plan_id, plan_name in await groups_repo.linked_plan_summaries(
                self._db, group.id, user_id
            )
        ]
        return DependencyGroupDetailResponse(
            id=group.id,
            name=group.name,
            created_at=group.created_at,
            memberships=enriched_members,
            linked_plans=linked_plans,
        )

    async def _refresh_crossover_blocked_state(self, user_id: int) -> None:
        """Persist blocked-state changes and invalidate dependent user-scoped reads.

        Args:
            user_id: The authenticated user whose blocked state changed.
        """
        await refresh_user_blocked_status(user_id, self._db)
        await self._db.commit()
        await invalidate_user_view(user_id)

    async def list_groups(self, user_id: int) -> list[DependencyGroupResponse]:
        """List the current user's groups and memberships.

        Args:
            user_id: The authenticated owner of the requested groups.

        Returns:
            The user's groups with memberships resolved to comic metadata.
        """
        groups = await groups_repo.list_groups_for_user(self._db, user_id)
        return [await self._group_response(group) for group in groups]

    async def create_group(
        self,
        user_id: int,
        payload: DependencyGroupCreate,
    ) -> DependencyGroupResponse:
        """Create a named dependency group.

        Args:
            user_id: The authenticated group owner.
            payload: The validated group creation request.

        Returns:
            The newly created group with memberships loaded.

        Raises:
            ConflictError: When a group with this name already exists.
        """
        group = DependencyGroup(user_id=user_id, name=_normalize_name(payload.name))
        self._db.add(group)
        try:
            await self._db.commit()
        except IntegrityError as exc:
            await self._db.rollback()
            raise ConflictError("A group with this name already exists") from exc
        return await self._group_response(group)

    async def get_group(self, user_id: int, group_id: int) -> DependencyGroupResponse:
        """Return one owned group.

        Args:
            user_id: The authenticated group owner.
            group_id: The dependency group identifier.

        Returns:
            The requested owned group with memberships resolved to comic
            metadata.
        """
        return await self._group_response(await self._require_owned_group(group_id, user_id))

    async def get_group_detail(
        self,
        user_id: int,
        group_id: int,
    ) -> DependencyGroupDetailResponse:
        """Return one owned group with enriched member, plan, and project data.

        Args:
            user_id: The authenticated group owner.
            group_id: The dependency group identifier.

        Returns:
            The requested owned group with enriched member, plan, and project
            data, avoiding per-member N+1 requests.
        """
        group = await self._require_owned_group(group_id, user_id)
        return await self._group_detail_response(group, user_id)

    async def update_group(
        self,
        user_id: int,
        group_id: int,
        payload: DependencyGroupUpdate,
    ) -> DependencyGroupResponse:
        """Rename one owned group.

        Args:
            user_id: The authenticated group owner.
            group_id: The dependency group identifier.
            payload: The validated group rename request.

        Returns:
            The renamed group with memberships resolved to comic metadata.

        Raises:
            ConflictError: When a group with this name already exists.
        """
        group = await self._require_owned_group(group_id, user_id)
        group.name = _normalize_name(payload.name)
        try:
            await self._db.commit()
        except IntegrityError as exc:
            await self._db.rollback()
            raise ConflictError("A group with this name already exists") from exc
        return await self._group_response(group)

    async def delete_group(self, user_id: int, group_id: int) -> None:
        """Delete one owned group and its memberships.

        Args:
            user_id: The authenticated group owner.
            group_id: The dependency group identifier.
        """
        group = await self._require_owned_group(group_id, user_id)
        await self._db.delete(group)
        await self._db.commit()
        await self._refresh_crossover_blocked_state(user_id)

    async def list_thread_groups(
        self,
        user_id: int,
        thread_id: int,
    ) -> list[DependencyGroupSummary]:
        """List groups containing an owned thread or any of its owned issues.

        Args:
            user_id: The authenticated thread and group owner.
            thread_id: The owned thread identifier used for the lookup.

        Returns:
            Distinct group summaries ordered by name and identifier.

        Raises:
            NotFoundError: When the thread does not exist or is not owned.
        """
        thread = await groups_repo.get_owned_thread(self._db, thread_id, user_id)
        if thread is None:
            raise NotFoundError(f"Thread {thread_id} not found")
        return [
            DependencyGroupSummary(id=group_id, name=group_name)
            for group_id, group_name in await groups_repo.thread_group_summaries(
                self._db, thread_id, user_id
            )
        ]

    async def add_issue_range(
        self,
        user_id: int,
        group_id: int,
        payload: DependencyGroupIssueRangeCreate,
    ) -> DependencyGroupIssueRangeResponse:
        """Add one inclusive issue-position range from an owned thread to a group.

        Args:
            user_id: The authenticated group and thread owner.
            group_id: The dependency group identifier.
            payload: The validated issue-position range request.

        Returns:
            The idempotent range result with inserted and already-present
            issue IDs.

        Raises:
            NotFoundError: When the group or thread does not exist or is not
                owned.
            InvalidRequestError: When the range is oversized or contains
                missing positions.
        """
        await self._require_owned_group(group_id, user_id)
        thread = await groups_repo.get_owned_thread(self._db, payload.thread_id, user_id)
        if thread is None:
            raise NotFoundError(f"Thread {payload.thread_id} not found")

        range_size = payload.end_position - payload.start_position + 1
        if range_size > MAX_RANGE_SIZE:
            raise InvalidRequestError(
                f"Issue range cannot contain more than {MAX_RANGE_SIZE} positions"
            )

        issues = await groups_repo.issues_in_range(
            self._db,
            payload.thread_id,
            payload.start_position,
            payload.end_position,
        )
        expected_positions = list(range(payload.start_position, payload.end_position + 1))
        actual_positions = [issue.position for issue in issues]
        if actual_positions != expected_positions:
            missing = sorted(set(expected_positions) - set(actual_positions))
            raise InvalidRequestError(
                f"Issue range contains missing positions: {', '.join(map(str, missing))}"
            )

        issue_ids = [issue.id for issue in issues]
        added_ids = await groups_repo.insert_issue_memberships(self._db, group_id, issue_ids)
        await self._db.commit()
        await self._refresh_crossover_blocked_state(user_id)
        added_id_set = set(added_ids)

        return DependencyGroupIssueRangeResponse(
            thread_id=payload.thread_id,
            start_position=payload.start_position,
            end_position=payload.end_position,
            added_issue_ids=added_ids,
            already_present_issue_ids=[
                issue_id for issue_id in issue_ids if issue_id not in added_id_set
            ],
        )

    async def add_member(
        self,
        user_id: int,
        group_id: int,
        payload: DependencyGroupMemberCreate,
    ) -> DependencyGroupMemberResponse:
        """Add one owned thread or issue to an owned group.

        Args:
            user_id: The authenticated owner of the group and target.
            group_id: The dependency group identifier.
            payload: The validated thread or issue membership request.

        Returns:
            The newly persisted membership with resolved comic metadata.

        Raises:
            NotFoundError: When the group, thread, or issue does not exist or
                is not owned.
            InvalidRequestError: When the proposed sequence position is taken.
            ConflictError: When the member is already in the group.
        """
        await self._require_owned_group(group_id, user_id)
        if payload.thread_id is not None:
            target = await groups_repo.get_owned_thread(self._db, payload.thread_id, user_id)
            if target is None:
                raise NotFoundError(f"Thread {payload.thread_id} not found")
        else:
            issue_id = payload.issue_id
            if issue_id is None:
                raise InvalidRequestError("Exactly one of thread_id or issue_id is required")
            issue = await groups_repo.get_owned_issue(self._db, issue_id, user_id)
            if issue is None:
                raise NotFoundError(f"Issue {issue_id} not found")

        proposed_sequence = payload.sequence_order if payload.issue_id is not None else None
        if proposed_sequence is not None:
            if await groups_repo.sequence_occupied(self._db, group_id, proposed_sequence):
                raise InvalidRequestError(
                    "Each sequence_order position may appear at most once in the crossover"
                )

        member = DependencyGroupMembership(
            group_id=group_id,
            thread_id=payload.thread_id,
            issue_id=payload.issue_id,
            sequence_order=proposed_sequence,
        )
        self._db.add(member)
        try:
            await self._db.commit()
        except IntegrityError as exc:
            await self._db.rollback()
            raise ConflictError("This member is already in the group") from exc
        await self._db.refresh(member)
        response = (await self._member_responses([member]))[0]
        await self._refresh_crossover_blocked_state(user_id)
        return response

    async def set_group_order(
        self,
        user_id: int,
        group_id: int,
        payload: DependencyGroupOrderUpdate,
    ) -> DependencyGroupResponse:
        """Replace the authoritative reading order of one owned crossover.

        The payload enumerates issue-level members in their intended reading
        order; each listed issue's ``sequence_order`` is persisted verbatim
        (the provided order is the canonical source, never re-derived from
        membership ids or per-series issue positions). Any issue-level member
        not listed is cleared to unordered. Thread-level memberships are never
        sequence entries and are left untouched.

        Args:
            user_id: The authenticated owner of the group and referenced issues.
            group_id: The dependency group identifier.
            payload: The ordered issue list for the crossover.

        Returns:
            The updated group with memberships resolved to comic metadata.

        Raises:
            NotFoundError: When the group, a referenced issue, or a referenced
                issue-level membership does not exist or is not owned.
            InvalidRequestError: When an issue or position is duplicated in
                the order.
        """
        await self._require_owned_group(group_id, user_id)

        ordered_issue_ids = {item.issue_id for item in payload.items}
        ordered_positions: dict[int, int] = {
            item.issue_id: item.sequence_order for item in payload.items
        }
        if len(ordered_issue_ids) != len(payload.items):
            raise InvalidRequestError("Each crossover issue may appear at most once in the order")
        if len(set(ordered_positions.values())) != len(ordered_positions):
            raise InvalidRequestError(
                "Each sequence_order position may appear at most once in the order"
            )

        member_by_issue = await groups_repo.issue_memberships_by_issue(self._db, group_id)
        owned_issues = await groups_repo.owned_issues_by_id(self._db, ordered_issue_ids, user_id)

        for issue_id in ordered_issue_ids:
            if issue_id not in owned_issues:
                raise NotFoundError(f"Issue {issue_id} not found")
            if issue_id not in member_by_issue:
                raise NotFoundError(f"Issue {issue_id} is not a member of this crossover")

        for issue_id, membership in member_by_issue.items():
            membership.sequence_order = ordered_positions.get(issue_id)
        await self._db.commit()
        await self._refresh_crossover_blocked_state(user_id)
        return await self._group_response(await self._require_owned_group(group_id, user_id))

    async def list_crossover_plans(
        self,
        user_id: int,
        group_id: int,
    ) -> list[DependencyGroupSummary]:
        """List continuity plans containing this crossover as a node.

        Args:
            user_id: The authenticated group and plan owner.
            group_id: The dependency group identifier.

        Returns:
            Distinct plan summaries ordered by name and identifier.
        """
        await self._require_owned_group(group_id, user_id)
        return [
            DependencyGroupSummary(id=plan_id, name=plan_name)
            for plan_id, plan_name in await groups_repo.linked_plan_summaries(
                self._db, group_id, user_id
            )
        ]

    async def remove_member(
        self,
        user_id: int,
        group_id: int,
        member_id: int,
    ) -> None:
        """Remove one membership from an owned group.

        Args:
            user_id: The authenticated group owner.
            group_id: The dependency group identifier.
            member_id: The membership identifier to remove.

        Raises:
            NotFoundError: When the group or membership does not exist or is
                not owned.
        """
        await self._require_owned_group(group_id, user_id)
        member = await groups_repo.get_membership(self._db, member_id)
        if member is None or member.group_id != group_id:
            raise NotFoundError(f"Member {member_id} not found")
        await self._db.delete(member)
        await self._db.commit()
        await self._refresh_crossover_blocked_state(user_id)
