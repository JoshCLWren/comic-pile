"""Test-data flag semantics plus pruned admin routes (#4861).

The admin HTTP surface (delete-test-data, export CSV/JSON/summary) was
deleted with its router mounts because no browser caller remains. These
guards keep the non-HTTP :attr:`Thread.is_test` flag-semantics test (which
never needed the admin router) and assert every pruned admin path answers
404. The underlying admin service helpers remain for non-HTTP callers and
are not exercised through HTTP here.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Thread, User
from app.main import create_app


@pytest.mark.asyncio
async def test_seed_data_marks_as_test(async_db: AsyncSession, default_user: User) -> None:
    """Test that seeded data is marked as test data."""
    user = default_user

    thread = Thread(
        title="Test Comic",
        format="Issue",
        issues_remaining=10,
        queue_position=1,
        status="active",
        is_test=True,
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    assert thread.is_test is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/api/admin/delete-test-data/",
        "/api/v1/admin/delete-test-data/",
        "/api/admin/export/csv/",
        "/api/v1/admin/export/csv/",
        "/api/admin/export/json/",
        "/api/v1/admin/export/json/",
        "/api/admin/export/summary/",
        "/api/v1/admin/export/summary/",
    ],
)
async def test_pruned_admin_test_data_routes_return_404(
    auth_client: AsyncClient, path: str
) -> None:
    """The pruned admin test-data/export handlers answer 404."""
    response = await auth_client.post(path)
    assert response.status_code == 404


def test_pruned_admin_test_data_absent_from_openapi() -> None:
    """The pruned admin test-data paths stay out of the OpenAPI contract."""
    schema = create_app(serve_frontend=False).openapi()
    for path in (
        "/api/admin/delete-test-data/",
        "/api/v1/admin/delete-test-data/",
        "/api/admin/export/csv/",
        "/api/v1/admin/export/csv/",
        "/api/admin/export/json/",
        "/api/v1/admin/export/json/",
        "/api/admin/export/summary/",
        "/api/v1/admin/export/summary/",
    ):
        assert path not in schema["paths"], f"{path} must stay pruned"
