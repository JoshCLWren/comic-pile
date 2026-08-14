"""API coverage for external crossover template preview and adoption."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import continuity_template
from app.models.continuity_plan import ContinuityPlan
from app.models.continuity_rule import ContinuityRule
from app.models.issue import Issue
from app.models.thread import Thread
from app.services.crossover_templates import (
    CBLPlacement,
    CrossoverTemplateConflict,
    CrossoverTemplateIntersection,
    CrossoverTemplateItem,
    CrossoverTemplateParallelCandidate,
    CrossoverTemplateSerialSpine,
    TemplateEvidence,
    DerivedCrossoverTemplate,
)
from tests.conftest import get_or_create_user_async
