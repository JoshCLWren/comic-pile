#!/usr/bin/env python3
"""Diagnostic script to understand thread adoption state."""

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

DATABASE_URL = "postgresql+asyncpg://postgres:password@localhost:5432/comic_pile_test"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def analyze_thread_states():
    """Analyze thread states to understand the issue."""
    with SessionLocal() as session:
        # Get threads with issue tracking (total_issues is not NULL)
        query = text("""
            SELECT t.id, t.title, t.total_issues, t.issues_remaining, t.next_unread_issue_id,
                   COUNT(i.id) as actual_issues, 
                   COUNT(CASE WHEN i.status = 'read' THEN 1 END) as read_issues,
                   COUNT(CASE WHEN i.status = 'unread' THEN 1 END) as unread_issues
            FROM threads t
            LEFT JOIN issues i ON t.id = i.thread_id
            WHERE t.total_issues IS NOT NULL
            GROUP BY t.id, t.title, t.total_issues, t.issues_remaining, t.next_unread_issue_id
            HAVING COUNT(i.id) > 0
            ORDER BY t.id
        """)
        
        results = session.execute(query)
        
        print("Thread Analysis Report:")
        print("=" * 80)
        for row in results:
            thread_id = row.id
            title = row.title
            reported_total = row.total_issues
            reported_remaining = row.issues_remaining
            next_unread_id = row.next_unread_issue_id
            actual_count = row.actual_issues
            read_count = row.read_issues
            unread_count = row.unread_issues
            
            print(f"\nThread {thread_id}: {title}")
            print(f"  Reported: total_issues={reported_total}, issues_remaining={reported_remaining}, next_unread_issue_id={next_unread_id}")
            print(f"  Actual Issues in DB: {actual_count} (read={read_count}, unread={unread_count})")
            
            if reported_total != actual_count:
                print(f"  ❌ MISMATCH: total_issues ({reported_total}) != actual count ({actual_count})")
            if reported_remaining != unread_count:
                print(f"  ❌ MISMATCH: issues_remaining ({reported_remaining}) != actual unread ({unread_count})")
            if not next_unread_id and unread_count > 0:
                print(f"  ❌ PROBLEM: next_unread_issue_id is NULL but {unread_count} unread issues exist")


def analyze_cbl_source_entries():
    """Analyze CBL source entries to understand selective adoption."""
    with SessionLocal() as session:
        query = text("""
            SELECT sle.list_id, sle.source_path, sle.declared_issue_count,
                   COUNT(DISTINCT sle.id) as actual_entries,
                   COUNT(DISTINCT i.id) as adopted_issues,
                   COUNT(CASE WHEN i.status = 'read' THEN 1 END) as adopted_read
            FROM cbl_source_entries sle
            LEFT JOIN external_identities ei ON sle.external_issue_identity_id = ei.id
            LEFT JOIN issue_external_identity_mappings iem ON ei.id = iem.external_identity_id
            LEFT JOIN issues i ON iem.issue_id = i.id
            WHERE ei.external_id IS NOT NULL AND iem.status = 'confirmed'
            GROUP BY sle.list_id, sle.source_path, sle.declared_issue_count
            HAVING COUNT(DISTINCT i.id) > 0
            ORDER BY sle.list_id
        """)
        
        results = session.execute(query)
        
        print("\n\nCBL Source Entry Analysis:")
        print("=" * 80)
        for row in results:
            list_id = row.list_id
            source_path = row.source_path
            declared = row.declared_issue_count
            actual_entries = row.actual_entries
            adopted_issues = row.adopted_issues
            adopted_read = row.adopted_read
            
            print(f"\nCBL List {list_id} ({source_path}):")
            print(f"  Declared issues (external series): {declared}")
            print(f"  Actual CBL source entries: {actual_entries}")
            print(f"  Adopted issues in ComicPile: {adopted_issues}")
            print(f"  Adopted issues (read): {adopted_read}")
            
            if adopted_issues < declared:
                print(f"  ✅ Selective adoption confirmed: {declared - adopted_issues} issues filtered")


if __name__ == "__main__":
    analyze_thread_states()
    analyze_cbl_source_entries()
