"""Service for synchronizing followed ComicVine volumes and adopting released issues."""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.models.reading_plan_release_source import ReadingPlanReleaseSource
from app.models.thread import Thread
from app.models.continuity_plan import ContinuityPlan
from app.models.external_identity import ExternalIdentity
from app.models.issue import Issue
from comic_pile.comicvine_provider import ComicVineProvider
from app.services.provider_issue_adoption import adopt_comicvine_issue, AdoptionResult
from app.repositories.reading_plan_release_source_repository import (
    reading_plan_release_source_repository,
)
from app.repositories.thread_repository import thread_repository
from app.repositories.external_identity_repository import external_identity_repository
from app.repositories.issue_repository import issue_repository

logger = logging.getLogger(__name__)


class SyncResult:
    """Result of a sync operation."""
    
    def __init__(
        self,
        total_sources: int,
        enabled_sources: int,
        successful_sources: int,
        failed_sources: int,
        created_issues: int,
        reused_issues: int,
        future_skips: int,
        unknown_date_skips: int,
        conflicts: int,
        errors: List[Dict[str, str]],
    ):
        self.total_sources = total_sources
        self.enabled_sources = enabled_sources
        self.successful_sources = successful_sources
        self.failed_sources = failed_sources
        self.created_issues = created_issues
        self.reused_issues = reused_issues
        self.future_skips = future_skips
        self.unknown_date_skips = unknown_date_skips
        self.conflicts = conflicts
        self.errors = errors


class SourceSyncResult:
    """Result for a single source sync."""
    
    def __init__(
        self,
        source_id: int,
        plan_id: int,
        thread_id: int,
        volume_id: int,
        success: bool,
        message: str,
        issues_checked: int = 0,
        issues_created: int = 0,
        issues_reused: int = 0,
        future_skips: int = 0,
        unknown_date_skips: int = 0,
        conflicts: int = 0,
        error: Optional[str] = None,
    ):
        self.source_id = source_id
        self.plan_id = plan_id
        self.thread_id = thread_id
        self.volume_id = volume_id
        self.success = success
        self.message = message
        self.issues_checked = issues_checked
        self.issues_created = issues_created
        self.issues_reused = issues_reused
        self.future_skips = future_skips
        self.unknown_date_skips = unknown_date_skips
        self.conflicts = conflicts
        self.error = error


async def sync_released_issues(
    db, 
    as_of: datetime, 
    refresh: bool = True
) -> SyncResult:
    """
    Synchronize followed ComicVine volumes and adopt only released issues.
    
    Args:
        db: Database session
        as_of: UTC timestamp defining the release boundary - only issues with 
               store_date <= as_of will be adopted
        refresh: Whether to refresh the ComicVine cache
        
    Returns:
        SyncResult with detailed statistics about the sync operation
    """
    # Query all enabled release sources
    enabled_sources = await reading_plan_release_source_repository.get_enabled_sources(db)
    
    total_sources = len(enabled_sources)
    enabled_sources_count = len([s for s in enabled_sources if s.enabled])
    
    logger.info(f"Starting sync for {enabled_sources_count}/{total_sources} enabled sources")
    
    sync_result = SyncResult(
        total_sources=total_sources,
        enabled_sources=enabled_sources_count,
        successful_sources=0,
        failed_sources=0,
        created_issues=0,
        reused_issues=0,
        future_skips=0,
        unknown_date_skips=0,
        conflicts=0,
        errors=[],
    )
    
    # Group sources by volume_id to avoid duplicate fetching
    volume_sources: Dict[int, List[ReadingPlanReleaseSource]] = {}
    for source in enabled_sources:
        if source.enabled:
            if source.volume_id not in volume_sources:
                volume_sources[source.volume_id] = []
            volume_sources[source.volume_id].append(source)
    
    # Process each unique volume
    for volume_id, sources in volume_sources.items():
        logger.info(f"Processing volume {volume_id} for {len(sources)} sources")
        
        source_results = await _sync_volume_issues(
            db, volume_id, sources, as_of, refresh
        )
        
        # Aggregate results from all sources for this volume
        for result in source_results:
            if result.success:
                sync_result.successful_sources += 1
                sync_result.created_issues += result.issues_created
                sync_result.reused_issues += result.issues_reused
                sync_result.future_skips += result.future_skips
                sync_result.unknown_date_skips += result.unknown_date_skips
                sync_result.conflicts += result.conflicts
            else:
                sync_result.failed_sources += 1
                sync_result.errors.append({
                    "source_id": result.source_id,
                    "plan_id": result.plan_id,
                    "thread_id": result.thread_id,
                    "volume_id": result.volume_id,
                    "error": result.error or result.message,
                })
        
        # Update last_synced_at for all sources that were processed
        # (even if some failed, we don't want to hide partial progress)
        for source in sources:
            try:
                await reading_plan_release_source_repository.update_last_synced_at(
                    db, source.id
                )
            except Exception as e:
                logger.warning(
                    f"Failed to update last_synced_at for source {source.id}: {e}"
                )
    
    logger.info(
        f"Sync completed: {sync_result.successful_sources} successful, "
        f"{sync_result.failed_sources} failed, "
        f"{sync_result.created_issues} created, "
        f"{sync_result.reused_issues} reused"
    )
    
    return sync_result


