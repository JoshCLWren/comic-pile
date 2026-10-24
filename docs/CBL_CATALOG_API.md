# Shared CBL catalog API

Authenticated readers browse the same persisted source catalog, including readers with no comics. These read-only routes do not reconcile owned issues, create Reading Lists, or fetch GitHub.

- `GET /api/v1/issue-identity/cbl-sources/folders?folder=DC` returns immediate child folders, breadcrumbs, and direct/recursive active-list counts. Omit `folder` for the root.
- `GET /api/v1/issue-identity/cbl-sources/browse?folder=DC&page=1&page_size=50` returns immediate folders and a page of directly contained source lists.
- Add `q` to browse to search names and source-relative paths across the whole catalog. Search treats `%` and `_` literally. A nonempty query ignores folder scope.

Pages are one-based with at most 100 items per page; `total`, `total_pages`, `has_next`, and `has_previous` describe the complete matching set. Ordering is stable by name, source path, then source-list ID. Empty root/search results are successful empty responses. Missing folders return 404, malformed paths return 400, invalid pagination returns 422, and database outages return 503. Catalog query errors carry `detail.code` and `detail.message`. A connection failure in request dependencies uses the application-wide `error.code=database_unavailable`, `error.message`, and `error.status=SERVICE_UNAVAILABLE` envelope with `Retry-After`; both outage shapes are included in the generated 503 contract. Pages beyond the matching set return empty items without sending an unbounded offset to PostgreSQL.

Folder paths preserve spaces and use forward slashes, including nested `unsorted` directories. Empty segments, traversal segments, backslashes, and control characters are rejected. Source detail remains at `GET /api/v1/issue-identity/cbl-sources/{list_id}` with bounded occurrence pagination.

Migration `c40080000001` adds an active/path prefix index and name/path trigram indexes using `pg_trgm`. The model declares the same indexes and installs `pg_trgm` before metadata-based PostgreSQL schema creation. It does not ingest sources or change reader data. Catalog coverage depends on separately approved off-request source ingestion; an empty catalog does not trigger ingestion in a request.

Focused verification: `TEST_DATABASE_URL=<isolated PostgreSQL test URL> uv run pytest tests/test_cbl_catalog_api.py -q --no-cov`. Coverage includes two empty accounts, nested folders, more than 100 results, literal wildcard characters, inactive sources, route precedence, fixed query counts, prefix-index selection, and error contracts.
