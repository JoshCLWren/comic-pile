"""Legacy continuity readiness compatibility endpoints."""

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
    return ContinuityChainNode(
        node_type=node.node_type,
        node_id=node.node_id,
        label=node.label,
        is_readable=node.is_readable,
    )


@router.post(
    "/continuity/readiness",
    response_model=ContinuityReadinessResponse,
    description="Legacy direct continuity readiness compatibility endpoint.",
)
async def get_continuity_readiness(
    request: ContinuityReadinessRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ContinuityReadinessResponse:
    """Serve the temporary compatibility API; normal product UI does not call it."""
    result = await evaluate_continuity_readiness(
        db,
        user_id=current_user.id,
        node_type=request.node_type,
        node_id=request.node_id,
        expose_result=True,
    )
    assert result is not None
    return result


@router.post(
    "/continuity/chains",
    response_model=ContinuityChainResponse,
    description="Legacy bounded continuity-chain compatibility endpoint.",
)
async def get_continuity_chains(
    request: ContinuityReadinessRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ContinuityChainResponse:
    """Serve legacy chain consumers while the removed product surface is cleaned up."""
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
