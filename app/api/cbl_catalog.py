"""Read-only browsing of the shared CBL catalog folder tree and search.

These endpoints are deliberately ownership-free: they read the shared
``cbl_sources`` / ``cbl_source_lists`` catalog and never join reader-owned
Issues, Threads, Reading Lists, or adoption receipts. Folder navigation, search,
and pagination therefore produce identical results for every authenticated
account, including a brand-new one with no comics.

The router is registered ahead of :mod:`app.api.cbl_sources` on purpose. The
sibling source-list detail route is ``/cbl-sources/{list_id}`` with an integer
path parameter, and FastAPI resolves the first matching path route, so the
literal ``/cbl-sources/folders`` and ``/cbl-sources/browse`` paths have to be
registered first or the integer route would answer them with a 422.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.cbl_catalog import (
    CBLCatalogBrowseResponse,
    CBLErrorResponse,
    CBLFolderListingResponse,
)
from app.services.cbl_catalog import (
    CBLFolderNotFoundError,
    InvalidCBLFolderPathError,
    InvalidCBLSearchQueryError,
    browse_cbl_catalog,
    list_cbl_catalog_folders,
)

router = APIRouter(prefix="/issue-identity", tags=["issue-identity"])
logger = logging.getLogger(__name__)

INVALID_FOLDER_CODE = "invalid_folder"
INVALID_QUERY_CODE = "invalid_query"
FOLDER_NOT_FOUND_CODE = "folder_not_found"
CATALOG_UNAVAILABLE_CODE = "cbl_catalog_unavailable"
CATALOG_UNAVAILABLE_MESSAGE = "The shared CBL catalog is temporarily unavailable."


def _error_detail(code: str, message: str) -> dict[str, str]:
    """Build the stable machine-readable error envelope used by catalog routes."""
    return {"code": code, "message": message}


@router.get(
    "/cbl-sources/folders",
    response_model=CBLFolderListingResponse,
    responses={
        400: {"model": CBLErrorResponse, "description": "Invalid folder path."},
        404: {"model": CBLErrorResponse, "description": "Folder not found."},
        503: {
            "model": CBLErrorResponse,
            "description": "The shared CBL catalog is temporarily unavailable.",
        },
    },
)
async def list_cbl_source_folders(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    folder: Annotated[str, Query(max_length=1000)] = "",
) -> CBLFolderListingResponse:
    """List immediate subfolders of one shared CBL catalog folder.

    The root folder is addressed with an empty ``folder`` value. A request for a
    folder with no active CBLs or subfolders returns a stable 404 envelope; a
    malformed path returns 400.

    Args:
        current_user: The authenticated user (injected by dependency).
        db: The async database session (injected by dependency).
        folder: The catalog folder path to list. Empty string for root.

    Returns:
        CBLFolderListingResponse: The folder listing containing subfolders.
    """
    del current_user
    try:
        return await list_cbl_catalog_folders(db, folder=folder)
    except InvalidCBLFolderPathError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_error_detail(INVALID_FOLDER_CODE, str(error)),
        ) from error
    except CBLFolderNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_error_detail(FOLDER_NOT_FOUND_CODE, str(error)),
        ) from error
    except SQLAlchemyError as error:
        logger.exception("CBL folder listing query failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_error_detail(CATALOG_UNAVAILABLE_CODE, CATALOG_UNAVAILABLE_MESSAGE),
        ) from error


@router.get(
    "/cbl-sources/browse",
    response_model=CBLCatalogBrowseResponse,
    responses={
        400: {
            "model": CBLErrorResponse,
            "description": "Invalid folder path or search query.",
        },
        404: {"model": CBLErrorResponse, "description": "Folder not found."},
        503: {
            "model": CBLErrorResponse,
            "description": "The shared CBL catalog is temporarily unavailable.",
        },
    },
)
async def browse_cbl_source_catalog(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    folder: Annotated[str, Query(max_length=1000)] = "",
    q: Annotated[str | None, Query(max_length=200)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> CBLCatalogBrowseResponse:
    """Browse one catalog folder or search all CBLs by name and source path.

    With a blank ``q`` the response describes the immediate contents of
    ``folder``. With a non-blank ``q`` the search spans the entire shared
    catalog, regardless of ``folder``, and ``scope`` is ``"search"``. ``total``
    is the truthful number of matches, so callers can page past 100 results.

    Args:
        current_user: The authenticated user (injected by dependency).
        db: The async database session (injected by dependency).
        folder: The catalog folder path to browse. Empty string for root.
        q: Optional search query for CBL name and source path.
        page: Page number (1-indexed).
        page_size: Number of results per page (1-100).

    Returns:
        CBLCatalogBrowseResponse: The browse response containing entries and pagination info.
    """
    del current_user
    try:
        return await browse_cbl_catalog(
            db,
            folder=folder,
            query=q,
            page=page,
            page_size=page_size,
        )
    except InvalidCBLFolderPathError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_error_detail(INVALID_FOLDER_CODE, str(error)),
        ) from error
    except InvalidCBLSearchQueryError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_error_detail(INVALID_QUERY_CODE, str(error)),
        ) from error
    except CBLFolderNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_error_detail(FOLDER_NOT_FOUND_CODE, str(error)),
        ) from error
    except SQLAlchemyError as error:
        logger.exception("CBL catalog browse query failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_error_detail(CATALOG_UNAVAILABLE_CODE, CATALOG_UNAVAILABLE_MESSAGE),
        ) from error
