"""Transactional, idempotent commit of user-approved ComicVine series mappings.

This is the write half of the read-only series-mapping preview contract (issue #2721). A
caller approves only rows the preview classified ``safe_exact_match``, referencing the signed
preview token that proves which scope, series, and issue set it saw.

Commit never trusts the token or the caller as a substitute for database revalidation:

1. the token signature, user binding, and 10-minute TTL are verified;
2. the idempotency receipt for the key is consulted first so an identical retry replays the
   same logical result without duplicating confirmed identities;
3. the current plan is rebuilt from the database and its state digest must equal the digest the
   token bound, otherwise the preview is stale;
4. every approved row must still resolve to a locally owned issue the preview classified as a
   safe exact match, and no approved row may conflict with an existing confirmed mapping;
5. all identity writes and the idempotency receipt commit in one transaction, so any failure
   leaves no partial writes;
6. metadata hydration is handed off only after that transaction commits, so a hydration failure
   never rolls back a confirmed identity.

Idempotency is durable (``catalog_commit_receipts``) rather than process memory, so concurrent
API workers converge: the loser of the unique-constraint race rolls back its own writes and
replays the winning receipt.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Sequence

from fastapi import status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.external_identities import (
    USER_SERIES_CONFIRMATION_EVIDENCE_SOURCE,
    link_issue_external_identity,
    link_thread_external_series,
    upsert_external_identity,
)
from app.repositories.catalog_commit_repository import (
    find_commit_receipt,
    insert_commit_receipt,
    list_confirmed_issue_identities,
    list_owned_issue_ids,
)
from app.services.catalog import (
    build_series_mapping_plan,
    upsert_catalog_series,
    verify_preview_token,
)

logger = logging.getLogger(__name__)

COMMIT_ENDPOINT = "catalog_series_mapping_commit"
"""Logical endpoint name recorded with each durable idempotency receipt."""

BULK_SAFE_CLASSIFICATION = "safe_exact_match"
"""The only preview classification a caller may bulk-approve."""

LEFTOVER_CLASSIFICATIONS = (
    "needs_review_ambiguous",
    "needs_review_conflict",
    "unresolved",
    "excluded_special",
)
"""Classifications that stay needs-review and continue through issue-level correction."""

ERROR_PREVIEW_STALE = "preview_stale"
ERROR_PREVIEW_EXPIRED = "preview_expired"
ERROR_CONFIRMED_MAPPING_CONFLICT = "confirmed_mapping_conflict"
ERROR_IDEMPOTENCY_CONFLICT = "idempotency_conflict"
ERROR_INVALID_APPROVED_ROW = "invalid_approved_row"


class SeriesMappingCommitConflictError(Exception):
    """Raised when a commit is refused before any identity write happens."""

    def __init__(self, code: str, *, status_code: int = status.HTTP_409_CONFLICT) -> None:
        """Record the contract error code and HTTP status to surface.

        Args:
            code: Contract error code such as ``preview_stale``.
            status_code: HTTP status the router maps the refusal onto.
        """
        super().__init__(code)
        self.code = code
        self.status_code = status_code


async def commit_series_mapping(
    db: AsyncSession,
    *,
    user_id: int,
    preview_token: str,
    idempotency_key: str,
    approved_row_ids: Sequence[str],
) -> dict[str, object]:
    """Confirm the approved safe mappings for one preview and hand off hydration.

    Args:
        db: Async database session; this service owns the transaction boundary.
        user_id: Authenticated user ID.
        preview_token: Signed, user-bound preview token from the preview endpoint.
        idempotency_key: Caller key applied to the complete material commit request.
        approved_row_ids: Preview row ids the caller approved.

    Returns:
        Logical commit result: ``idempotency_key``, ``confirmed_issue_ids``,
        ``already_confirmed_issue_ids``, ``needs_review_issue_ids``,
        ``hydration_queued_issue_ids``, and ``series_mapping``.

    Raises:
        SeriesMappingCommitConflictError: For every contract refusal (stale preview, expired preview,
            confirmed-mapping conflict, idempotency conflict, invalid approved row). No identity
            write has been committed when this is raised.
    """
    normalized_key = idempotency_key.strip()
    if not normalized_key:
        raise SeriesMappingCommitConflictError(ERROR_IDEMPOTENCY_CONFLICT)

    canonical_rows = _canonical_row_ids(approved_row_ids)
    fingerprint = _request_fingerprint(preview_token, canonical_rows)

    payload = verify_preview_token(
        preview_token,
        expected_user_id=user_id,
        expiry_status_code=status.HTTP_409_CONFLICT,
        expiry_detail=ERROR_PREVIEW_EXPIRED,
    )

    # Idempotency is resolved before revalidation so a retry of an already committed request
    # replays its result even though committing it necessarily changed the bound state.
    replay = await _replay_receipt(db, user_id=user_id, idempotency_key=normalized_key, fingerprint=fingerprint)
    if replay is not None:
        return replay

    provider = str(payload.get("provider") or "")
    series_external_id = str(payload.get("provider_series_external_id") or "")
    origin_issue_id = payload.get("origin_issue_id")
    if not isinstance(origin_issue_id, int) or not provider or not series_external_id:
        raise SeriesMappingCommitConflictError(ERROR_PREVIEW_STALE)

    plan = await build_series_mapping_plan(
        db,
        user_id=user_id,
        origin_issue_id=origin_issue_id,
        provider=provider,
        provider_series_external_id=series_external_id,
    )
    scope_status = _plan_scope_status(plan)
    plan_rows = _plan_rows(plan)

    if (
        scope_status != "available"
        or plan.get("scope_key") != payload.get("scope_key")
        or plan.get("state_digest") != payload.get("classification_digest")
    ):
        # A concurrent identical attempt may have committed between the receipt lookup and this
        # revalidation. Converge on its stored result instead of reporting a spurious stale.
        replay = await _replay_receipt(
            db, user_id=user_id, idempotency_key=normalized_key, fingerprint=fingerprint
        )
        if replay is not None:
            return replay
        raise SeriesMappingCommitConflictError(ERROR_PREVIEW_STALE)

    rows_by_id = {str(row.get("row_id")): row for row in plan_rows}
    approved_rows = [_resolve_approved_row(row_id, rows_by_id) for row_id in canonical_rows]

    await _assert_approved_issues_owned(db, user_id=user_id, approved_rows=approved_rows)
    await _assert_no_confirmed_mapping_conflict(db, approved_rows=approved_rows)

    response = await _apply_identity_writes(
        db,
        user_id=user_id,
        approved_rows=approved_rows,
        provider=provider,
        series_external_id=series_external_id,
        idempotency_key=normalized_key,
        request_fingerprint=fingerprint,
        rows=plan_rows,
    )

    hydration_targets = [
        int(row["_identity_id"]) for row in approved_rows if row.get("_identity_id") is not None
    ]
    await _hydrate_after_commit(
        user_id=user_id,
        identity_ids=hydration_targets,
    )

    return response


def _plan_rows(plan: dict[str, object]) -> list[dict[str, object]]:
    """Return the plan's classified rows as plain dicts in their deterministic order."""
    raw_rows = plan.get("rows")
    if not isinstance(raw_rows, list):
        return []
    return [row for row in raw_rows if isinstance(row, dict)]


