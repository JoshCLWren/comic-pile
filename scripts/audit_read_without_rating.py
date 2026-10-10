#!/usr/bin/env python3
"""Audit and reconcile remaining read-without-rating issues after the historical ratings backfill.

This script audits the remaining read-without-rating population for user 1 and classifies
each issue into specific causes. It can also repair cases where a known historical rating
exists but failed to become an effective ComicPile `rate` event.

The audit classifies each read-without-rating issue into one of these categories:
1. Historical source rating exists, local issue mapped, but `rate` event missing
2. Historical source rating exists, but issue identity/mapping is ambiguous  
3. Edition/duplicate conflict prevented safe historical match
4. Issue is read in ComicPile but no historical source rating exists
5. Other specific, evidenced cause discovered by the audit

Examples:
    uv run python scripts/audit_read_without_rating.py --user-id 1 --dry-run
    uv run python scripts/audit_read_without_rating.py --user-id 1 --classify-only
    uv run python scripts/audit_read_without_rating.py --user-id 1 --repair-safe
"""

from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict, Counter
from dataclasses import dataclass, field
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Any, Literal

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Import database and models
from app.database import AsyncSessionLocal
from app.models.event import Event
from app.models.issue import Issue
from app.models.thread import Thread
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
from app.repositories.creator_summary import load_creator_summary_inputs

# Constants
USER_ID = 1
COMICVINE_PROVIDER = "comicvine"
EVIDENCE_FILE = ROOT / "docs/recovery/read-without-rating-audit-evidence.json"


@dataclass
class ClassificationResult:
    """Result of classifying one read-without-rating issue."""
    
    issue_id: int
    thread_id: int
    thread_title: str
    issue_number: str
    classification: Literal[
        "missing_rate_event", 
        "unresolved_mapping", 
        "edition_conflict", 
        "no_source_rating", 
        "other_cause"
    ]
    details: dict[str, Any] = field(default_factory=dict)
    historical_rating_exists: bool = False
    historical_rating_value: float | None = None
    mapping_confidence: str | None = None
    repair_safe: bool = False


@dataclass
class AuditReport:
    """Complete audit report for read-without-rating issues."""
    
    total_read_unrated: int
    classifications: dict[Literal["missing_rate_event", "unresolved_mapping", "edition_conflict", "no_source_rating", "other_cause"], int]
    by_thread: dict[int, dict[str, int]]
    by_creator: dict[str, dict[str, int]]
    creator_impact: dict[str, int]
    issues_by_classification: dict[Literal["missing_rate_event", "unresolved_mapping", "edition_conflict", "no_source_rating", "other_cause"], list[ClassificationResult]]
    historical_ratings_found: int
    repairs_made: int
    timestamp: datetime = field(default_factory=datetime.now)


async def get_read_without_rating_issues(db: AsyncSession, user_id: int) -> tuple[set[int], dict[int, str], dict[int, int], dict[int, int]]:
    """Get all read issues without effective ratings for the user."""
    
    # Get user's owned issues with their status
    owned_issues_result = await db.execute(
        select(Issue.id, Issue.status, Issue.thread_id, Issue.issue_number, Thread.title)
        .join(Thread, Thread.id == Issue.thread_id)
        .where(Thread.user_id == user_id)
    )
    
    owned_issues: dict[int, str] = {}
    issue_to_thread: dict[int, int] = {}
    issue_numbers: dict[int, str] = {}
    thread_titles: dict[int, str] = {}
    
    for issue_id, status, thread_id, issue_number, thread_title in owned_issues_result.all():
        owned_issues[issue_id] = status
        issue_to_thread[issue_id] = thread_id
        issue_numbers[issue_id] = issue_number
        thread_titles[thread_id] = thread_title
    
    # Get effective ratings (latest rate event per issue)
    effective_ratings_query = text("""
        SELECT DISTINCT ON (issue_id) issue_id, rating
        FROM events 
        WHERE type = 'rate' 
        AND issue_id IS NOT NULL 
        AND rating IS NOT NULL
        ORDER BY issue_id, timestamp DESC, id DESC
    """)
    effective_ratings_result = await db.execute(effective_ratings_query)
    effective_ratings = {int(row.issue_id): float(row.rating) for row in effective_ratings_result}
    
    # Identify read-without-rating issues
    read_unrated_issues = {
        issue_id for issue_id, status in owned_issues.items()
        if status == "read" and issue_id not in effective_ratings
    }
    
    return read_unrated_issues, issue_numbers, thread_titles, issue_to_thread


