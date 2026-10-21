# CBL Mirror Refresh Runbook

This runbook makes a complete `JoshCLWren/CBL-ReadingLists` refresh repeatable and measurable. The
sync is always performed **outside** application requests: the web/API runtime reads the already
persisted `cbl_sources`, `cbl_source_lists`, and `cbl_source_entries` tables and never fetches GitHub
per request.

## 1. Pin and inventory the mirror

Check out the intended mirror revision locally and record its exact SHA:

```bash
cd /path/to/CBL-ReadingLists
git fetch origin
git checkout <pinned-sha>
MIRROR_SHA="$(git rev-parse HEAD)"
MIRROR_ROOT="$(pwd)"
```

Run the database-free inventory:

```bash
uv run python scripts/sync_cbl_mirror.py "$MIRROR_ROOT" \
  --revision-sha "$MIRROR_SHA" \
  --inventory-only
```

This prints one JSON object containing:

- aggregate file counts (`total_files`, `parsed_files`, `failed_files`);
- ordered-entry counts and Comic Vine series/issue/pair counts;
- distinct Comic Vine identity counts;
- duplicate content-hash groups, duplicate source paths, and declared-`NumIssues` mismatches;
- per-publisher file/parse/failure counts;
- one `files` row per parsed path with its exact source-relative path, SHA-256 content hash,
  publisher, entry count, and Comic Vine ID counts;
- every parse failure with its source path and message.

The command exits `1` when any file fails to parse, but still emits the complete inventory. Repeating
it against the same checked-out revision produces byte-identical JSON. No database session is opened.

## 2. Preview the reconciliation

Use the same pinned SHA and local mirror for a database dry-run:

```bash
uv run python scripts/sync_cbl_mirror.py "$MIRROR_ROOT" \
  --revision-sha "$MIRROR_SHA" \
  --dry-run
```

The JSON adds the same `inventory` plus `inserted_lists`, `updated_lists`, `deactivated_lists`,
`unchanged_lists`, `entries_written`, `source_created`, `changed`, and `repository_reconciled`
counters. Dry-run performs reads only; it writes no source, list, entry, or identity rows.

If production still uses a legacy machine-path source identity, pass it as an alias without editing
the database by hand:

```bash
uv run python scripts/sync_cbl_mirror.py "$MIRROR_ROOT" \
  --revision-sha "$MIRROR_SHA" \
  --repository JoshCLWren/CBL-ReadingLists \
  --reconcile-repository /mnt/bigdata/CBL-ReadingLists \
  --dry-run
```

The alias is renamed in place on the applying run, so the existing `cbl_sources.id` and every
`cbl_source_lists.id` are preserved instead of creating a duplicate source and re-inserting every
list. If both the canonical repository and an alias already exist, the canonical row wins and the
alias is ignored. More than one matching alias is rejected before any write.

## 3. Apply the refresh

Remove `--dry-run` after reviewing the counts:

```bash
uv run python scripts/sync_cbl_mirror.py "$MIRROR_ROOT" \
  --revision-sha "$MIRROR_SHA" \
  --repository JoshCLWren/CBL-ReadingLists \
  --reconcile-repository /mnt/bigdata/CBL-ReadingLists
```

Refresh behavior:

- A file whose content hash is unchanged stays untouched.
- A changed file replaces only its own ordered entries and receives the new revision SHA.
- A file missing from the new revision is retained and marked inactive; its rows are never
  hard-deleted, so existing reader references survive.
- A file present but malformed is protected by source path: its last known-good list and entries
  remain active.
- Replaying the same revision and content hashes performs no source/list/entry/identity writes.
- Publisher and arbitrarily nested source paths are preserved verbatim as source-relative paths.

A production bulk source sync remains a separately authorized operation. This script does not run
from a web request, does not fetch GitHub, and does not apply reader repairs.
