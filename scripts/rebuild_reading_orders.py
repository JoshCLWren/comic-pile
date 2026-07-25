#!/usr/bin/env python3
"""Rebuild reading order directories on SD card from API dependency graph.

Usage:
    python scripts/rebuild_reading_orders.py [--dry-run]

Requires COMIC_PILE_USERNAME and COMIC_PILE_PASSWORD env vars.
"""

import argparse
import os
import shutil
import sys
import time

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, os.path.dirname(__file__))

from comic_pile_api import API_BASE, get_all_threads, login
from wildstorm_chains import load_chains

SD = "/media/josh/6103-A8BB/comics"
DATA_DIR = "/mnt/extra/josh/code/comic-ripper/data"

# Map thread title → SD card directory name
SERIES_DIR_MAP = {
    # Wildstorm
    "Stormwatch Vol. 1": "Stormwatch-1993",
    "Stormwatch Vol. 2": "Stormwatch-1997",
    "The Authority": "The-Authority-1999",
    "Planetary": "Planetary",
    "WildC.A.T.s/Aliens": "WildC.A.T.s-Aliens",
    "Planetary/The Authority: Ruling the World": "Planetary-Authority-Ruling-the-World",
    "Planetary/JLA: Terra Occulta": "Planetary-JLA-Terra-Occulta",
    "Planetary/Batman: Night on Earth": None,
    "Jenny Sparks: The Secret History of the Authority": None,
    # Absolute Earth-0 / K.O.
    "Dark Nights: Death Metal": "Dark-Nights-Death-Metal",
    "Superman": "Superman-2023",
    "The Flash": "The-Flash-2023",
    "Justice League Unlimited": "Justice-League-Unlimited-2024",
    "Justice League: Dark Tomorrow Special": "Justice-League-Dark-Tomorrow-Special",
    "Justice League: The Omega Act Special": "Justice-League-The-Omega-Act-Special",
    "Summer of Superman Special": "Summer-of-Superman-Special",
    "DC K.O.": "DC-K-O",
    "Free Comic Book Day 2025: DC All In Special Edition": "Free-Comic-Book-Day-2025",
    # Absolute titles
    "Absolute Batman": "Absolute-Batman",
    "Absolute Wonder Woman": "Absolute-Wonder-Woman",
    "Absolute Superman": "Absolute-Superman",
    "Absolute Flash": "Absolute-Flash",
    "Absolute Martian Manhunter": "Absolute-Martian-Manhunter",
    "Absolute Green Lantern": "Absolute-Green-Lantern",
    "Absolute Green Arrow": None,
    "Absolute Catwoman": None,
    "Absolute Specials": None,
    "Absolute Evil": "Absolute-Evil",
    "Absolute Batman: Ark M Special": "Absolute-Batman-Ark-M-Special",

    # Ultimate
    "Ultimate Spider-Man": "Ultimate-Spider-Man-2024",
    "Ultimate Black Panther": "Ultimate-Black-Panther",
    "Ultimate X-Men": "Ultimate-X-Men-2024",
    "The Ultimates": "The-Ultimates-2024",
    "Ultimate Wolverine": "Ultimate-Wolverine",
    "Ultimate Spider-Man: Incursion": "Ultimate-Spider-Man-Incursion",
    "Ultimate Endgame": "Ultimate-Endgame",
    "Ultimate Universe: One Year In": "Ultimate-Universe-One-Year-In",
    "Ultimate Universe: Two Years In": "Ultimate-Universe-Two-Years-In",
    "Miles Morales: Spider-Man": "Miles-Morales-Spider-Man-2022",
    "Free Comic Book Day 2024: Ultimate Universe / Spider-Man": "Free-Comic-Book-Day-2024",
    "Free Comic Book Day 2025: Amazing Spider-Man / Ultimate Universe": "Free-Comic-Book-Day-2025",
    "Ultimate Impact: Reborn": None,
    "Ultimate Hawkeye": None,
    "Ultimate Universe: Finale": None,
}

