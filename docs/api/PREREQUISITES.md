# Stable explicit prerequisites

`/api/v1/prerequisites/` authors stable Issue-to-Issue requirements on the existing
`dependencies` table. It does not activate Option E, convert historical rows, or
change reading progress. A requirement has no owning list: list placement, reordering,
skipping and deletion do not rewrite its endpoints.

- `GET /` returns both-endpoint-owned requirements and read-only provenance.
- `POST /` accepts `source_issue_id`, `target_issue_id` and an optional `note`.
  Identical already-authored pairs are idempotent. A deliberate POST of a historical
  pair validates the canonical graph, then adopts that same row as `origin=reader`,
  `classification=A`, with server-recorded reader provenance (no duplicate edge).
  New rows use the same provenance.
- `PATCH /{id}` accepts only a note; `DELETE /{id}` removes the requirement.
  Both writes are limited to explicitly reader-authored rows. Historical/converted
  rows return 409 unless first adopted by an explicit validated POST.

Endpoint ownership is checked through both Issues' Threads. Unavailable endpoints
return 404; self-references, stranded prerequisites and combined graph cycles return
422. Writes serialize on the same reader lock as Reading List authoring and validate
series order, all authored lists, explicit requirements and resolved exclusions,
including constraints involving already-read Issues. Cycle errors include paths and origins.

The additive migration leaves historical origin, classification and provenance NULL.
NULL means unconverted historical data, never reader approval. A reviewed future
conversion may use `origin=converted` with class A/B/C/D and original-source provenance;
class D preserves archive information, but does not govern Option E execution.
Only an explicit validated reader POST promotes an existing pair to an effective
prerequisite; the API does not accept client-supplied classification or provenance.

The existing unique endpoint constraint enforces a single stable pair. Issue ownership
scopes that pair to its reader; the API rejects cross-reader endpoints. Multiple lists
can refer to either endpoint without claiming ownership of the requirement.

This is the additive authoring boundary from #3669. The legacy dependency APIs and
runtime remain transitional until the separately guarded Option E cutover (#3673/#3676).