async def _sync_volume_issues(
    db,
    volume_id: int,
    sources: List[ReadingPlanReleaseSource],
    as_of: datetime,
    refresh: bool,
) -> List[SourceSyncResult]:
    """
    Sync issues for a single volume across multiple sources.
    
    Args:
        db: Database session
        volume_id: ComicVine volume ID to sync
        sources: List of release sources for this volume
        as_of: UTC timestamp defining the release boundary
        refresh: Whether to refresh the ComicVine cache
        
    Returns:
        List of SourceSyncResult for each source
    """
    results = []
    
    try:
        # Fetch volume issues from ComicVine
        provider = ComicVineProvider()
        comicvine_issues = await provider.fetch_volume_issues(volume_id, refresh=refresh)
        
        logger.info(f"Fetched {len(comicvine_issues)} issues from ComicVine volume {volume_id}")
        
        # Get existing issue identities for this volume to avoid duplicates
        existing_identities = await external_identity_repository.get_by_provider_and_volume(
            db, "comicvine", volume_id
        )
        existing_issue_ids = {
            identity.external_id for identity in existing_identities
        }
        
        # Process each source
        for source in sources:
            result = await _sync_source_issues(
                db, source, comicvine_issues, existing_issue_ids, as_of
            )
            results.append(result)
            
    except Exception as e:
        logger.error(f"Failed to sync volume {volume_id}: {e}")
        # Create failure results for all sources
        for source in sources:
            results.append(SourceSyncResult(
                source_id=source.id,
                plan_id=source.reading_plan_id,
                thread_id=source.thread_id,
                volume_id=volume_id,
                success=False,
                message=f"Volume sync failed: {str(e)}",
                error=str(e),
            ))
    
    return results