# Special file name overrides for one-shots
SPECIAL_FILES = {
    ("Justice League: Dark Tomorrow Special", "1"): "full.cbz",
    ("Justice League: The Omega Act Special", "1"): "full.cbz",
    ("Summer of Superman Special", "1"): "full.cbz",
    ("Free Comic Book Day 2024: Ultimate Universe / Spider-Man", "1"): "Universe.cbz",
    ("Free Comic Book Day 2025: DC All In Special Edition", "1"): "All.cbz",
    ("Free Comic Book Day 2025: Amazing Spider-Man / Ultimate Universe", "1"): "Spider.cbz",
    ("Ultimate Universe: One Year In", "1"): "full.cbz",
    ("Ultimate Universe: Two Years In", "1"): "full.cbz",
    ("Absolute Batman: Ark M Special", "1"): "full.cbz",
    ("Absolute Evil", "1"): "full.cbz",
}


def map_to_file(title, issue_num):
    """Map (title, issue_number) to SD card CBZ file path."""
    sd_dir = SERIES_DIR_MAP.get(title)
    if sd_dir is None:
        return None

    # Check for special file names
    special_key = (title, str(issue_num))
    if special_key in SPECIAL_FILES:
        sf = SPECIAL_FILES[special_key]
        for base in (SD, DATA_DIR):
            p = os.path.join(base, sd_dir, sf)
            if os.path.isfile(p):
                return p
        return None

    # FCBD 2025: distinguish All vs Spider
    if sd_dir == "Free-Comic-Book-Day-2025":
        if "DC All In" in title:
            p = os.path.join(SD, sd_dir, "All.cbz")
            return p if os.path.isfile(p) else None
        elif "Amazing Spider-Man" in title or "Ultimate Universe" in title:
            p = os.path.join(SD, sd_dir, "Spider.cbz")
            return p if os.path.isfile(p) else None
        return None

    # Regular issue number as filename
    fname = f"{issue_num}.cbz"
    for base in (SD, DATA_DIR):
        p = os.path.join(base, sd_dir, fname)
        if os.path.isfile(p):
            return p
    return None


def build_issue_read_status(token):
    """Query API for all threads and get {title: {issue_num: status}}."""
    all_threads = get_all_threads(token)
    read_status = {}
    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {token}"

    skipped = 0
    for title, t in all_threads.items():
        total = t.get("total_issues")
        if not total:
            read_status[title] = {}
            skipped += 1
            continue

        # Fetch with retries, using pagination like get_thread_issues
        issues = {}
        page_token = ""
        for attempt in range(3):
            try:
                while True:
                    params = {"page_token": page_token} if page_token else {}
                    r = session.get(
                        f"{API_BASE}/api/v1/threads/{t['id']}/issues",
                        params=params,
                        timeout=60,
                    )
                    r.raise_for_status()
                    data = r.json()
                    for issue in data.get("issues", []):
                        num = issue.get("issue_number", "")
                        issues[num] = issue.get("status", "unread")
                    page_token = data.get("next_page_token", "")
                    if not page_token:
                        break
                break
            except (requests.RequestException, ConnectionError) as e:
                if attempt == 2:
                    print(f"  Warning: failed to fetch issues for '{title}': {e}")
                    issues = {}
                else:
                    time.sleep(2)

        read_status[title] = issues

    if skipped:
        print(f"  Skipped {skipped} threads without issue tracking")
    return read_status


def expand_chain(edges, max_issues=None):
    """Expand a chain of (title, issue) edges by filling same-series gaps.

    Puts fills BEFORE the current edge (since edges are blocking points
    reached after reading intermediate issues).

    Args:
        edges: List of (title, issue_number_str) tuples
        max_issues: Dict mapping title -> total_issues, used to fill
                    remaining issues after the last edge of each series
    """
    result = []
    for i, (title, issue) in enumerate(edges):
        issue_num = int(issue)

        # Find last occurrence of this series and fill gaps
        if i > 0:
            for j in range(i - 1, -1, -1):
                prev_title, prev_issue_str = edges[j]
                if prev_title == title:
                    prev_num = int(prev_issue_str)
                    if prev_num + 1 < issue_num:
                        for mid in range(prev_num + 1, issue_num):
                            result.append((title, str(mid)))
                    break

        result.append((title, str(issue_num)))

    return result


