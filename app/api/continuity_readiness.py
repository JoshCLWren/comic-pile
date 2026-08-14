"""Continuity readiness evaluation endpoint."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.continuity_chains import ContinuityTraversalNode, resolve_continuity_chains
from app.continuity_readiness import evaluate_continuity_readiness
from app.database import get_db
from app.models.user import User
from app.schemas.continuity_readiness import (
    ContinuityChainNode,
    ContinuityChainResponse,
    ContinuityReadinessRequest,
    ContinuityReadinessResponse,
)

router = APIRouter(tags=["continuity"])


def _chain_node_to_schema(node: ContinuityTraversalNode) -> ContinuityChainNode:
    """Convert one traversal dataclass node into the API response schema.

    Args:
        node: ``ContinuityTraversalNode`` produced by the bounded traversal.

    Returns:
        Pydantic node representation suitable for JSON serialization.
    """
    return ContinuityChainNode(
        node_type=node.node_type,
        node_id=node.node_id,
        label=node.label,
        is_readable=node.is_readable,
    )


@router.post(
    "/continuity/readiness",
    response_model=ContinuityReadinessResponse,
    description="Evaluate direct continuity readiness for one owned issue, thread, or crossover.",
)
async def get_continuity_readiness(
    request: ContinuityReadinessRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ContinuityReadinessResponse:
    """Return a structured direct-readiness result for the requested owned node.

    Args:
        request: Node type and identifier requested by the authenticated client.
        current_user: Authenticated owner resolved by the API dependency.
        db: Database session supplied by the API dependency.

    Returns:
        Structured readiness state and any unsatisfied blockers for the owned node.
    """
    return await evaluate_continuity_readiness(
        db,
        user_id=current_user.id,
        node_type=request.node_type,
        node_id=request.node_id,
    )


@router.post(
    "/continuity/chains",
    response_model=ContinuityChainResponse,
    description=(
        "Resolve bounded transitive prerequisite chains, currently readable "
        "prerequisites, and structured traversal diagnostics for one owned node."
    ),
)
async def get_continuity_chains(
    request: ContinuityReadinessRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ContinuityChainResponse:
    """Return bounded prerequisite chains for one owned issue, thread, or crossover.

    Args:
        request: Node type and identifier requested by the authenticated client.
        current_user: Authenticated owner resolved by the API dependency.
        db: Database session supplied by the API dependency.

    Returns:
        Direct blockers, deterministic full chains, currently readable prerequisites,
        and structured diagnostics for any cycles, depth, or node-budget failures.
    """
    result = await resolve_continuity_chains(
        db,
        user_id=current_user.id,
        node_type=request.node_type,
        node_id=request.node_id,
    )
    return ContinuityChainResponse(
        node_type=result.node_type,
        node_id=result.node_id,
        evaluated_issue_id=result.evaluated_issue_id,
        direct_blockers=list(result.direct_blockers),
        chains=[[_chain_node_to_schema(node) for node in path] for path in result.chains],
        readable_prerequisites=[
            _chain_node_to_schema(node) for node in result.readable_prerequisites
        ],
        diagnostics=[
            {
                "code": diagnostic.code,
                "node_type": diagnostic.node_type,
                "node_id": diagnostic.node_id,
                "limit": diagnostic.limit,
            }
            for diagnostic in result.diagnostics
        ],
    )
