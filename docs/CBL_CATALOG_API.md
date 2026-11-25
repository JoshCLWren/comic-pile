# Shared CBL catalog API

Authenticated readers browse the persisted source catalog, including readers with no comics. These native read-only routes do not reconcile owned issues, create Reading Lists, or fetch GitHub.

- `GET /api/v1/issue-identity/cbl-sources/folders?folder=DC` returns immediate child folders, breadcrumbs, and direct/recursive active-list counts. Omit `folder` for the root.
- `GET /api/v1/issue-identity/cbl-sources/browse?folder=DC&page=1&page_size=50` returns immediate folders and a page of directly contained source lists.
- Add `q` to browse to search names and source-relative paths across the whole catalog. Search treats `%` and `_` literally; a nonempty query ignores folder scope.

Pages are one-based with at most 100 items. `total`, `total_pages`, `has_next`, and `has_previous` describe the complete matching set. Ordering is stable by name, source path, then source-list ID. Pages beyond the matching set clamp to the last nonempty page rather than sending an unbounded offset. Empty root/search results are successful empty responses. Missing folders return 404, malformed paths 400, and invalid pagination 422. Pool-acquisition outages use the global 503 `database_unavailable` envelope; SQL failures use the generated 503 `CBLErrorResponse` contract.

Folder paths preserve spaces and forward slashes. Empty/traversal segments, backslashes, and control characters are rejected. Source detail remains at `GET /api/v1/issue-identity/cbl-sources/{list_id}` with bounded occurrence pagination.

The native implementation is `native/roll-service/src/cbl_catalog.rs`. Indexes and `pg_trgm` are owned by the refinery baseline (`native/migrate/migrations/V1__baseline.sql`), not an active Alembic revision. The catalog is read-only; source ingestion is a separate operational concern.

Focused verification uses the native DB-backed HTTP suite:

```bash
RUST_ROLL_TEST_DATABASE_URL=postgresql://... \
  cargo test --locked -p comicpile-roll-service --test cbl_catalog
```

Coverage includes nested folders, pagination/clamping, literal wildcard characters, inactive sources, and error contracts. Dedicated route-precedence and ownership assertions are not claimed here; preserve those checks in the owning HTTP/auth suites when they change.