def fill_gaps_and_remaining(order, read_status):
    """Fill gaps between same-series occurrences and remaining after last.

    Processes items sequentially. For each (title, issue):
    1. If there was a pending gap-fill for this title, insert it now
    2. Add the current item
    3. Look ahead in the ORIGINAL order for the next same-series issue.
       If non-consecutive, queue the gap-fill.
    4. If no next same-series found, add remaining unread issues.

    This correctly handles cross-chain gaps and remaining issues.
    """
    result = []
    pending = {}  # title -> [items to insert]

    for idx, (title, issue) in enumerate(order):
        # Insert any pending items for this title
        if title in pending:
            result.extend(pending[title])
            del pending[title]

        result.append((title, issue))

        if not issue.isdigit():
            continue

        current_num = int(issue)
        statuses = read_status.get(title, {})

        # Look ahead in original order for next same-series occurrence
        next_num = None
        for other_title, other_issue in order[idx + 1:]:
            if other_title == title and other_issue.isdigit():
                next_num = int(other_issue)
                break

        if next_num is not None:
            # Fill gap between current and next occurrence
            if current_num + 1 < next_num:
                to_add = []
                for gn in range(current_num + 1, next_num):
                    item = (title, str(gn))
                    if statuses.get(str(gn), "unread") == "unread":
                        to_add.append(item)
                if to_add:
                    pending[title] = to_add
        else:
            # Last occurrence - add remaining unread issues
            to_add = []
            for num_str, st in statuses.items():
                if num_str.isdigit() and int(num_str) > current_num and st == "unread":
                    item = (title, num_str)
                    if item not in result and item not in order:
                        to_add.append(item)
            if to_add:
                to_add.sort(key=lambda x: int(x[1]))
                result.extend(to_add)

    # Flush any remaining pending items
    for _title, items in pending.items():
        for item in items:
            if item not in result:
                result.append(item)

    return result


def build_wildstorm_order(read_status):
    """Build Wildstorm reading order from YAML chains with same-series fills."""
    yaml_chains = load_chains()
    order = []

    # Concatenate expanded chains (filter out read issues)
    for chain_name in ["stormwatch", "planetary_authority", "planetary_late"]:
        if chain_name not in yaml_chains:
            continue
        edges = yaml_chains[chain_name]
        expanded = expand_chain(edges)
        for item in expanded:
            title, issue = item
            st = read_status.get(title, {}).get(issue, "unread")
            if st == "unread" and item not in order:
                order.append(item)

    # Fill gaps between chains and remaining after last occurrences
    order = fill_gaps_and_remaining(order, read_status)

    return order


