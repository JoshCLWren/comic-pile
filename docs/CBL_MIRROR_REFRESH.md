# CBL Mirror Refresh Runbook

The shared CBL catalog is a read-only consumer of the persisted `cbl_sources`,
`cbl_source_lists`, and `cbl_source_entries` tables; see
[CBL_CATALOG_API.md](CBL_CATALOG_API.md). A refresh is an **offline,
non-destructive** operation: the Rust `cbl_ingest` binary reads a pinned local
checkout of `JoshCLWren/CBL-ReadingLists`, never fetches GitHub, and never runs
from an application request. The retired Python `scripts.sync_cbl_mirror` CLI
does not ship; all commands below use the native binary.

A production refresh is an ordinary authorized operational change: run the
inventory and dry-run first, attach their JSON to the owning issue/PR, then use
the existing trusted application/operational workflow with its existing
credentials to apply the same pinned revision. Direct agent access to a
production database, destructive cleanup, and personal reader-data repairs
remain prohibited without separate explicit authorization. The ingester never
starts ComicVine background hydration.

## 1. Pin and inventory the mirror

Check out the intended mirror revision locally and record its exact SHA:

```bash
COMIC_PILE_ROOT="/path/to/comic-pile"
cd /path/to/CBL-ReadingLists
git fetch origin
git checkout <pinned-sha>
test -z "$(git status --porcelain)" || { echo "mirror worktree must be clean" >&2; exit 1; }
MIRROR_SHA="$(git rev-parse HEAD)"
MIRROR_ROOT="$(pwd)"
```

Run the database-free inventory from the Comic Pile workspace, not from the mirror:

```bash
cargo run --locked --manifest-path "$COMIC_PILE_ROOT/Cargo.toml" \
  -p comicpile-roll-service --bin cbl_ingest -- \
  "$MIRROR_ROOT" --revision-sha "$MIRROR_SHA" --inventory-only
```

This prints one JSON object containing `mode`, `repository`, `revision_sha`,
`inventory`, `parsed_lists`, and `parse_failures`. The inventory contains:

- aggregate file counts (`total_files`, `parsed_files`, `failed_files`);
- ordered-entry counts and Comic Vine series/issue/pair counts;
- distinct Comic Vine identity counts;
- duplicate content-hash groups, duplicate source paths, and declared-`NumIssues` mismatches;
- per-publisher file/parse/failure counts (`publishers`);
- one `files` row per parsed path with its exact source-relative path, SHA-256 content hash,
  publisher, entry count, and Comic Vine ID counts;
- every parse failure with its source path and message.

Every mode exits `1` when any file fails to parse, but still emits its complete
JSON report. Inventory mode opens no database connection. Database modes retain
last-known-good rows for malformed paths and may apply valid files, but the
nonzero status prevents a trusted workflow from treating a partial refresh as a
clean success. Repeating inventory against the same checked-out revision produces
the same report.

## 2. Preview the reconciliation

Use the same pinned SHA and local mirror for a database dry-run. The trusted
workflow's credentials are read from `CBL_INGEST_DATABASE_URL`, falling back to
`RUST_ROLL_DATABASE_URL` and then the deployment `DATABASE_URL`. In the existing
trusted production operations runner, map its established `MIGRATE_DATABASE_URL`
credential to `CBL_INGEST_DATABASE_URL` for this command; do not provision a new
agent credential or connect an agent directly to production:

```bash
CBL_INGEST_DATABASE_URL="$MIGRATE_DATABASE_URL" \
cargo run --locked --manifest-path "$COMIC_PILE_ROOT/Cargo.toml" \
  -p comicpile-roll-service --bin cbl_ingest -- \
  "$MIRROR_ROOT" --revision-sha "$MIRROR_SHA" --dry-run
```

The JSON adds `source_created`, `inserted_lists`, `updated_lists`,
`deactivated_lists`, `unchanged_lists`, `entries_written`, `identities_upserted`,
`dry_run`, `changed`, and `repository_reconciled`. A dry run performs reads
only; it writes no source, list, entry, or identity rows.

If production still uses a legacy machine-path source identity, pass it as an
alias without editing the database by hand:

```bash
cargo run --locked --manifest-path "$COMIC_PILE_ROOT/Cargo.toml" \
  -p comicpile-roll-service --bin cbl_ingest -- \
  "$MIRROR_ROOT" --revision-sha "$MIRROR_SHA" \
  --repository JoshCLWren/CBL-ReadingLists \
  --reconcile-repository /mnt/bigdata/CBL-ReadingLists \
  --dry-run
```

The alias is renamed in place on the applying run, so the existing
`cbl_sources.id` and every `cbl_source_lists.id` are preserved instead of
creating a duplicate source and re-inserting every list. If both the canonical
repository and an alias already exist, the canonical row wins and the alias is
ignored. More than one matching alias is rejected before any write.

## 3. Apply the refresh

Remove `--dry-run` after reviewing the counts, using the trusted workflow with
its existing credentials:

```bash
CBL_INGEST_DATABASE_URL="$MIGRATE_DATABASE_URL" \
cargo run --locked --manifest-path "$COMIC_PILE_ROOT/Cargo.toml" \
  -p comicpile-roll-service --bin cbl_ingest -- \
  "$MIRROR_ROOT" --revision-sha "$MIRROR_SHA" \
  --repository JoshCLWren/CBL-ReadingLists \
  --reconcile-repository /mnt/bigdata/CBL-ReadingLists
```

Refresh behavior:

- A file whose content hash is unchanged stays untouched; replaying the same
  revision and hashes performs no writes and does not restamp `synced_at`. If a
  previously removed file returns with the same hash, only its list metadata is
  reactivated; existing entry IDs and reader decisions are preserved.
- A changed file replaces only its own ordered entries and receives the new revision SHA.
- A file missing from the new revision is retained and marked inactive; its rows are never
  hard-deleted, so existing reader references survive.
- A file present but malformed is protected by source path: its last known-good list and entries
  remain active.
- Publisher and arbitrarily nested source paths are preserved verbatim as source-relative paths.
- Optional `Volume` and `Year` values containing the explicit `None` sentinel (case-insensitive,
  surrounding whitespace ignored) are preserved as unknown years. The occurrence stays in source
  order; missing provider identities remain unresolved. Other malformed numeric values and missing
  required `Series`/`Number` still produce a path-specific parse failure. `NumIssues` remains numeric.
- Comic Vine IDs are recorded as `external_identities` rows keyed by
  `(provider, entity_type, external_id)`, and CBL entries reference them.

All writes happen in one transaction and use bounded set-based `unnest` batches
for lists, identities, and entries; no SQL runs per entry row.

## Validation

The ingester and catalog regressions are DB-backed and run against the
canonical disposable schema:

```bash
cargo test -p comicpile-roll-service --lib cbl_ingest
cargo test -p comicpile-roll-service --test cbl_ingest
cargo test -p comicpile-roll-service --test cbl_catalog
```

They cover repeatable/idempotent reruns, changed revisions, removal as
deactivation, unchanged reactivation with stable entry IDs, parse-failure and
malformed-structure protection, repository-alias reconciliation, and
browse/search/discovery parity on a synthetic corpus of more than 100 lists.
