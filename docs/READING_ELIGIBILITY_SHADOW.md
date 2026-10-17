# Read-only Reading List eligibility comparison

Option E's shadow report compares the existing stored frontier/cache with derived
frontiers and hypothetical eligibility from current authored Reading List modes,
gates, skips, explicit requirements and resolved collection exclusions. It does
not activate lists, repair pointers, refresh blocked flags or change Roll.

Run from the repository root with an explicit async PostgreSQL URL:

```bash
uv run python -m scripts.report_reading_eligibility \
  --database-url "$READING_SHADOW_DATABASE_URL" --user-id 1 > reading-shadow.json
```

The CLI uses a PostgreSQL-enforced read-only, repeatable-read transaction with
autoflush disabled. It never loads the URL from application settings. Normal
For the **app-wide Option E cutover** (#3676), inspect every reader in one
repeatable-read snapshot and save the fingerprinted acceptance evidence:

```bash
uv run python -m scripts.report_reading_eligibility \\
  --database-url "$READING_SHADOW_DATABASE_URL" --all-readers > reading-all-readers.json
```

The all-reader result contains separate owner-scoped reports (including readers with
no lists), aggregate reader-validity and eligible/blocked divergence counts, and a
SHA-256 `source_fingerprint` of the complete read-only report. A valid graph is a
necessary condition, not proof that every offered comic matches current intent;
review known crossover, annual, strict-list and event-hold examples before
production enablement. Historical/converted dependency rows are audit evidence,
not automatic canonical blockers; the shadow comparison still records their
legacy effect.

Roll requests are unaffected; `shadow_reading_eligibility` is also available to
an explicit diagnostic caller alongside the current runtime.

`schema_version=1` contains stable IDs, complete aggregate counts, per-Thread
details, list sizes and diagnostics. It excludes usernames, titles, credentials
and historical note prose. Default limits are 1,000 Thread/list/diagnostic details
and 50 blockers/waiting Issues per Thread. Set `--max-threads` and `--max-blockers`
for a larger artifact. Every detail collection carries an explicit truncation
indicator; totals always cover the whole snapshot.

Every owned Thread reports these observations, including inactive frontier defects.
Inactive Threads remain outside both candidate pools:

- `stored_next_issue_id`, pointer validity and `derived_next_issue_id`: first
  unread non-excluded Issue by position and stable ID, independent of cached counters.
  A foreign/unresolved stored pointer is redacted while its presence and invalidity remain visible.
- `stored_is_blocked`, `legacy_stored_frontier_blocked` and
  `legacy_derived_frontier_blocked`: distinguish stale flags from blockers hidden
  by a stale pointer. Only non-inert historical requirements participate.
- `current_pool_candidate`: the current stored-cache queue predicate, before dice
  limit, session skips and snoozes. Empty shell Threads can currently satisfy it.
- `proposed_eligible` and `proposed_pool_candidate`: the single pure evaluator's
  proposed answer, plus queue-position filtering. Blockers include list/prerequisite
  IDs, gate IDs, concrete unread Issue IDs and prerequisite origin.
- `frontier_divergence`, `cache_divergence` and `eligibility_divergence` identify
  different defects; agreement in one does not prove correctness in another.

Current Custom CBL entries supply the entire authored order. Shorter normalized
Reading Plan memberships and plan JSON are never substituted for those entries.
Loose lists do not infer annual gates or hard adjacency. Inert `cbl-order:` rows
are counted in SQL and never loaded as runtime requirements. Enforced legacy
requirements retain stable endpoints, with provisional converted origin and
unknown historical classification; this is observational metadata, not approval
or a database backfill.

The loader uses a constant number of owner-scoped bulk queries, including Issues
in inactive Threads needed as prerequisite sources. It never walks the legacy
Reading Plan/ContinuityRule graph or runs the retiring compiler. The pure global
cycle validator checks only series order, list intent and explicit requirements.
Foreign list/requirement references, stranded exclusions and cycles produce
`valid=false` and null proposed eligibility/divergence. They never become an
apparently successful parity result by dropping unresolved constraints.

This report is evidence for #3672 and the guarded conversion/activation review in
#3676. A valid report or zero diff neither authorizes a production write nor
satisfies the Option E trust milestone. Reader review and fresh approved previews
remain required by [the ADR](READING_LIST_EXECUTION_ADR.md).
