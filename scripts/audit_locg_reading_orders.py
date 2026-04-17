#!/usr/bin/env python3
"""Audit reading order dependencies in production against LOCG community lists.

For each LOCG reading order list, extracts cross-series transition edges
(where consecutive issues belong to different series) and compares them
against actual issue-level dependencies in the production API.
"""

import json
import sys
from pathlib import Path

import requests

# Add scripts dir to path so we can import comic_pile_api
sys.path.insert(0, str(Path(__file__).parent))
from comic_pile_api import (
    API_BASE,
    REQUESTS_TIMEOUT,
    DepEdge,
    get_all_threads,
    get_thread_issues,
    login,
)

COMMUNITY_LISTS_DIR = Path("/mnt/extra/josh/code/locg-import-tool/community-lists")


def normalize_series(name: str) -> str:
    """Normalize a series name for comparison."""
    name = name.strip()
    if name.lower().startswith("the "):
        name = name[4:]
    return name.lower()


def match_series_to_thread(series_name: str, threads: dict[str, dict]) -> str | None:
    """Try to match a series name to an existing thread title.

    Tries:
    1. Exact match (case-insensitive)
    2. Strip leading 'The ' and try again
    3. Substring match (series name contained in thread title or vice versa)

    Returns the canonical thread title if matched, else None.
    """
    series_lower = series_name.strip().lower()
    series_norm = normalize_series(series_name)

    for title in threads:
        title_lower = title.lower()
        title_norm = normalize_series(title)

        # Exact match
        if series_lower == title_lower:
            return title
        # Normalized exact match
        if series_norm == title_norm:
            return title

    # Substring matches (less strict — both ways)
    for title in threads:
        title_lower = title.lower()
        title_norm = normalize_series(title)

        if series_norm in title_norm or title_norm in series_norm:
            return title

    return None


def extract_cross_series_edges(issues: list[dict]) -> list[tuple[str, str, str, str]]:
    """Extract cross-series transition edges from an ordered issues list.

    Returns list of (src_series, src_issue_num, tgt_series, tgt_issue_num) tuples
    for each consecutive pair where the series differs.
    """
    edges = []
    sorted_issues = sorted(issues, key=lambda x: x["position"])

    for i in range(len(sorted_issues) - 1):
        curr = sorted_issues[i]
        nxt = sorted_issues[i + 1]
        if curr["series"] != nxt["series"]:
            edges.append(
                (
                    curr["series"],
                    curr["issue_number"],
                    nxt["series"],
                    nxt["issue_number"],
                )
            )

    return edges


def get_thread_dependencies(token: str, thread_id: int) -> set[tuple[int, int]]:
    """Fetch all dependency edges (source_id, target_id) for a thread."""
    response = requests.get(
        f"{API_BASE}/api/v1/threads/{thread_id}/dependencies",
        headers={"Authorization": f"Bearer {token}"},
        timeout=REQUESTS_TIMEOUT,
    )
    response.raise_for_status()
    data = response.json()

    edges: set[tuple[int, int]] = set()
    for dep in data.get("blocking", []) + data.get("blocked_by", []):
        src_id = dep.get("source_issue_id")
        tgt_id = dep.get("target_issue_id")
        if src_id is not None and tgt_id is not None:
            edges.add((src_id, tgt_id))
    return edges


def load_locg_lists() -> list[dict]:
    """Load all LOCG JSON reading order files."""
    lists = []
    for path in sorted(COMMUNITY_LISTS_DIR.glob("*.json")):
        try:
            with path.open() as f:
                data = json.load(f)
            if "metadata" in data and "issues" in data:
                lists.append(data)
        except (json.JSONDecodeError, KeyError):
            print(f"  Skipping malformed file: {path.name}")
    return lists


