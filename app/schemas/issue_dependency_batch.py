"""Schemas for fetching issue dependencies for an entire thread."""

from pydantic import BaseModel

from app.schemas.dependency import IssueDependenciesResponse


class ThreadIssueDependenciesResponse(BaseModel):
    """Issue dependency payloads for every issue in one owned thread."""

    thread_id: int
    issues: list[IssueDependenciesResponse]
