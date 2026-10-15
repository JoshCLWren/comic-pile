# Read-only Option E dependency and frontier census

Issue #3661 adds an offline evidence report. It does not change Roll, classify historical
edges as approved, repair pointers, or execute the production operation in #3588.

Run from the repository root with an explicitly supplied asyncpg URL:

```bash
uv run python -m scripts.report_dependency_provenance \
  --database-url "$CENSUS_DATABASE_URL" --user-id 1 > dependency-provenance.json
```

The report runs in a PostgreSQL-enforced read-only, repeatable-read transaction with
ORM autoflush disabled. There is no default database URL, apply flag, or migration.
Keep reports private: they contain reader-owned source notes and stable row identities.

`edges` accounts for each dependency touching an owned endpoint exactly once, except
inert `cbl-order:` rows, which are counted separately. Endpoint details are restricted
to owned Issues/Threads. Unresolved/foreign endpoints keep their edge identifiers but
expose no foreign titles, status, or list membership. Source/target list IDs, plan
references and explanations, matching rules, legacy links, compiler-note rule references,
and conflicting or missing rule evidence remain visible. Cross-list counts mean both
endpoints have list memberships with no shared list; unlisted endpoints are not guessed
into a list. Active frontier blocker counts measure dependency rows, not unique Threads;
a missing or foreign source is retained in the inventory but is not a confirmed Roll blocker.

The A/B/C/D vocabulary follows the accepted Reading List ADR. A requires reviewed
reader-authorship evidence; C requires preserved generation evidence. Existing arbitrary
notes, plan links, and compiler markers do not prove either, so this report conservatively
leaves them D. A matching checkpoint rule alone cannot prove the dependency's origin; such edges remain D.
Multiple competing rules, missing referenced rules, or mismatching provenance remain D.
Neither B nor any other report field authorizes retirement. Historical overwritten notes
cannot be recovered by inference; review the retained evidence before making decisions.

`frontiers` includes every owned Thread regardless of status and derives first unread
using `(Issue.position, Issue.id)`. It compares stored pointers and counters without
using them as authority. Only status `read` is complete, matching the pure frontier service.
This is a storage census before exclusion enforcement; no exclusion or list-local skip is
inferred. `known_3588_threads` separately enumerates all 24 stable IDs from #3588, including
completed shells and explicit `missing_or_deleted` records. Missing means absent from
this reader's current ownership scope; it does not prove when or why a row disappeared.

Counts reflect the supplied snapshot, never the dated production counts in the ADR.
This implementation has no production report attached and does not replace fresh
owner-reviewed production evidence for later conversion or repair.