def audit_list(
    locg_list: dict,
    threads: dict[str, dict],
    token: str,
    issue_cache: dict[int, dict[str, int]],
    dep_cache: dict[int, set[tuple[int, int]]],
) -> dict | None:
    """Audit a single LOCG reading order list.

    Returns audit result dict, or None if list has fewer than 2 owned series.
    """
    metadata = locg_list["metadata"]
    issues = locg_list["issues"]
    list_title = metadata["list_title"]

    # Extract cross-series transition edges from the LOCG list
    raw_edges = extract_cross_series_edges(issues)

    if not raw_edges:
        return None

    # Match series names to user's threads
    # Track which series in this list the user owns
    all_series_in_list = {issue["series"] for issue in issues}
    series_to_thread: dict[str, str | None] = {}
    for series in all_series_in_list:
        series_to_thread[series] = match_series_to_thread(series, threads)

    owned_series = {s for s, t in series_to_thread.items() if t is not None}

    # Only edges where BOTH endpoints are in owned series matter
    relevant_edges = [
        (src_s, src_i, tgt_s, tgt_i)
        for src_s, src_i, tgt_s, tgt_i in raw_edges
        if src_s in owned_series and tgt_s in owned_series
    ]

    # Deduplicate (only care about each unique series-to-series transition once: last→first)
    # But LOCG lists may have a series appear multiple times (interleaved).
    # We keep all edge instances to catch every required dep.
    # However, deduplicate on (src_series_thread, src_issue, tgt_series_thread, tgt_issue)
    # since multiple LOCG list entries could map to the same dep.
    unique_relevant: list[tuple[str, str, str, str]] = []
    seen_edge_keys: set[tuple[str, str, str, str]] = set()
    for src_s, src_i, tgt_s, tgt_i in relevant_edges:
        src_thread = series_to_thread[src_s]
        tgt_thread = series_to_thread[tgt_s]
        assert src_thread is not None and tgt_thread is not None
        key = (src_thread, src_i, tgt_thread, tgt_i)
        if key not in seen_edge_keys:
            seen_edge_keys.add(key)
            unique_relevant.append((src_s, src_i, tgt_s, tgt_i))

    if not unique_relevant:
        return None

    # How many unique owned series are involved?
    owned_series_involved = {series_to_thread[src_s] for src_s, _, _, _ in unique_relevant} | {
        series_to_thread[tgt_s] for _, _, tgt_s, _ in unique_relevant
    }

    if len(owned_series_involved) < 2:
        return None

    # Fetch issues and deps for all involved threads (use cache)
    involved_thread_ids = {threads[t]["id"] for t in owned_series_involved if t}

    for thread_title in owned_series_involved:
        if thread_title is None:
            continue
        thread_id = threads[thread_title]["id"]
        if thread_id not in issue_cache:
            issue_cache[thread_id] = get_thread_issues(token, thread_id)
        if thread_id not in dep_cache:
            dep_cache[thread_id] = get_thread_dependencies(token, thread_id)

    # Build combined actual edges from all involved threads
    actual_edges: set[tuple[int, int]] = set()
    for thread_id in involved_thread_ids:
        actual_edges |= dep_cache.get(thread_id, set())

    # Build a mapping of issue_id -> (thread_title, issue_number) for unexpected detection
    id_to_label: dict[int, tuple[str, str]] = {}
    all_issue_ids_in_scope: set[int] = set()
    for thread_title in owned_series_involved:
        if thread_title is None:
            continue
        thread_id = threads[thread_title]["id"]
        for issue_num, issue_id in issue_cache[thread_id].items():
            id_to_label[issue_id] = (thread_title, issue_num)
            all_issue_ids_in_scope.add(issue_id)

    # Compare expected vs actual
    present: list[DepEdge] = []
    missing: list[DepEdge] = []
    not_found: list[DepEdge] = []
    expected_id_pairs: set[tuple[int, int]] = set()

    for src_s, src_i, tgt_s, tgt_i in unique_relevant:
        src_thread = series_to_thread[src_s]
        tgt_thread = series_to_thread[tgt_s]
        assert src_thread is not None and tgt_thread is not None

        src_thread_id = threads[src_thread]["id"]
        tgt_thread_id = threads[tgt_thread]["id"]

        src_issue_map = issue_cache.get(src_thread_id, {})
        tgt_issue_map = issue_cache.get(tgt_thread_id, {})

        src_id = src_issue_map.get(src_i)
        tgt_id = tgt_issue_map.get(tgt_i)

        edge = DepEdge(src_thread, src_i, tgt_thread, tgt_i)

        if src_id is None or tgt_id is None:
            not_found.append(edge)
        else:
            expected_id_pairs.add((src_id, tgt_id))
            if (src_id, tgt_id) in actual_edges:
                present.append(edge)
            else:
                missing.append(edge)

    # Unexpected: actual edges between in-scope issues that aren't expected
    unexpected: list[DepEdge] = []
    for src_id, tgt_id in actual_edges:
        if (src_id, tgt_id) in expected_id_pairs:
            continue
        if src_id in all_issue_ids_in_scope and tgt_id in all_issue_ids_in_scope:
            if src_id in id_to_label and tgt_id in id_to_label:
                src_label = id_to_label[src_id]
                tgt_label = id_to_label[tgt_id]
                # Only flag if it's cross-thread (same-thread unexpected deps are noise)
                if src_label[0] != tgt_label[0]:
                    unexpected.append(
                        DepEdge(src_label[0], src_label[1], tgt_label[0], tgt_label[1])
                    )

    return {
        "list_title": list_title,
        "list_id": metadata["list_id"],
        "username": metadata.get("username", "?"),
        "owned_series": sorted(t for t in owned_series_involved if t),
        "present": sorted(present),
        "missing": sorted(missing),
        "not_found": sorted(not_found),
        "unexpected": sorted(unexpected),
        "unmatched_series": sorted(s for s in all_series_in_list if series_to_thread[s] is None),
    }