async def find_historical_ratings(db: AsyncSession, user_id: int) -> dict[int, float]:
    """Find historical ratings that may exist but not be converted to effective rate events.
    
    This looks for any historical rating data that was imported but may not have
    been properly converted to ComicPile rate events.
    """
    
    # Look for historical ratings in external identity mappings
    # This might include ratings from LoCG or other historical sources
    historical_ratings_query = text("""
        SELECT i.id as issue_id, jsonb_extract_path_text(e.metadata_json, 'rating') as rating
        FROM issues i
        JOIN threads t ON i.thread_id = t.id
        JOIN issue_external_identity_mappings iem ON i.id = iem.issue_id
        JOIN external identities e ON iem.external_identity_id = e.id
        WHERE t.user_id = :user_id
        AND iem.status = 'confirmed'
        AND e.provider = :provider
        AND jsonb_extract_path_text(e.metadata_json, 'rating') IS NOT NULL
        AND i.status = 'read'
    """)
    
    result = await db.execute(historical_ratings_query, {"user_id": user_id, "provider": COMICVINE_PROVIDER})
    historical_ratings = {}
    
    for row in result:
        try:
            rating = float(row.rating)
            if 0.5 <= rating <= 5.0:  # Valid rating range
                historical_ratings[row.issue_id] = rating
        except (ValueError, TypeError):
            continue
    
    return historical_ratings


async def classify_issue(
    issue_id: int,
    issue_number: str,
    thread_id: int,
    thread_title: str,
    historical_ratings: dict[int, float],
    db: AsyncSession
) -> ClassificationResult:
    """Classify a single read-without-rating issue."""
    
    classification = ClassificationResult(
        issue_id=issue_id,
        thread_id=thread_id,
        thread_title=thread_title,
        issue_number=issue_number,
        classification="no_source_rating",  # Default
        details={}
    )
    
    # Check if historical rating exists for this issue
    if issue_id in historical_ratings:
        classification.historical_rating_exists = True
        classification.historical_rating_value = historical_ratings[issue_id]
        classification.classification = "missing_rate_event"
        classification.repair_safe = True
        classification.details = {
            "historical_rating": historical_ratings[issue_id],
            "reason": "Historical rating found but no ComicPile rate event exists"
        }
        
        # Check for potential mapping conflicts
        # Look for duplicate issues with same number in different threads
        duplicate_check_query = text("""
            SELECT id, thread_id, thread_title
            FROM issues 
            WHERE issue_number = :issue_number 
            AND thread_id != :thread_id
            AND status = 'read'
        """)
        
        duplicate_result = await db.execute(duplicate_check_query, {
            "issue_number": issue_number,
            "thread_id": thread_id
        })
        
        duplicates = duplicate_result.fetchall()
        if duplicates:
            classification.classification = "edition_conflict"
            classification.repair_safe = False
            classification.details = {
                "historical_rating": historical_ratings[issue_id],
                "reason": "Duplicate/edition conflict detected",
                "duplicates": [(dup.id, dup.thread_id, dup.thread_title) for dup in duplicates]
            }
        
        # Check for ambiguous mapping
        # This could be issues with unclear identity or multiple possible matches
        if not classification.repair_safe:
            # Additional checks for ambiguous mapping could go here
            pass
    
    else:
        # No historical rating found
        classification.classification = "no_source_rating"
        classification.details = {
            "reason": "No historical source rating found for this issue"
        }
    
    # Additional classification logic could be added here for other causes
    
    return classification


async def audit_read_without_rating(
    db: AsyncSession, 
    user_id: int, 
    classify_only: bool = False
) -> AuditReport:
    """Perform complete audit of read-without-rating issues."""
    
    print("🔍 Starting audit of read-without-rating issues...")
    
    # Get read-without-rating issues
    read_unrated_issues, issue_numbers, thread_titles = await get_read_without_rating_issues(db, user_id)
    print(f"📊 Found {len(read_unrated_issues)} read-without-rating issues")
    
    # Find historical ratings
    historical_ratings = await find_historical_ratings(db, user_id)
    print(f"📚 Found {len(historical_ratings)} historical ratings in metadata")
    
    # Classify each issue
    classifications_by_type: dict[Literal["missing_rate_event", "unresolved_mapping", "edition_conflict", "no_source_rating", "other_cause"], list[ClassificationResult]] = {
        "missing_rate_event": [],
        "unresolved_mapping": [],
        "edition_conflict": [],
        "no_source_rating": [],
        "other_cause": []
    }
    
    classification_counts = Counter()
    by_thread = defaultdict(lambda: defaultdict(int))
    by_creator = defaultdict(lambda: defaultdict(int))
    creator_impact = defaultdict(int)
    
    for issue_id in read_unrated_issues:
        issue_number = issue_numbers.get(issue_id, "unknown")
        thread_id = issue_to_thread.get(issue_id)
        
        if not thread_id:
            print(f"⚠️  Thread not found for issue {issue_id}")
            continue
            
        thread_title = thread_titles.get(thread_id, "Unknown Thread")
        
        classification = await classify_issue(
            issue_id, issue_number, thread_id, thread_title, 
            historical_ratings, db
        )
        
        classifications_by_type[classification.classification].append(classification)
        classification_counts[classification.classification] += 1
        
        by_thread[thread_id][classification.classification] += 1
        
        # Extract creator name from thread title for impact analysis
        # This is a simple approach - could be enhanced with actual creator metadata
        creator_name = thread_title.split(" ")[0] if thread_title else "Unknown"
        by_creator[creator_name][classification.classification] += 1
        creator_impact[creator_name] += 1
    
    # Generate creator impact report (focus on large outliers)
    top_creators = sorted(creator_impact.items(), key=lambda x: x[1], reverse=True)[:10]
    
    # Perform repairs if requested
    repairs_made = 0
    if not classify_only:
        print("🔧 Starting safe repairs...")
        repairs_made = await perform_safe_repairs(db, classifications_by_type["missing_rate_event"])
        print(f"✅ Made {repairs_made} safe repairs")
    
    # Create audit report
    report = AuditReport(
        total_read_unrated=len(read_unrated_issues),
        classifications=dict(classification_counts),
        by_thread=dict(by_thread),
        by_creator=dict(by_creator),
        creator_impact=dict(top_creators),
        issues_by_classification=classifications_by_type,
        historical_ratings_found=len(historical_ratings),
        repairs_made=repairs_made
    )
    
    return report


