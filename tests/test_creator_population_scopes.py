"""Creator population-scope coverage for the #3579 analytics contract.

The headline ``Rated`` population is deliberately narrower than the series
groups: only issues where the creator held a headline-eligible role count
toward the headline summary, distribution, and Rated list, while series groups
cover every verified credited role. These tests prove the two populations stay
explicitly labeled, that every series aggregate is backed by an inspectable
drill-down, and that a multi-role issue never multiplies a count or average.

The historical Mignola/Milgrom report shapes are encoded as fixtures; this
module inspects the local persisted identities and ratings and never asserts
unavailable production provider ids.
"""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, User
from tests.test_creator_detail_api import D1, D2, D3, _confirm_identity, _make_thread, _rate

HEADLINE_ROLES = {"writer", "artist", "penciler", "inker", "colorist", "letterer"}


async def _group_by_thread(body: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """Index the detail response's series groups by their stable thread id."""
    return {group["thread_id"]: group for group in body["series_groups"]}


@pytest.mark.asyncio
async def test_series_groups_include_all_roles_while_rated_list_is_headline_only(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Headline and all-role populations diverge with explicit labels.

    One creator draws two headline-rated issues (writer) and one extra rated
    issue credited only as cover, plus a read-but-unrated issue. The Rated list
    stays at the headline sample while the series group exposes all three rated
    issues through its drill-down.
    """
    thread, issues = await _make_thread(
        async_db,
        default_user,
        title="Alpha Flight",
        issue_count=4,
        queue_position=1,
        read_through=4,
    )
    await _confirm_identity(
        async_db,
        issues[0],
        creators=[{"id": 3579, "name": "Scope Tester", "role": "writer"}],
    )
    await _confirm_identity(
        async_db,
        issues[1],
        creators=[{"id": 3579, "name": "Scope Tester", "role": "cover"}],
    )
    await _confirm_identity(
        async_db,
        issues[2],
        creators=[{"id": 3579, "name": "Scope Tester", "role": "writer, cover"}],
    )
    await _confirm_identity(
        async_db,
        issues[3],
        creators=[{"id": 3579, "name": "Scope Tester", "role": "writer"}],
    )
    await _rate(async_db, issues[0], rating=4.0, timestamp=D1)
    await _rate(async_db, issues[1], rating=5.0, timestamp=D2)
    await _rate(async_db, issues[2], rating=3.0, timestamp=D3)

    response = await auth_client.get("/api/v1/creators/creator:3579")

    assert response.status_code == 200
    body = response.json()
    assert body["rated_population_scope"] == "headline_roles_only"
    assert set(body["headline_roles"]) == HEADLINE_ROLES
    assert body["summary"]["ratings_count"] == 2
    assert body["summary"]["average_rating"] == pytest.approx(3.5)
    assert body["rating_distribution"]["sample_count"] == 2
    assert {row["issue_id"] for row in body["rated_issues"]} == {
        issues[0].id,
        issues[2].id,
    }

    groups = await _group_by_thread(body)
    group = groups[thread.id]
    assert group["population_scope"] == "all_verified_credits"
    assert group["rated_issue_count"] == 3
    assert group["average_rating"] == pytest.approx(4.0)
    assert group["read_unrated_issue_count"] == 1
    assert group["roles"] == ["cover", "writer"]
    assert group["rated_issue_count"] > body["summary"]["ratings_count"]

    drilldown = await auth_client.get(
        f"/api/v1/creators/creator:3579/series/{group['series_key']}/issues"
    )
    assert drilldown.status_code == 200
    drill = drilldown.json()
    assert drill["population_scope"] == "all_verified_credits"
    assert drill["series_key"] == group["series_key"]
    assert drill["total"] == group["rated_issue_count"] == len(drill["issues"])
    assert drill["average_rating"] == pytest.approx(group["average_rating"])
    ratings = [row["effective_rating"] for row in drill["issues"]]
    assert all(rating is not None for rating in ratings)
    assert round(sum(ratings) / len(ratings), 2) == pytest.approx(group["average_rating"])

    rows_by_id = {row["issue_id"]: row for row in drill["issues"]}
    assert set(rows_by_id) == {issue.id for issue in issues[:3]}
    assert rows_by_id[issues[1].id]["roles"] == ["cover"]
    assert rows_by_id[issues[2].id]["roles"] == ["cover", "writer"]
    assert rows_by_id[issues[2].id]["effective_rating"] == pytest.approx(3.0)


@pytest.mark.asyncio
async def test_multi_role_issue_counts_once_and_drilldown_reconciles(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A multi-role issue contributes one rating but keeps every role visible."""
    thread, issues = await _make_thread(
        async_db, default_user, title="Duo", issue_count=1, queue_position=1, read_through=1
    )
    await _confirm_identity(
        async_db,
        issues[0],
        creators=[
            {"id": 35791, "name": "Two Hats", "role": "writer"},
            {"id": 35791, "name": "Two Hats", "role": "artist"},
        ],
    )
    await _rate(async_db, issues[0], rating=4.5, timestamp=D1)

    body = (await auth_client.get("/api/v1/creators/creator:35791")).json()
    assert body["summary"]["ratings_count"] == 1
    groups = await _group_by_thread(body)
    group = groups[thread.id]
    assert group["rated_issue_count"] == 1
    assert group["average_rating"] == pytest.approx(4.5)
    assert group["roles"] == ["artist", "writer"]

    drill = (
        await auth_client.get(
            f"/api/v1/creators/creator:35791/series/{group['series_key']}/issues"
        )
    ).json()
    assert drill["total"] == 1
    assert len(drill["issues"]) == 1
    assert drill["issues"][0]["issue_id"] == issues[0].id
    assert drill["issues"][0]["roles"] == ["artist", "writer"]
    assert drill["issues"][0]["effective_rating"] == pytest.approx(4.5)


@pytest.mark.asyncio
async def test_zero_ratings_same_title_series_and_user_isolation(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Distinct local volume identities stay separate and another reader leaks nothing."""
    first_thread, first_issues = await _make_thread(
        async_db, default_user, title="Same Name", issue_count=1, queue_position=1, read_through=1
    )
    second_thread, second_issues = await _make_thread(
        async_db, default_user, title="Same Name", issue_count=1, queue_position=2, read_through=1
    )
    await _confirm_identity(
        async_db,
        first_issues[0],
        creators=[{"id": 4242, "name": "Twin Series", "role": "writer"}],
    )
    await _confirm_identity(
        async_db,
        second_issues[0],
        creators=[{"id": 4242, "name": "Twin Series", "role": "cover"}],
    )
    await _rate(async_db, first_issues[0], rating=4.0, timestamp=D1)
    await _rate(async_db, second_issues[0], rating=2.0, timestamp=D2)

    body = (await auth_client.get("/api/v1/creators/creator:4242")).json()
    assert body["summary"]["ratings_count"] == 1
    groups = await _group_by_thread(body)
    assert set(groups) == {first_thread.id, second_thread.id}
    assert groups[first_thread.id]["series_key"] != groups[second_thread.id]["series_key"]
    assert groups[first_thread.id]["thread_title"] == "Same Name"
    assert groups[second_thread.id]["thread_title"] == "Same Name"
    assert groups[first_thread.id]["rated_issue_count"] == 1
    assert groups[second_thread.id]["rated_issue_count"] == 1

    # Another reader owns the same creator id and must stay invisible.
    other_user = User(username="creator_population_other")
    async_db.add(other_user)
    await async_db.flush()
    hidden_thread, hidden_issues = await _make_thread(
        async_db, other_user, title="Hidden Run", issue_count=1, queue_position=3, read_through=1
    )
    await _confirm_identity(
        async_db,
        hidden_issues[0],
        creators=[{"id": 4242, "name": "Twin Series", "role": "writer"}],
    )
    await _rate(async_db, hidden_issues[0], rating=5.0, timestamp=D3)

    isolated = (await auth_client.get("/api/v1/creators/creator:4242")).json()
    assert set(await _group_by_thread(isolated)) == {first_thread.id, second_thread.id}
    hidden = await auth_client.get(
        f"/api/v1/creators/creator:4242/series/thread:{hidden_thread.id}/issues"
    )
    assert hidden.status_code == 404

    # A creator with only unrated credits has no headline sample and no groups.
    unrated_thread, unrated_issues = await _make_thread(
        async_db, default_user, title="Unrated", issue_count=1, queue_position=4
    )
    await _confirm_identity(
        async_db,
        unrated_issues[0],
        creators=[{"id": 4243, "name": "No Ratings", "role": "writer"}],
    )
    unrated = (await auth_client.get("/api/v1/creators/creator:4243")).json()
    assert unrated["summary"]["ratings_count"] == 0
    assert unrated["summary"]["average_rating"] is None
    assert unrated["series_groups"] == []
    unrated_drill = await auth_client.get(
        f"/api/v1/creators/creator:4243/series/thread:{unrated_thread.id}/issues"
    )
    assert unrated_drill.status_code == 404


@pytest.mark.asyncio
async def test_known_report_shapes_regress_without_rating_writes(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Reproduce the Mignola/Milgrom divergence shapes without mutating ratings.

    Mignola's reported page showed 43 headline-rated issues but series groups
    summing to 47, with Alpha Flight at 2 issues / 3.25 and WAR ON FROGS at
    5 issues / 3.8 while only 3 of its issues appeared in the Rated list. The
    fixture encodes that reported shape: 40 headline-rated main-run issues plus
    3 headline-rated WAR issues (43 total) and 4 non-headline rated credits
    (2 Alpha Flight, 2 WAR) that appear only through series drill-downs.

    Milgrom's report was a headline credit in one series and a non-headline
    credit in another; the second half of this test verifies that same
    divergence contract on the local canonical thread identities.
    """
    mignola = 1672
    main_thread, main_issues = await _make_thread(
        async_db,
        default_user,
        title="Mignolaverse Main",
        issue_count=40,
        queue_position=1,
        read_through=40,
    )
    for issue in main_issues:
        await _confirm_identity(
            async_db,
            issue,
            creators=[{"id": mignola, "name": "Mike Mignola", "role": "writer"}],
        )
        await _rate(async_db, issue, rating=4.0, timestamp=D1)

    alpha_thread, alpha_issues = await _make_thread(
        async_db,
        default_user,
        title="Alpha Flight",
        issue_count=2,
        queue_position=2,
        read_through=2,
    )
    for issue, rating in zip(alpha_issues, (3.0, 3.5), strict=True):
        await _confirm_identity(
            async_db,
            issue,
            creators=[{"id": mignola, "name": "Mike Mignola", "role": "cover"}],
        )
        await _rate(async_db, issue, rating=rating, timestamp=D1)

    war_thread, war_issues = await _make_thread(
        async_db,
        default_user,
        title="B.P.R.D.: WAR ON FROGS",
        issue_count=5,
        queue_position=3,
        read_through=5,
    )
    war_roles_and_ratings = (
        ("writer", 4.0),
        ("writer", 4.0),
        ("writer", 3.0),
        ("cover", 4.0),
        ("cover", 4.0),
    )
    for issue, (role, rating) in zip(war_issues, war_roles_and_ratings, strict=True):
        await _confirm_identity(
            async_db,
            issue,
            creators=[{"id": mignola, "name": "Mike Mignola", "role": role}],
        )
        await _rate(async_db, issue, rating=rating, timestamp=D1)

    # Milgrom report shape: one headline credit, one non-headline credit.
    milgrom = 1673
    daredevil_thread, daredevil_issues = await _make_thread(
        async_db, default_user, title="Daredevil", issue_count=1, queue_position=4, read_through=1
    )
    spectacular_thread, spectacular_issues = await _make_thread(
        async_db,
        default_user,
        title="Peter Parker, The Spectacular Spider-Man",
        issue_count=1,
        queue_position=5,
        read_through=1,
    )
    await _confirm_identity(
        async_db,
        daredevil_issues[0],
        creators=[{"id": milgrom, "name": "Al Milgrom", "role": "writer"}],
    )
    await _confirm_identity(
        async_db,
        spectacular_issues[0],
        creators=[{"id": milgrom, "name": "Al Milgrom", "role": "cover"}],
    )
    await _rate(async_db, daredevil_issues[0], rating=4.0, timestamp=D2)
    await _rate(async_db, spectacular_issues[0], rating=3.0, timestamp=D2)

    event_count_before = (
        await async_db.execute(select(func.count(Event.id)).where(Event.type == "rate"))
    ).scalar_one()

    body = (await auth_client.get(f"/api/v1/creators/creator:{mignola}")).json()
    groups = await _group_by_thread(body)
    assert body["summary"]["ratings_count"] == 43
    assert body["rated_population_scope"] == "headline_roles_only"
    assert sum(group["rated_issue_count"] for group in body["series_groups"]) == 47
    assert groups[alpha_thread.id]["rated_issue_count"] == 2
    assert groups[alpha_thread.id]["average_rating"] == pytest.approx(3.25)
    assert groups[war_thread.id]["rated_issue_count"] == 5
    assert groups[war_thread.id]["average_rating"] == pytest.approx(3.8)
    assert groups[main_thread.id]["rated_issue_count"] == 40
    rated_thread_ids = {row["thread_id"] for row in body["rated_issues"]}
    assert alpha_thread.id not in rated_thread_ids
    assert len([row for row in body["rated_issues"] if row["thread_id"] == war_thread.id]) == 3

    war_drill = (
        await auth_client.get(
            f"/api/v1/creators/creator:{mignola}/series/"
            f"{groups[war_thread.id]['series_key']}/issues"
        )
    ).json()
    assert war_drill["population_scope"] == "all_verified_credits"
    assert war_drill["total"] == 5
    assert war_drill["average_rating"] == pytest.approx(3.8)
    war_rows = {row["issue_id"]: row for row in war_drill["issues"]}
    assert set(war_rows) == {issue.id for issue in war_issues}
    assert len([row for row in war_rows.values() if "cover" in row["roles"]]) == 2
    assert len([row for row in war_rows.values() if "writer" in row["roles"]]) == 3

    milgrom_body = (await auth_client.get(f"/api/v1/creators/creator:{milgrom}")).json()
    milgrom_groups = await _group_by_thread(milgrom_body)
    assert milgrom_body["summary"]["ratings_count"] == 1
    assert sum(group["rated_issue_count"] for group in milgrom_body["series_groups"]) == 2
    assert milgrom_groups[daredevil_thread.id]["roles"] == ["writer"]
    assert milgrom_groups[spectacular_thread.id]["roles"] == ["cover"]
    spectacular_drill = (
        await auth_client.get(
            f"/api/v1/creators/creator:{milgrom}/series/"
            f"{milgrom_groups[spectacular_thread.id]['series_key']}/issues"
        )
    ).json()
    assert spectacular_drill["total"] == 1
    assert spectacular_drill["issues"][0]["roles"] == ["cover"]
    assert spectacular_drill["issues"][0]["effective_rating"] == pytest.approx(3.0)

    event_count_after = (
        await async_db.execute(select(func.count(Event.id)).where(Event.type == "rate"))
    ).scalar_one()
    assert event_count_after == event_count_before