def print_report(results: list[dict]) -> None:
    """Print a human-readable audit report."""
    total_present = sum(len(r["present"]) for r in results)
    total_missing = sum(len(r["missing"]) for r in results)
    total_not_found = sum(len(r["not_found"]) for r in results)
    total_unexpected = sum(len(r["unexpected"]) for r in results)

    print("=" * 80)
    print("LOCG READING ORDER DEPENDENCY AUDIT")
    print("=" * 80)
    print(f"Lists audited (with 2+ owned series): {len(results)}")
    print(f"  OK (present):   {total_present}")
    print(f"  Missing:        {total_missing}")
    print(f"  Not found:      {total_not_found}")
    print(f"  Unexpected:     {total_unexpected}")
    print()

    # Sort: lists with problems first
    def sort_key(r: dict) -> tuple:
        has_problems = len(r["missing"]) + len(r["unexpected"]) + len(r["not_found"])
        return (-has_problems, r["list_title"])

    for result in sorted(results, key=sort_key):
        list_title = result["list_title"]
        n_present = len(result["present"])
        n_missing = len(result["missing"])
        n_not_found = len(result["not_found"])
        n_unexpected = len(result["unexpected"])

        has_issues = n_missing + n_not_found + n_unexpected

        status_icon = "OK" if not has_issues else "!!"
        print(f"[{status_icon}] {list_title}  (list-{result['list_id']} by {result['username']})")
        print(f"     Owned series: {', '.join(result['owned_series'])}")
        print(
            f"     Present: {n_present}  Missing: {n_missing}  Not-found: {n_not_found}  Unexpected: {n_unexpected}"
        )

        if result["present"]:
            for e in result["present"]:
                print(
                    f"       OK  {e.source_title} #{e.source_issue}  -->  {e.target_title} #{e.target_issue}"
                )

        if result["missing"]:
            for e in result["missing"]:
                print(
                    f"       MISSING  {e.source_title} #{e.source_issue}  -->  {e.target_title} #{e.target_issue}"
                )

        if result["not_found"]:
            for e in result["not_found"]:
                print(
                    f"       NOT-FOUND  {e.source_title} #{e.source_issue}  -->  {e.target_title} #{e.target_issue}"
                )

        if result["unexpected"]:
            for e in result["unexpected"]:
                print(
                    f"       UNEXPECTED  {e.source_title} #{e.source_issue}  -->  {e.target_title} #{e.target_issue}"
                )

        if result["unmatched_series"]:
            print(
                f"     Unmatched (not in library): {', '.join(result['unmatched_series'][:5])}"
                + (
                    f" (+{len(result['unmatched_series']) - 5} more)"
                    if len(result["unmatched_series"]) > 5
                    else ""
                )
            )
        print()


def main() -> None:
    """Run the LOCG reading order audit script."""
    print("Logging in...")
    token = login("Josh_Digital_Comics", "Emily4412")
    print("Fetching all threads...")
    threads = get_all_threads(token)
    print(f"  Found {len(threads)} threads in library")

    print("Loading LOCG community lists...")
    locg_lists = load_locg_lists()
    print(f"  Loaded {len(locg_lists)} lists")
    print()

    issue_cache: dict[int, dict[str, int]] = {}
    dep_cache: dict[int, set[tuple[int, int]]] = {}

    results: list[dict] = []
    skipped = 0

    for locg_list in locg_lists:
        list_title = locg_list["metadata"]["list_title"]
        print(f"  Auditing: {list_title}...", end=" ", flush=True)
        try:
            result = audit_list(locg_list, threads, token, issue_cache, dep_cache)
            if result is None:
                print("skip (< 2 owned series)")
                skipped += 1
            else:
                print(
                    f"OK ({len(result['owned_series'])} owned series, "
                    f"{len(result['present'])}P/{len(result['missing'])}M/{len(result['not_found'])}NF)"
                )
                results.append(result)
        except Exception as e:
            print(f"ERROR: {e}")

    print()
    print(f"Skipped {skipped} lists (fewer than 2 owned series)")
    print()
    print_report(results)


if __name__ == "__main__":
    main()