async def perform_safe_repairs(db: AsyncSession, repairable_issues: list[ClassificationResult]) -> int:
    """Perform safe repairs for issues with missing rate events."""
    
    repairs_made = 0
    
    for classification in repairable_issues:
        if not classification.repair_safe:
            continue
            
        try:
            # Create a rate event for the historical rating
            rate_event = Event(
                type="rate",
                rating=classification.historical_rating_value,
                issue_id=classification.issue_id,
                thread_id=classification.thread_id,
                timestamp=datetime.now(),  # Use current timestamp for repair events
                issues_read=1  # Assume 1 issue was read
            )
            
            db.add(rate_event)
            repairs_made += 1
            
        except Exception as e:
            print(f"❌ Failed to repair issue {classification.issue_id}: {e}")
    
    if repairs_made > 0:
        await db.commit()
    
    return repairs_made


async def save_evidence(report: AuditReport) -> None:
    """Save audit evidence to JSON file."""
    
    evidence = {
        "timestamp": report.timestamp.isoformat(),
        "total_read_unrated": report.total_read_unrated,
        "classifications": report.classifications,
        "by_thread": report.by_thread,
        "by_creator": report.by_creator,
        "creator_impact": report.creator_impact,
        "historical_ratings_found": report.historical_ratings_found,
        "repairs_made": report.repairs_made,
        "detailed_issues": {
            classification_type: [
                {
                    "issue_id": result.issue_id,
                    "thread_id": result.thread_id,
                    "thread_title": result.thread_title,
                    "issue_number": result.issue_number,
                    "classification": result.classification,
                    "details": result.details,
                    "historical_rating_exists": result.historical_rating_exists,
                    "historical_rating_value": result.historical_rating_value,
                    "repair_safe": result.repair_safe
                }
                for result in issues
            ]
            for classification_type, issues in report.issues_by_classification.items()
        }
    }
    
    EVIDENCE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with EVIDENCE_FILE.open("w", encoding="utf-8") as f:
        json.dump(evidence, f, indent=2, ensure_ascii=False)
    
    print(f"📄 Evidence saved to: {EVIDENCE_FILE}")


async def main() -> None:
    """Main audit script entry point."""
    
    parser = argparse.ArgumentParser(description="Audit and reconcile read-without-rating issues")
    parser.add_argument("--user-id", type=int, default=1, help="User ID to audit")
    parser.add_argument("--dry-run", action="store_true", help="Run audit without repairs")
    parser.add_argument("--classify-only", action="store_true", help="Only classify, don't repair")
    parser.add_argument("--output", type=str, help="Output file for report")
    
    args = parser.parse_args()
    
    async with AsyncSessionLocal() as db:
        print(f"🚀 Starting audit for user {args.user_id}")
        
        # Perform audit
        report = await audit_read_without_rating(
            db, 
            user_id=args.user_id, 
            classify_only=args.classify_only or args.dry_run
        )
        
        # Print summary
        print("\n" + "="*60)
        print("📊 AUDIT SUMMARY")
        print("="*60)
        print(f"Total read-without-rating issues: {report.total_read_unrated}")
        print(f"Historical ratings found: {report.historical_ratings_found}")
        print(f"Safe repairs made: {report.repairs_made}")
        
        print("\n📋 Classification breakdown:")
        for classification, count in report.classifications.items():
            print(f"  {classification}: {count}")
        
        print("\n👥 Top creators by read-without-rating count:")
        for creator, count in report.creator_impact[:5]:
            print(f"  {creator}: {count}")
        
        # Save evidence
        await save_evidence(report)
        
        # Save detailed report if requested
        if args.output:
            output_file = Path(args.output)
            output_file.parent.mkdir(parents=True, exist_ok=True)
            
            with output_file.open("w", encoding="utf-8") as f:
                json.dump({
                    "summary": {
                        "total": report.total_read_unrated,
                        "classifications": report.classifications,
                        "repairs_made": report.repairs_made
                    },
                    "timestamp": report.timestamp.isoformat()
                }, f, indent=2)
            
            print(f"📄 Summary saved to: {output_file}")


if __name__ == "__main__":
    asyncio.run(main())