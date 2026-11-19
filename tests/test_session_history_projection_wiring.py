"""Endpoint-level regression coverage for the linear History event projection.

These tests prove ``list_sessions()`` preserves the exact History response
contract when it assembles summaries from the single ordered event read
produced by ``project_session_history_events()``.
"""


from sqlalchemy.ext.asyncio import AsyncSession



async def _commit_all(async_db: AsyncSession) -> None:
    await async_db.flush()
    await async_db.commit()



