def build_absolute_order(read_status):
    """Build Absolute Universe reading order."""
    order = []

    # Earth-0 chain (strict)
    earth_0 = [
        ("Dark Nights: Death Metal", "7"),
        ("Superman", "23"),
        ("Superman", "26"),
        ("Summer of Superman Special", "1"),
        ("Superman", "27"),
        ("Free Comic Book Day 2025: DC All In Special Edition", "1"),
        ("Superman", "28"),
        ("Justice League: Dark Tomorrow Special", "1"),
        ("Superman", "29"),
        ("Justice League Unlimited", "10"),
        ("Superman", "30"),
        ("Justice League Unlimited", "11"),
        ("Justice League: The Omega Act Special", "1"),
        ("DC K.O.", "1"),
    ]
    expanded = expand_chain(earth_0)
    for item in expanded:
        title, issue = item
        st = read_status.get(title, {}).get(issue, "unread")
        if st == "unread" and item not in order:
            order.append(item)

    # K.O. tie-ins between #1 and #3
    ko_tie_ins = [
        ("Superman", "31"),
        ("Superman", "32"),
        ("Superman", "34"),
        ("Superman", "35"),
        ("The Flash", "26"),
        ("The Flash", "27"),
        ("The Flash", "29"),
        ("The Flash", "30"),
    ]
    expanded_ko = expand_chain(ko_tie_ins)
    for item in expanded_ko:
        title, issue = item
        st = read_status.get(title, {}).get(issue, "unread")
        if st == "unread" and item not in order:
            order.append(item)

    # K.O. continuation: #3 → #4 → #5
    for num in ("3", "4", "5"):
        item = ("DC K.O.", num)
        if read_status.get("DC K.O.", {}).get(num, "unread") == "unread" and item not in order:
            order.append(item)

    # Absolute titles (no blocking) - add all unread issues in numerical order
    absolute_titles = [
        "Absolute Batman",
        "Absolute Batman: Ark M Special",
        "Absolute Wonder Woman",
        "Absolute Superman",
        "Absolute Flash",
        "Absolute Martian Manhunter",
        "Absolute Green Lantern",
        "Absolute Evil",
        "Absolute Green Arrow",
        "Absolute Catwoman",
        "Absolute Specials",
    ]
    for at in absolute_titles:
        statuses = read_status.get(at, {})
        all_nums = sorted(int(k) for k in statuses.keys() if k.isdigit())
        for num in all_nums:
            item = (at, str(num))
            if statuses.get(str(num), "unread") == "unread" and item not in order:
                order.append(item)

    return order