async def _sync_source_issues(
    db,
    source: ReadingPlanReleaseSource,
    comicvine_issues: List[Dict],
    existing_issue_ids: set,
    as_of: datetime,
) -> SourceSyncResult:
    """
    Sync issues for a single release source.
    
    Args:
        db: Database session
        source: Release source to sync
        comicvine_issues: List of issues from ComicVine
        existing_issue_ids: Set of already adopted issue IDs
        as_of: UTC timestamp defining the release boundary
        
    Returns:
        SourceSyncResult with detailed statistics for this source
    """
    issues_checked = 0
    issues_created = 0
    issues_reused = 0
    future_skips = 0
    unknown_date_skips = 0
    conflicts = 0
    
    try:
        # Validate that the thread still exists and belongs to the plan's user
        thread = await thread_repository.get_by_id(db, source.thread_id)
        if not thread:
            raise ValueError(f"Thread {source.thread_id} not found")
        
        if thread.user_id != source.reading_plan.user_id:
            raise ValueError(
                f"Thread {source.thread_id} user mismatch: "
                f"thread.user_id={thread.user_id}, "
                f"plan.user_id={source.reading_plan.user_id}"
            )
        
        # Check that the volume mapping is still confirmed
        volume_identity = await external_identity_repository.get_by_provider_and_external_id(
            db, "comicvine", str(source.volume_id)
        )
        if not volume_identity or not volume_identity.confirmed:
            raise ValueError(
                f"Volume {source.volume_id} mapping is not confirmed"
            )
        
        # Process each ComicVine issue
        for comicvine_issue in comicvine_issues:
            issues_checked += 1
            
            try:
                issue_result = await _process_comicvine_issue(
                    db, source, comicvine_issue, existing_issue_ids, as_of
                )
                
                if issue_result == "created":
                    issues_created += 1
                elif issue_result == "reused":
                    issues_reused += 1
                elif issue_result == "future_skip":
                    future_skips += 1
                elif issue_result == "unknown_date_skip":
                    unknown_date_skips += 1
                elif issue_result == "conflict":
                    conflicts += 1
                    
            except Exception as e:
                logger.warning(
                    f"Failed to process issue {comicvine_issue['id']} for source {source.id}: {e}"
                )
                # Continue with next issue instead of failing the whole source
                continue
        
        return SourceSyncResult(
            source_id=source.id,
            plan_id=source.reading_plan_id,
            thread_id=source.thread_id,
            volume_id=source.volume_id,
            success=True,
            message=f"Synced {issues_checked} issues: {issues_created} created, {issues_reused} reused",
            issues_checked=issues_checked,
            issues_created=issues_created,
            issues_reused=issues_reused,
            future_skips=future_skips,
            unknown_date_skips=unknown_date_skips,
            conflicts=conflicts,
        )
        
    except Exception as e:
        logger.error(f"Failed to sync source {source.id}: {e}")
        return SourceSyncResult(
            source_id=source.id,
            plan_id=source.reading_plan_id,
            thread_id=source.thread_id,
            volume_id=source.volume_id,
            success=False,
            message=f"Source sync failed: {str(e)}",
            error=str(e),
        )


async def _process_comicvine_issue(
    db,
    source: ReadingPlanReleaseSource,
    comicvine_issue: Dict,
    existing_issue_ids: set,
    as_of: datetime,
) -> str:
    """
    Process a single ComicVine issue for adoption.
    
    Args:
        db: Database session
        source: Release source
        comicvine_issue: ComicVine issue data
        existing_issue_ids: Set of already adopted issue IDs
        as_of: UTC timestamp defining the release boundary
        
    Returns:
        String indicating the result: "created", "reused", "future_skip", 
        "unknown_date_skip", or "conflict"
    """
    issue_id = str(comicvine_issue["id"])
    
    # Check if issue already exists
    if issue_id in existing_issue_ids:
        return "reused"
    
    # Check release date eligibility
    store_date_str = comicvine_issue.get("store_date")
    if not store_date_str:
        # Missing store_date - skip and report
        return "unknown_date_skip"
    
    try:
        # Parse store_date (ComicVine returns this as a string)
        store_date = datetime.fromisoformat(store_date_str.replace("Z", "+00:00"))
        
        # Check if issue is released (store_date <= as_of)
        if store_date > as_of:
            # Future release - skip
            return "future_skip"
            
    except ValueError as e:
        logger.warning(f"Invalid store_date {store_date_str} for issue {issue_id}: {e}")
        return "unknown_date_skip"
    
    # Adopt the issue
    try:
        result = await adopt_comicvine_issue(
            db=db,
            thread_id=source.thread_id,
            comicvine_volume_id=source.volume_id,
            comicvine_issue_id=issue_id,
        )
        
        if result == AdoptionResult.CONFLICT:
            return "conflict"
        elif result == AdoptionResult.CREATED:
            return "created"
        elif result == AdoptionResult.REUSED:
            return "reused"
        else:
            logger.warning(f"Unexpected adoption result: {result}")
            return "reused"
            
    except Exception as e:
        logger.error(f"Failed to adopt issue {issue_id}: {e}")
        raise e