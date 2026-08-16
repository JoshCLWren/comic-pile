"""Dependency API endpoints (/api/v1)."""

from typing import Annotated, TypedDict

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.cache import TTL, cached
from app.database import get_db
from app.models import Dependency, Issue, Thread
from app.models.user import User
from app.schemas.dependency import (
    BatchBlockingExplanationRequest,
    BatchBlockingExplanationResponse,
    BlockingExplanation,
    ConnectedThreadInfo,
    DependencyCreate,
    DependencyNoteUpdate,
    DependencyOrderConflict,
    DependencyOrderRequirement,
    DependencyResponse,
    IssueDependenciesResponse,
    IssueDependencyEdge,
    ThreadConnectedResponse,
    ThreadDependencyOrderCheckResponse,
    ThreadDependencyResponse,
    ThreadConnectedResponse,