# Ultimate reading order (from create_ultimate_universe_from_scratch.py)
ULTIMATE_ORDER = [
    ("Free Comic Book Day 2024: Ultimate Universe / Spider-Man", "1"),
    ("Ultimate Spider-Man", "1"),
    ("Ultimate Black Panther", "1"),
    ("Ultimate Spider-Man", "2"),
    ("Ultimate X-Men", "7"),
    ("Ultimate Black Panther", "2"),
    ("Ultimate Spider-Man", "3"),
    ("Ultimate X-Men", "8"),
    ("Ultimate Black Panther", "3"),
    ("Ultimate Spider-Man", "4"),
    ("Ultimate X-Men", "9"),
    ("Ultimate Black Panther", "4"),
    ("Ultimate Spider-Man", "5"),
    ("The Ultimates", "1"),
    ("Ultimate X-Men", "10"),
    ("Ultimate Spider-Man", "6"),
    ("Ultimate Black Panther", "5"),
    ("The Ultimates", "2"),
    ("Ultimate X-Men", "11"),
    ("Ultimate Black Panther", "6"),
    ("Ultimate Spider-Man", "7"),
    ("Ultimate Black Panther", "7"),
    ("The Ultimates", "3"),
    ("Ultimate Spider-Man", "8"),
    ("Ultimate X-Men", "12"),
    ("The Ultimates", "4"),
    ("Ultimate Black Panther", "8"),
    ("Ultimate X-Men", "13"),
    ("Ultimate Spider-Man", "9"),
    ("Ultimate Black Panther", "9"),
    ("The Ultimates", "5"),
    ("Ultimate Spider-Man", "10"),
    ("Ultimate X-Men", "14"),
    ("The Ultimates", "6"),
    ("Ultimate X-Men", "15"),
    ("Ultimate Spider-Man", "11"),
    ("Ultimate Black Panther", "10"),
    ("The Ultimates", "7"),
    ("Ultimate Universe: One Year In", "1"),
    ("Ultimate X-Men", "16"),
    ("Ultimate Spider-Man", "12"),
    ("Ultimate Black Panther", "11"),
    ("The Ultimates", "8"),
    ("Ultimate Black Panther", "12"),
    ("Ultimate Wolverine", "1"),
    ("Ultimate Spider-Man", "13"),
    ("Ultimate X-Men", "17"),
    ("The Ultimates", "9"),
    ("Ultimate Black Panther", "13"),
    ("Ultimate Wolverine", "2"),
    ("Ultimate Spider-Man", "14"),
    ("Ultimate X-Men", "18"),
    ("The Ultimates", "10"),
    ("Ultimate Black Panther", "14"),
    ("Ultimate X-Men", "19"),
    ("Ultimate Spider-Man", "15"),
    ("Ultimate Wolverine", "3"),
    ("Ultimate X-Men", "20"),
    ("The Ultimates", "11"),
    ("Ultimate Wolverine", "4"),
    ("Ultimate Black Panther", "15"),
    ("Ultimate Spider-Man", "16"),
    ("Free Comic Book Day 2025: Amazing Spider-Man / Ultimate Universe", "1"),
    ("Ultimate Wolverine", "5"),
    ("Ultimate Black Panther", "16"),
    ("Ultimate X-Men", "21"),
    ("The Ultimates", "12"),
    ("Ultimate Spider-Man", "17"),
    ("Ultimate Wolverine", "6"),
    ("Ultimate Spider-Man: Incursion", "1"),
    ("Ultimate Black Panther", "17"),
    ("Ultimate X-Men", "22"),
    ("The Ultimates", "13"),
    ("Ultimate Spider-Man", "18"),
    ("Ultimate Wolverine", "7"),
    ("Ultimate Spider-Man: Incursion", "2"),
    ("Ultimate Black Panther", "18"),
    ("Ultimate X-Men", "23"),
    ("Ultimate Spider-Man", "19"),
    ("The Ultimates", "14"),
    ("Ultimate X-Men", "24"),
    ("Ultimate Wolverine", "8"),
    ("The Ultimates", "15"),
    ("Ultimate Spider-Man: Incursion", "3"),
    ("Ultimate Black Panther", "19"),
    ("Ultimate Spider-Man", "20"),
    ("Ultimate X-Men", "25"),
    ("Ultimate Wolverine", "9"),
    ("Ultimate Spider-Man: Incursion", "4"),
    ("Ultimate Black Panther", "20"),
    ("The Ultimates", "16"),
    ("Ultimate Spider-Man", "21"),
    ("Ultimate Hawkeye", "1"),
    ("Ultimate Wolverine", "10"),
    ("Ultimate Black Panther", "21"),
    ("Ultimate Spider-Man", "22"),
    ("Ultimate Spider-Man: Incursion", "5"),
    ("The Ultimates", "17"),
    ("Ultimate Black Panther", "22"),
    ("Ultimate Wolverine", "11"),
    ("The Ultimates", "18"),
    ("Ultimate Universe: Two Years In", "1"),
    ("Ultimate Black Panther", "23"),
    ("Ultimate Wolverine", "12"),
    ("Ultimate Spider-Man", "23"),
    ("Ultimate Endgame", "1"),
    ("The Ultimates", "19"),
    ("Ultimate Wolverine", "13"),
    ("The Ultimates", "20"),
    ("Ultimate Black Panther", "24"),
    ("Ultimate Endgame", "2"),
    ("Ultimate Wolverine", "14"),
    ("Ultimate Spider-Man", "24"),
    ("The Ultimates", "21"),
    ("The Ultimates", "22"),
    ("Ultimate Wolverine", "15"),
    ("Ultimate Endgame", "3"),
    ("Ultimate Wolverine", "16"),
    ("The Ultimates", "23"),
    ("Ultimate Endgame", "4"),
    ("The Ultimates", "24"),
    ("Ultimate Endgame", "5"),
    ("Ultimate Universe: Finale", "1"),
    ("Miles Morales: Spider-Man", "1"),
    ("Ultimate Impact: Reborn", "1"),
]


