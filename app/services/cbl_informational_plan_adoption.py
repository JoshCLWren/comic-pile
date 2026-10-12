"""Held: imported X-Men/FF CBL lists must not be adopted as plans.

Never having adopted a strict ContinuityPlan is not evidence of
informational mode. The importer used to omit unmatched entries and pick
the lowest issue id on a duplicate identity. That path is closed.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_plan import ContinuityPlan


class InformationalCblAdoptionError(ValueError):
    """Raised when informational CBL adoption is requested while held."""


async def adopt_cbl_list_as_informational_plan(
    db: AsyncSession,
    *,
    user_id: int,
    source_list_id: int,
    plan_name: str,
) -> ContinuityPlan:
    """Refuse to adopt X-Men/FF CBL lists as informational plans.

    Args:
        db: Unused; kept so call sites fail in place instead of writing.
        user_id: Unused plan owner.
        source_list_id: Unused CBL list id.
        plan_name: Unused plan name.

    Returns:
        Never returns.

    Raises:
        InformationalCblAdoptionError: Always. Use
            ``report_cbl_source_identity_resolution`` instead.
    """
    del db, user_id, source_list_id, plan_name
    raise InformationalCblAdoptionError(
        "X-Men/FF CBL lists must not be adopted while unmatched or "
        "multi-matched identities remain; never omit silently and never "
        "pick the lowest issue id. Report candidates with "
        "report_cbl_source_identity_resolution. Never having adopted a "
        "strict plan is not evidence of informational mode."
    )