def _plan_scope_status(plan: dict[str, object]) -> str:
    """Return the plan's scope status, or an empty string when it is malformed."""
    scope = plan.get("scope")
    if not isinstance(scope, dict):
        return ""
    status_value = scope.get("status")
    return status_value if isinstance(status_value, str) else ""


def _canonical_row_ids(approved_row_ids: Sequence[str]) -> list[str]:
    """Return approved row ids in a canonical, order-independent form.

    The idempotency key applies to the complete material request, so ``["issue:2","issue:1"]``
    and ``["issue:1","issue:2","issue:1"]`` are the same material request.
    """
    return sorted({row_id.strip() for row_id in approved_row_ids if row_id.strip()})


def _request_fingerprint(preview_token: str, canonical_rows: list[str]) -> str:
    """Digest the complete material commit request for idempotency comparison."""
    material = json.dumps(
        {"preview_token": preview_token, "approved_row_ids": canonical_rows},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


async def _replay_receipt(
    db: AsyncSession,
    *,
    user_id: int,
    idempotency_key: str,
    fingerprint: str,
) -> dict[str, object] | None:
    """Return the stored result for a matching receipt, or refuse a reused key.

    Args:
        db: Async database session.
        user_id: Authenticated user ID.
        idempotency_key: Normalized caller key.
        fingerprint: Digest of the complete material commit request.

    Returns:
        The stored logical result, or ``None`` when the key has never committed.

    Raises:
        SeriesMappingCommitConflictError: When the key was already used for materially different
            input.
    """
    receipt = await find_commit_receipt(db, user_id=user_id, idempotency_key=idempotency_key)
    if receipt is None:
        return None
    stored_fingerprint = receipt.request_fingerprint
    if stored_fingerprint != fingerprint:
        logger.info(
            "catalog_series_mapping_commit idempotency_conflict user_id=%s key=%s",
            user_id,
            idempotency_key,
        )
        raise SeriesMappingCommitConflictError(ERROR_IDEMPOTENCY_CONFLICT)
    stored = receipt.response_json
    if not isinstance(stored, dict):
        raise SeriesMappingCommitConflictError(ERROR_IDEMPOTENCY_CONFLICT)
    return stored


def _resolve_approved_row(row_id: str, rows_by_id: dict[str, dict[str, object]]) -> dict[str, object]:
    """Return the current safe row for one approved row id.

    Args:
        row_id: Approved preview row id.
        rows_by_id: Current preview rows keyed by row id.

    Returns:
        The matching preview row, annotated with the identity to confirm.

    Raises:
        SeriesMappingCommitConflictError: ``invalid_approved_row`` when the row is gone, no longer a
            bulk-safe exact match, has no selected provider identity, or is a provider roster
            row that carries no ComicPile thread to attach.
    """
    row = rows_by_id.get(row_id)
    if row is None or row.get("classification") != BULK_SAFE_CLASSIFICATION:
        raise SeriesMappingCommitConflictError(
            ERROR_INVALID_APPROVED_ROW, status_code=status.HTTP_422_UNPROCESSABLE_CONTENT
        )
    issue_id = row.get("issue_id")
    provider = row.get("provider")
    external_id = row.get("external_id")
    if not isinstance(issue_id, int) or not isinstance(provider, str) or not isinstance(external_id, str):
        raise SeriesMappingCommitConflictError(
            ERROR_INVALID_APPROVED_ROW, status_code=status.HTTP_422_UNPROCESSABLE_CONTENT
        )
    if not external_id.strip():
        raise SeriesMappingCommitConflictError(
            ERROR_INVALID_APPROVED_ROW, status_code=status.HTTP_422_UNPROCESSABLE_CONTENT
        )
    if not isinstance(row.get("thread_id"), int):
        raise SeriesMappingCommitConflictError(
            ERROR_INVALID_APPROVED_ROW, status_code=status.HTTP_422_UNPROCESSABLE_CONTENT
        )
    row["_identity_id"] = None
    return row


async def _assert_approved_issues_owned(
    db: AsyncSession,
    *,
    user_id: int,
    approved_rows: Sequence[dict[str, object]],
) -> None:
    """Require every approved row to be a ComicPile issue owned by this user.

    Raises:
        SeriesMappingCommitConflictError: ``invalid_approved_row`` when any approved row is not an
            issue in one of the caller's threads.
    """
    issue_ids = [int(row["issue_id"]) for row in approved_rows]
    owned = await list_owned_issue_ids(db, user_id=user_id, issue_ids=issue_ids)
    if any(issue_id not in owned for issue_id in issue_ids):
        raise SeriesMappingCommitConflictError(
            ERROR_INVALID_APPROVED_ROW, status_code=status.HTTP_422_UNPROCESSABLE_CONTENT
        )


async def _assert_no_confirmed_mapping_conflict(
    db: AsyncSession,
    *,
    approved_rows: Sequence[dict[str, object]],
) -> None:
    """Refuse bulk confirmation that would overwrite a conflicting confirmed identity.

    Raises:
        SeriesMappingCommitConflictError: ``confirmed_mapping_conflict`` when an approved issue
            already has a confirmed mapping to a different provider identity.
    """
    issue_ids = [int(row["issue_id"]) for row in approved_rows]
    confirmed = await list_confirmed_issue_identities(db, issue_ids=issue_ids)
    for row in approved_rows:
        target = (str(row["provider"]), str(row["external_id"]))
        existing = confirmed.get(int(row["issue_id"]), set())
        if any(identity != target for identity in existing):
            logger.info(
                "catalog_series_mapping_commit confirmed_mapping_conflict issue_id=%s",
                row["issue_id"],
            )
            raise SeriesMappingCommitConflictError(ERROR_CONFIRMED_MAPPING_CONFLICT)


async def _apply_identity_writes(
    db: AsyncSession,
    *,
    user_id: int,
    approved_rows: Sequence[dict[str, object]],
    provider: str,
    series_external_id: str,
    idempotency_key: str,
    request_fingerprint: str,
    rows: Sequence[dict[str, object]],
) -> dict[str, object]:
    """Confirm every approved identity, record the receipt, and commit exactly once.

    The receipt is written inside the same transaction as the identity writes, so a failure
    anywhere leaves nothing behind and a concurrent identical attempt cannot both commit.
    """
    confirmed_issue_ids: list[int] = []
    thread_ids: list[int] = []

    for row in approved_rows:
        identity = await upsert_external_identity(
            db,
            provider=str(row["provider"]),
            entity_type="issue",
            external_id=str(row["external_id"]),
        )
        identity_id = identity.id
        mapping = await link_issue_external_identity(
            db,
            user_id=user_id,
            issue_id=int(row["issue_id"]),
            external_identity_id=identity_id,
            status="confirmed",
            evidence_source=USER_SERIES_CONFIRMATION_EVIDENCE_SOURCE,
            confidence=1.0,
        )
        # Attribute values are extracted before commit so no later access can trigger a lazy
        # load on an expired session.
        row["_identity_id"] = identity_id
        row["_mapping_id"] = mapping.id
        confirmed_issue_ids.append(int(row["issue_id"]))
        thread_id = row.get("thread_id")
        if isinstance(thread_id, int):
            thread_ids.append(thread_id)

    series_identity = await upsert_catalog_series(
        db,
        provider=provider,
        entity_type="series",
        external_id=series_external_id,
    )
    series_identity_id = series_identity.id
    for thread_id in sorted(set(thread_ids)):
        await link_thread_external_series(
            db,
            user_id=user_id,
            thread_id=thread_id,
            external_identity_id=series_identity_id,
            status="confirmed",
            evidence_source=USER_SERIES_CONFIRMATION_EVIDENCE_SOURCE,
            confidence=1.0,
        )

    response: dict[str, object] = {
        "idempotency_key": idempotency_key,
        "confirmed_issue_ids": confirmed_issue_ids,
        "already_confirmed_issue_ids": [
            int(row["issue_id"])
            for row in rows
            if isinstance(row, dict)
            and row.get("classification") == "already_confirmed"
            and isinstance(row.get("issue_id"), int)
        ],
        "needs_review_issue_ids": [
            int(row["issue_id"])
            for row in rows
            if isinstance(row, dict)
            and row.get("classification") in LEFTOVER_CLASSIFICATIONS
            and isinstance(row.get("issue_id"), int)
        ],
        "hydration_queued_issue_ids": list(confirmed_issue_ids),
        "series_mapping": {
            "provider": provider,
            "external_id": series_external_id,
            "status": "confirmed",
            "evidence_source": USER_SERIES_CONFIRMATION_EVIDENCE_SOURCE,
        },
    }

    try:
        await insert_commit_receipt(
            db,
            user_id=user_id,
            idempotency_key=idempotency_key,
            endpoint=COMMIT_ENDPOINT,
            request_fingerprint=request_fingerprint,
            response_json=response,
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        replay = await _replay_receipt(
            db, user_id=user_id, idempotency_key=idempotency_key, fingerprint=request_fingerprint
        )
        if replay is not None:
            logger.info(
                "catalog_series_mapping_commit converged_on_receipt user_id=%s key=%s",
                user_id,
                idempotency_key,
            )
            return replay
        raise

    return response


async def _hydrate_after_commit(
    *,
    user_id: int,
    identity_ids: Sequence[int],
) -> None:
    """Hand confirmed identities to existing metadata hydration after the commit.

    Hydration runs only once the identity transaction has committed and every failure is
    swallowed: a provider outage must never roll back a confirmed identity.

    Args:
        user_id: Authenticated user ID (for logging only).
        identity_ids: External identity IDs to hydrate.
    """
    if not identity_ids:
        return

    from app.services.comicvine_fallback import refresh_issue_metadata

    for identity_id in identity_ids:
        try:
            await refresh_issue_metadata(identity_id)
        except Exception as exc:
            logger.warning(
                "catalog_series_mapping_commit hydration_failed user_id=%s identity_id=%s error=%s",
                user_id,
                identity_id,
                type(exc).__name__,
            )