def build_ultimate_order(read_status):
    """Build Ultimate reading order, filtering out already-read issues."""
    order = []
    for title, issue in ULTIMATE_ORDER:
        st = read_status.get(title, {}).get(issue, "unread")
        if st == "unread" and (title, issue) not in order:
            order.append((title, issue))

    # Fill remaining unread issues for Ultimate series (issues not in the order)
    series_in_order = {title for title, _ in order}
    for title in series_in_order:
        statuses = read_status.get(title, {})
        all_nums = sorted(int(k) for k in statuses.keys() if k.isdigit())
        last_in_order = 0
        for t, i in order:
            if t == title and i.isdigit():
                last_in_order = max(last_in_order, int(i))
        for num in all_nums:
            if num > last_in_order:
                item = (title, str(num))
                if statuses.get(str(num), "unread") == "unread" and item not in order:
                    order.append(item)

    return order


def rebuild_reading_order(name, sd_dir, reading_order, dry_run=False):
    """Clear and rebuild a reading order directory on the SD card."""
    target_dir = os.path.join(SD, sd_dir)

    if dry_run:
        print(f"\n[Dry Run] Would rebuild {name} at {target_dir}")
    else:
        print(f"\n=== Rebuilding {name} ===")
        if os.path.isdir(target_dir):
            for f in os.listdir(target_dir):
                fpath = os.path.join(target_dir, f)
                if f.endswith(".cbz") or f.endswith(".pdf"):
                    os.remove(fpath)
        else:
            os.makedirs(target_dir, exist_ok=True)

    copied = 0
    skipped_no_file = 0
    skipped_missing = []

    counter = 0
    for title, issue_num in reading_order:
        file_path = map_to_file(title, str(issue_num))
        if file_path is None:
            skipped_no_file += 1
            if len(skipped_missing) < 10:
                skipped_missing.append(f"{title} #{issue_num}")
            continue

        counter += 1
        ext = os.path.splitext(file_path)[1]
        safe_title = title.replace(":", "").replace("/", "-")
        dest_name = f"{counter:03d} - {safe_title} #{issue_num}{ext}"
        dest_path = os.path.join(target_dir, dest_name)

        if dry_run:
            print(f"  Would copy: {dest_name}")
        else:
            shutil.copy2(file_path, dest_path)
        copied += 1

    print(f"  Result: {copied} files")
    if skipped_missing:
        print(f"  Missing files: {skipped_missing}")
        if skipped_no_file > len(skipped_missing):
            print(f"    ... and {skipped_no_file - len(skipped_missing)} more")
    return copied


def main() -> int:
    """Rebuild selected reading-order directories from current API state."""
    parser = argparse.ArgumentParser(description="Rebuild reading order directories")
    parser.add_argument("--dry-run", action="store_true", help="Only print what would be done")
    parser.add_argument("--universe", choices=["wildstorm", "absolute", "ultimate", "all"],
                        default="all", help="Which reading order to rebuild")
    args = parser.parse_args()

    username = os.environ.get("COMIC_PILE_USERNAME")
    password = os.environ.get("COMIC_PILE_PASSWORD")
    if not username or not password:
        print("Set COMIC_PILE_USERNAME and COMIC_PILE_PASSWORD")
        return 1

    print("Authenticating...")
    token = login(username, password)
    print("Authenticated")

    print("\nFetching read status...")
    read_status = build_issue_read_status(token)
    print(f"  Got {len(read_status)} threads")

    universes = []
    if args.universe in ("wildstorm", "all"):
        universes.append(("Wildstorm", "Wildstorm-reading-order",
                          build_wildstorm_order(read_status)))
    if args.universe in ("absolute", "all"):
        universes.append(("Absolute Universe", "Absolute-Universe-reading-order",
                          build_absolute_order(read_status)))
    if args.universe in ("ultimate", "all"):
        universes.append(("Ultimate Universe", "Ultimate-Universe-reading-order",
                          build_ultimate_order(read_status)))

    for name, sd_dir, order in universes:
        rebuild_reading_order(name, sd_dir, order, dry_run=args.dry_run)

    return 0


if __name__ == "__main__":
    main()
